# -*- coding: utf-8 -*-
"""seamm-environment-storage = archive: build the SEAMM environment on local disk,
publish it as an archive, unpack it into <root>/venvs/<stamp>, switch.

No uv is needed: a 'venv' here is a directory with pyvenv.cfg and bin/python.
"""

import os
from pathlib import Path
import subprocess
import tarfile
from types import SimpleNamespace

import pytest

from seamm_manager import archives, my, policy, venv_archives, versions
from seamm_manager.uv import Uv


def make_venv(path):
    (path / "bin").mkdir(parents=True)
    (path / "pyvenv.cfg").write_text("home = /uv/python\n")
    (path / "bin" / "python").write_text("not really python\n")
    (path / "lib" / "site").mkdir(parents=True)
    (path / "lib" / "site" / "mod.py").write_text(f"# {path.name}\n")
    return path


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = tmp_path / "SEAMM"
    root.mkdir()
    monkeypatch.setattr(my, "uv", Uv(root))
    monkeypatch.setattr(my, "root", root)
    monkeypatch.setattr(my, "options", SimpleNamespace())
    monkeypatch.setattr(versions, "relink_launchers", lambda: None)
    monkeypatch.setattr(versions, "processes_using", lambda prefix: [])
    monkeypatch.setattr(versions, "refused", False)
    monkeypatch.setattr(versions, "switched", False)
    monkeypatch.setattr(versions, "synced_manager", False)
    monkeypatch.setenv("SEAMM_ARCHIVE_BUILD_DIR", str(tmp_path / "build"))
    return root


@pytest.fixture
def fake_uv(monkeypatch):
    """Uv without uv: create makes a fake venv, installs are recorded."""
    import seamm_manager.util as util

    calls = []
    names = iter(["new", "newer", "newest"])

    def create(self, python_version=None, seed=True, relocatable=False):
        calls.append(("create", self.path, relocatable))
        make_venv(self.path)

    def install(self, packages, constraints=None, upgrade=False, **kw):
        calls.append(("install", self.path, list(packages)))
        (self.path / "lib" / "site" / "installed.txt").write_text(" ".join(packages))

    def run(self, *args, **kw):
        calls.append(("run", self.path, [str(a) for a in args]))

    monkeypatch.setattr(Uv, "create", create)
    monkeypatch.setattr(Uv, "install", install)
    monkeypatch.setattr(Uv, "run", run)
    monkeypatch.setattr(Uv, "freeze", lambda self: "seamm==1\n")
    monkeypatch.setattr(Uv, "list", lambda self: {})
    monkeypatch.setattr(
        Uv, "new_version_name", staticmethod(lambda now=None: next(names))
    )
    monkeypatch.setattr(util, "sync_manager", lambda: None)
    monkeypatch.setattr(versions, "regressions", lambda *a, **k: [])
    return calls


def versioned(root, name="old"):
    make_venv(root / "venv")
    my.uv.migrate_to_versioned(name=name)


def test_storage_setting(root):
    assert policy.seamm_environment_storage(root) == "directory"
    assert not venv_archives.enabled()
    policy.set_seamm_environment_storage(root, "archive")
    assert venv_archives.enabled()
    # The codes' setting is separate
    assert policy.code_environment_storage(root) == "directory"
    with pytest.raises(ValueError):
        policy.set_seamm_environment_storage(root, "zip")


def test_unpack_in_parallel_streams(tmp_path):
    src = tmp_path / "src" / "venv"
    for i in range(30):
        (src / f"pkg{i % 7}").mkdir(parents=True, exist_ok=True)
        (src / f"pkg{i % 7}" / f"f{i}.py").write_text(str(i))
    (src / "empty").mkdir()
    (src / "bin").mkdir()
    (src / "bin" / "python").symlink_to("/usr/bin/python3")
    tar = tmp_path / "a.tar"
    with tarfile.open(tar, "w") as t:
        t.add(src, arcname="venv")
    target = tmp_path / "out" / "2026-11-08T12-00-00"
    target.parent.mkdir()

    n = venv_archives.unpack(tar, target, streams=4)

    assert n == 31
    assert (target / "pkg3" / "f10.py").read_text() == "10"
    assert (target / "bin" / "python").is_symlink()
    assert (target / "empty").is_dir()
    assert sorted(p.name for p in target.parent.iterdir()) == [target.name]
    with pytest.raises(archives.ArchiveError, match="already exists"):
        venv_archives.unpack(tar, target)


def test_update_builds_publishes_unpacks_and_switches(root, fake_uv):
    versioned(root)
    policy.set_seamm_environment_storage(root, "archive")

    assert versions.apply_change(["seamm==2"], upgrade=True) is True

    directory = archives.archive_dir(root)
    assert os.readlink(directory / "seamm-venv.tar") == "seamm-venv-new.tar"
    assert "seamm==1" in (directory / "seamm-venv-new.explicit.txt").read_text()
    # Built relocatable on local disk, never beside the current one on /projects
    creates = [c for c in fake_uv if c[0] == "create"]
    assert creates == [
        ("create", root.parent / "build" / creates[0][1].parts[-2] / "venv", True)
    ]
    assert my.uv.current_version == "new"
    new = root / "venvs" / "new"
    assert (new / "lib" / "site" / "installed.txt").read_text() == "seamm==2"
    assert (root / "venvs" / "old").is_dir()
    # The queues' scripts, for this root
    stage = (root / "bin" / "stage_seamm_venv.sh").read_text()
    assert f"local root={root}\n" in stage and "@ROOT@" not in stage
    assert os.access(root / "bin" / "run_from_jobserver", os.X_OK)
    # The local build is gone
    assert list((root.parent / "build").iterdir()) == []


def test_next_update_starts_from_the_current_archive(root, fake_uv, monkeypatch):
    versioned(root)
    policy.set_seamm_environment_storage(root, "archive")
    assert versions.apply_change(["seamm==2"], upgrade=True)
    seen = []
    monkeypatch.setattr(
        versions,
        "regressions",
        lambda current, new, specs=(): seen.append(current) or [],
    )

    assert versions.apply_change(["molsystem==3"], upgrade=True)

    current = seen[0]
    # The copy staged from seamm-venv-new.tar on local disk, not <root>/venv
    assert current.path.name == "current" and root not in current.path.parents
    assert my.uv.current_version == "newer"
    assert os.readlink(archives.archive_dir(root) / "seamm-venv.tar") == (
        "seamm-venv-newer.tar"
    )


def test_rollback_moves_the_archive_link(root, fake_uv):
    versioned(root)
    policy.set_seamm_environment_storage(root, "archive")
    assert versions.apply_change(["seamm==2"], upgrade=True)
    assert versions.apply_change(["seamm==3"], upgrade=True)

    assert versions.rollback()

    assert my.uv.current_version == "new"
    link = archives.archive_dir(root) / "seamm-venv.tar"
    assert os.readlink(link) == "seamm-venv-new.tar"
    # A version without an archive leaves the link (and says so)
    assert versions.rollback("old")
    assert os.readlink(link) == "seamm-venv-new.tar"


def test_refused_outside_a_job(root, fake_uv, monkeypatch, capsys):
    versioned(root)
    policy.set_seamm_environment_storage(root, "archive")
    monkeypatch.delenv("SEAMM_ARCHIVE_BUILD_DIR")
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)

    assert versions.apply_change(["seamm==2"], upgrade=True) is False

    assert versions.refused
    assert "inside a Slurm job" in capsys.readouterr().out
    assert my.uv.current_version == "old"
    assert not archives.archive_dir(root).exists()


def test_in_place_is_not_in_place(root, fake_uv, capsys):
    versioned(root)
    policy.set_seamm_environment_storage(root, "archive")
    my.options.in_place = True

    assert versions.apply_change(["seamm==2"], upgrade=True) is True

    assert "never made in place" in capsys.readouterr().out
    assert my.uv.current_version == "new"


def test_failed_unpack_reports_the_published_archive(
    root, fake_uv, monkeypatch, capsys
):
    versioned(root)
    policy.set_seamm_environment_storage(root, "archive")

    real_unpack = venv_archives.unpack

    def broken(tar, target, streams=None):
        raise archives.ArchiveError("disk full")

    monkeypatch.setattr(venv_archives, "unpack", broken)

    assert versions.apply_change(["seamm==2"], upgrade=True) is False

    out = capsys.readouterr().out
    assert "disk full" in out and "environment unpack" in out
    assert my.uv.current_version == "old"
    assert venv_archives.current_archive().name == "seamm-venv-new.tar"

    # ... and 'environment unpack' finishes the job
    monkeypatch.setattr(venv_archives, "unpack", real_unpack)
    assert venv_archives.unpack_current() is True
    assert my.uv.current_version == "new"


def test_archive_current_bootstraps(root, fake_uv):
    versioned(root)

    archive = venv_archives.archive_current()

    assert archive.name == "seamm-venv-old.tar"
    assert venv_archives.current_archive() == archive
    # Again: nothing rebuilt, the link kept
    assert venv_archives.archive_current() == archive
    assert (root / "bin" / "stage_seamm_venv.sh").exists()


def _python(path, ok=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n" if ok else "#!/bin/sh\nexit 3\n")
    path.chmod(0o755)


def test_stage_script(root, tmp_path):
    venv_archives.install_job_scripts(root)
    script = root / "bin" / "stage_seamm_venv.sh"
    job = tmp_path / "job"
    job.mkdir()

    def stage():
        return subprocess.run(
            ["bash", "-c", f'source {script}; echo "VENV=$SEAMM_VENV"'],
            capture_output=True,
            text=True,
            env={"PATH": os.environ["PATH"], "TMPDIR": str(job)},
        )

    # No archive: the shared environment
    p = stage()
    assert p.returncode == 0 and "no archive" in p.stdout and "VENV=\n" in p.stdout

    src = tmp_path / "src" / "venv"
    _python(src / "bin" / "python")
    tar = tmp_path / "v.tar"
    with tarfile.open(tar, "w") as t:
        t.add(src, arcname="venv")
    archives.publish(root, "seamm-venv", tar, "", "h", stamp="2026-11-08T12-00-00")
    p = stage()
    assert p.returncode == 0, p.stderr
    assert f"VENV={job}/seamm-venv\n" in p.stdout
    assert "seamm-venv-2026-11-08T12-00-00.tar" in p.stdout
    assert Path(job / "seamm-venv" / "bin" / "python").exists()

    # A broken archive fails the job; no fallback
    bad = tmp_path / "bad.tar"
    bad.write_text("junk")
    archives.publish(root, "seamm-venv", bad, "", "h", stamp="2026-11-08T13-00-00")
    p = stage()
    assert p.returncode == 1 and "FAILED" in p.stderr and "VENV=" not in p.stdout
