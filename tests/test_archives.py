# -*- coding: utf-8 -*-
"""code-environment-storage = archive: build on local disk, pack, publish, stage."""

import logging
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

import pytest

from seamm_manager import archives, my, policy
from seamm_manager.installer_base import InstallerBase

YML = "name: seamm-mopac\nchannels:\n  - conda-forge\ndependencies:\n  - mopac\n"


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = tmp_path / "SEAMM"
    root.mkdir()
    monkeypatch.setattr(policy, "DEFAULT_ROOT", root)  # 'own' codes
    monkeypatch.setattr(sys, "argv", ["mopac-step-installer", "show"])
    monkeypatch.setattr(my, "logger", logging.getLogger("test"), raising=False)
    build = tmp_path / "build"
    monkeypatch.setenv("SEAMM_ARCHIVE_BUILD_DIR", str(build))
    return root


@pytest.fixture
def fake_conda(tmp_path, monkeypatch):
    """A conda whose `env create` makes a small prefix, and conda-pack -> plain tar."""
    calls = []

    def fake_run(args, env=None, what=""):
        calls.append(list(args))
        if args[1:3] == ["env", "create"]:
            prefix = Path(args[args.index("--prefix") + 1])
            (prefix / "conda-meta").mkdir(parents=True)
            (prefix / "bin").mkdir()
            (prefix / "bin" / "mopac").write_text("#!/bin/sh\n")
            assert env["CONDA_PKGS_DIRS"].startswith(str(tmp_path / "build"))
            return ""
        if args[1] == "list":
            return "@EXPLICIT\nhttps://conda.anaconda.org/conda-forge/mopac.conda\n"
        raise AssertionError(args)

    def fake_pack(prefix, output, n_threads=None):
        with tarfile.open(output, "w") as tar:
            tar.add(prefix, arcname=".")

    monkeypatch.setattr(archives, "_run", fake_run)
    monkeypatch.setattr(archives, "pack", fake_pack)
    conda = tmp_path / "miniforge" / "bin" / "conda"
    conda.parent.mkdir(parents=True)
    conda.write_text("#!/bin/sh\n")
    import seamm_manager

    monkeypatch.setattr(seamm_manager, "find_conda", lambda: str(conda))
    return calls, conda


def _installer(tmp_path, monkeypatch, root, yml=YML):
    monkeypatch.setenv("SEAMM_ROOT", str(root))
    ini = tmp_path / "seamm.ini"
    ini.write_text("")
    inst = InstallerBase(ini_file=str(ini))
    inst.section = "mopac-step"
    inst.environment = "seamm-mopac"
    inst.init_file_name = "mopac.ini"
    inst.environment_file = tmp_path / "seamm-mopac.yml"
    inst.environment_file.write_text(yml)
    (root / "mopac.ini").write_text("[local]\ncode = mopac\n")
    inst.exe_config.path = root / "mopac.ini"
    monkeypatch.setattr(inst, "check_exe_configuration_file", lambda: None)

    class _NoConda:
        def __getattr__(self, name):
            raise AssertionError(f"archive storage must not call conda.{name}")

    inst._conda = _NoConda()
    return inst


def test_storage_setting(root):
    assert policy.code_environment_storage(root) == "directory"
    policy.set_code_environment_storage(root, "archive")
    assert policy.code_environment_storage(root) == "archive"
    with pytest.raises(ValueError):
        policy.set_code_environment_storage(root, "zip")


def test_build_directory_needs_a_job(monkeypatch, tmp_path):
    monkeypatch.delenv("SEAMM_ARCHIVE_BUILD_DIR", raising=False)
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    with pytest.raises(archives.ArchiveError, match="Slurm job"):
        archives.build_directory()
    monkeypatch.setenv("SLURM_JOB_ID", "123")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert archives.build_directory() == tmp_path


def test_install_builds_publishes_and_registers(
    root, tmp_path, monkeypatch, fake_conda
):
    calls, conda = fake_conda
    policy.set_code_environment_storage(root, "archive")
    inst = _installer(tmp_path, monkeypatch, root)
    assert inst.archive_storage
    inst.install()

    link = root / "env-archives" / "seamm-mopac.tar"
    assert link.is_symlink()
    archive = archives.current_archive(root, "seamm-mopac")
    assert archive.name.startswith("seamm-mopac-") and archive.parent == link.parent
    with tarfile.open(archive) as tar:
        assert "./bin/mopac" in tar.getnames()
    stem = archive.name[: -len(".tar")]
    assert (archive.parent / f"{stem}.explicit.txt").read_text().startswith("@EXPLICIT")
    assert archives.archive_hash(root, "seamm-mopac") == archives.file_hash(
        inst.environment_file
    )
    # The build directory is cleaned up
    assert list((tmp_path / "build").iterdir()) == []
    # The .ini still names the environment; jobs map it through the wrapper
    text = (root / "mopac.ini").read_text()
    assert "installation = conda" in text and "conda-environment = seamm-mopac" in text
    wrapper = root / "bin" / "seamm-conda"
    body = wrapper.read_text()
    assert f"REAL=${{SEAMM_REAL_CONDA:-{conda}}}" in body
    assert f"ARCHIVES=${{SEAMM_ENV_ARCHIVES:-{root / 'env-archives'}}}" in body
    assert os.access(wrapper, os.X_OK)
    assert inst.check() is True


def test_update_rebuilds_only_when_the_file_changes(
    root, tmp_path, monkeypatch, fake_conda, capsys
):
    calls, _ = fake_conda
    policy.set_code_environment_storage(root, "archive")
    inst = _installer(tmp_path, monkeypatch, root)
    inst.install()
    first = archives.current_archive(root, "seamm-mopac")
    (root / "mopac.ini").write_text(
        "[local]\ninstallation = conda\nconda-environment = seamm-mopac\n"
    )
    n = len(calls)
    inst.update()
    assert len(calls) == n
    assert "is up to date" in capsys.readouterr().out

    time.sleep(1.1)  # a new stamp
    inst.environment_file.write_text(YML + "  - toml\n")
    inst.update()
    second = archives.current_archive(root, "seamm-mopac")
    assert second != first and first.exists()  # the old one is kept for a while
    assert archives.archive_hash(root, "seamm-mopac") == archives.file_hash(
        inst.environment_file
    )


def test_refresh_codes_forces_a_rebuild(root, tmp_path, monkeypatch, fake_conda):
    calls, _ = fake_conda
    policy.set_code_environment_storage(root, "archive")
    inst = _installer(tmp_path, monkeypatch, root)
    inst.install()
    (root / "mopac.ini").write_text(
        "[local]\ninstallation = conda\nconda-environment = seamm-mopac\n"
    )
    n = len(calls)
    monkeypatch.setenv("SEAMM_REFRESH_CODES", "1")
    time.sleep(1.1)
    inst.update()
    assert len(calls) > n


def test_directory_storage_is_unchanged(root, tmp_path, monkeypatch, fake_conda):
    """The default: conda environments as before (ChemAI, the Macs)."""
    inst = _installer(tmp_path, monkeypatch, root)
    assert not inst.archive_storage

    class _Conda:
        calls = []

        def exists(self, name):
            return False

        def create_environment(self, path, name=None):
            self.calls.append(("create", name))

    inst._conda = _Conda()
    monkeypatch.setattr(inst.exe_config, "save", lambda: None)
    inst.install()
    assert inst._conda.calls == [("create", "seamm-mopac")]
    assert not (root / "env-archives").exists()
    assert not (root / "bin" / "seamm-conda").exists()


def test_shared_installation_never_builds_archives(tmp_path, monkeypatch, fake_conda):
    calls, _ = fake_conda
    default = tmp_path / "SEAMM"
    new = tmp_path / "SEAMM_NEW"
    default.mkdir()
    new.mkdir()
    monkeypatch.setattr(policy, "DEFAULT_ROOT", default)
    monkeypatch.setattr(sys, "argv", ["mopac-step-installer", "show"])
    policy.set_code_environment_storage(new, "archive")  # policy stays 'shared'
    inst = _installer(tmp_path, monkeypatch, new)
    assert not inst.archive_storage
    assert calls == []


def test_publish_never_rewrites_and_switches_the_link(root, tmp_path):
    src = tmp_path / "a.tar"
    src.write_bytes(b"x")
    a = archives.publish(root, "seamm-psi4", src, "", "h1", stamp="2026-11-07T22-00-00")
    with pytest.raises(archives.ArchiveError):
        archives.publish(root, "seamm-psi4", src, "", "h1", stamp="2026-11-07T22-00-00")
    b = archives.publish(root, "seamm-psi4", src, "", "h2", stamp="2026-11-07T23-00-00")
    assert archives.current_archive(root, "seamm-psi4") == b.resolve()
    assert a.exists()
    assert archives.archive_hash(root, "seamm-psi4") == "h2"


def test_prune_keeps_current_recent_and_other_environments(root, tmp_path):
    src = tmp_path / "a.tar"
    src.write_bytes(b"x")
    stamps = [f"2026-11-0{d}T00-00-00" for d in range(1, 6)]
    for s in stamps:
        archives.publish(root, "seamm-lammps", src, "", "h", stamp=s)
    other = archives.publish(
        root, "seamm-lammps-xnn0240", src, "", "h", stamp="2026-11-01T00-00-00"
    )
    old = time.time() - 10 * 86400
    for p in (root / "env-archives").iterdir():
        if not p.is_symlink():
            os.utime(p, (old, old))
    removed = archives.prune(root, "seamm-lammps", keep=3)
    names = sorted({p.name.split(".")[0] for p in removed})
    assert names == [
        "seamm-lammps-2026-11-01T00-00-00",
        "seamm-lammps-2026-11-02T00-00-00",
    ]
    assert other.exists()
    assert archives.current_archive(root, "seamm-lammps").name.startswith(
        "seamm-lammps-2026-11-05"
    )


def test_real_conda_behind_the_wrapper(root, tmp_path, monkeypatch):
    conda = tmp_path / "conda"
    conda.write_text("")
    archives.install_wrapper(root, conda)
    wrapper = root / "bin" / "seamm-conda"
    monkeypatch.delenv("SEAMM_REAL_CONDA", raising=False)
    assert archives.real_conda(str(wrapper)) == str(conda)
    # Installing it again through the wrapper does not wrap the wrapper
    assert archives.install_wrapper(root, wrapper) is False
    assert archives.real_conda(str(conda)) == str(conda)


@pytest.mark.skipif(sys.platform == "darwin", reason="the wrapper uses GNU stat")
def test_wrapper_stages_fails_and_passes_through(root, tmp_path):
    """The installed wrapper: stage an archive, fail loudly, pass others through."""
    env = tmp_path / "envsrc"
    (env / "bin").mkdir(parents=True)
    (env / "bin" / "python").write_text('#!/bin/sh\nexec python3 "$@"\n')
    (env / "bin" / "python").chmod(0o755)
    (env / "bin" / "conda-unpack").write_text("pass\n")
    tar = tmp_path / "good.tar"
    with tarfile.open(tar, "w") as t:
        t.add(env, arcname=".")
    archives.publish(root, "good", tar, "", "h")
    bad = tmp_path / "bad.tar"
    bad.write_text("junk")
    archives.publish(root, "bad", bad, "", "h")
    archives.install_wrapper(root, "/bin/echo")
    wrapper = str(root / "bin" / "seamm-conda")
    run_env = {**os.environ, "TMPDIR": str(tmp_path / "job")}
    (tmp_path / "job").mkdir()

    def run(*args):
        return subprocess.run(
            [wrapper, *args], capture_output=True, text=True, env=run_env
        )

    p = run("run", "-n", "good", "psi4", "-n", "4")
    assert (
        p.returncode == 0 and "-p " + str(tmp_path / "job" / "seamm-envs") in p.stdout
    )
    assert p.stdout.rstrip().endswith("psi4 -n 4")
    p = run("run", "-n", "bad", "x")
    assert p.returncode == 1 and "seamm-conda: FAILED" in p.stderr
    p = run("run", "-n", "other", "x")
    assert p.returncode == 0 and p.stdout.strip() == "run -n other x"
    p = run("info", "--envs")
    assert p.stdout.strip() == "info --envs"


def test_update_leaves_a_hand_built_environment_alone(
    root, tmp_path, monkeypatch, fake_conda, capsys
):
    """An .ini naming an environment SEAMM did not make (seamm-lammps-xnn0240 on
    ARC) must not get an archive built from the plug-in's file."""
    calls, _ = fake_conda
    policy.set_code_environment_storage(root, "archive")
    inst = _installer(tmp_path, monkeypatch, root)
    (root / "mopac.ini").write_text(
        "[local]\ninstallation = conda\nconda-environment = my-own-mopac\n"
    )
    inst.exe_config.path = None  # read it again
    inst.exe_config.path = root / "mopac.ini"
    monkeypatch.setattr(inst, "_not_ours", lambda environment: True)
    inst.update()
    assert calls == []
    assert archives.current_archive(root, "my-own-mopac") is None
    assert "was not created by SEAMM" in capsys.readouterr().out
