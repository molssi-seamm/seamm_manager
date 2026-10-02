# -*- coding: utf-8 -*-
"""Versioned environments: build beside, switch, migrate, prune, rollback.

No uv is needed: a 'venv' here is a directory with pyvenv.cfg and bin/python.
"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from seamm_manager import my
from seamm_manager import versions
from seamm_manager.__main__ import own_installation_root
from seamm_manager.uv import Uv, UvError


def make_venv(path, shebang_prefix=None):
    """A fake environment at `path`; scripts' shebangs name `shebang_prefix`."""
    prefix = str(path) if shebang_prefix is None else str(shebang_prefix)
    (path / "bin").mkdir(parents=True)
    (path / "pyvenv.cfg").write_text("home = /uv/python\n")
    (path / "bin" / "python").write_bytes(b"\x7fELF binary " + prefix.encode())
    script = path / "bin" / "seamm-jobserver"
    script.write_text(f"#!{prefix}/bin/python\nimport sys\n")
    script.chmod(0o755)
    (path / "bin" / "activate").write_text(f'VIRTUAL_ENV="{prefix}"\n')
    return path


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = tmp_path / "SEAMM"
    root.mkdir()
    (root / "Jobs").mkdir()
    uv = Uv(root)
    monkeypatch.setattr(my, "uv", uv)
    monkeypatch.setattr(my, "root", root)
    monkeypatch.setattr(my, "options", SimpleNamespace())
    # Nothing here touches real services or apps
    monkeypatch.setattr(versions, "relink_launchers", lambda: None)
    monkeypatch.setattr(versions, "processes_using", lambda prefix: [])
    return root


# ---- Uv -------------------------------------------------------------------------


def test_plain_environment_paths(root):
    make_venv(root / "venv")
    uv = my.uv
    assert not uv.is_versioned
    assert uv.real_path == root / "venv"
    assert uv.python == root / "venv" / "bin" / "python"
    assert uv.exists
    assert uv.current_version is None
    assert uv.versions() == []


def test_migrate_renames_links_and_rewrites_paths(root):
    make_venv(root / "venv")
    uv = my.uv
    inode = (root / "venv" / "bin" / "seamm-jobserver").stat().st_ino

    name = uv.migrate_to_versioned(name="2026-10-02T10-00-00")

    assert name == "2026-10-02T10-00-00"
    target = root / "venvs" / name
    assert (root / "venv").is_symlink()
    assert os.readlink(root / "venv") == "venvs/2026-10-02T10-00-00"  # relative
    assert uv.is_versioned
    assert uv.real_path == target
    assert uv.current_version == name
    # The real path is what launchers get
    assert uv.python == target / "bin" / "python"
    assert uv.which("seamm-jobserver") == target / "bin" / "seamm-jobserver"
    # Same files (rename), with the old path rewritten in the text files only
    script = target / "bin" / "seamm-jobserver"
    assert script.stat().st_ino == inode
    assert script.read_text().startswith(f"#!{target}/bin/python\n")
    assert script.stat().st_mode & 0o777 == 0o755
    assert f'VIRTUAL_ENV="{target}"' in (target / "bin" / "activate").read_text()
    assert str(root / "venv").encode() in (target / "bin" / "python").read_bytes()
    # Idempotent
    assert uv.migrate_to_versioned() is None


def test_migrate_without_environment_does_nothing(root):
    assert my.uv.migrate_to_versioned() is None
    assert not (root / "venv").exists()


def test_switch_is_atomic_and_refuses_bad_targets(root):
    make_venv(root / "venv")
    uv = my.uv
    uv.migrate_to_versioned(name="2026-10-02T10-00-00")
    new = make_venv(root / "venvs" / "2026-10-02T11-00-00")

    uv.switch_to(new)
    assert uv.real_path == new
    assert os.readlink(root / "venv") == "venvs/2026-10-02T11-00-00"
    assert [n for n, _ in uv.versions()] == [
        "2026-10-02T10-00-00",
        "2026-10-02T11-00-00",
    ]
    assert not list(root.glob(".venv-switch-*"))

    with pytest.raises(UvError):
        uv.switch_to(root / "venvs" / "nothing-here")


def test_switch_refuses_a_real_directory(root):
    make_venv(root / "venv")
    other = make_venv(root / "venvs" / "x")
    with pytest.raises(UvError, match="migrate"):
        my.uv.switch_to(other)


def test_remove_versioned_removes_link_and_directory(root):
    make_venv(root / "venv")
    my.uv.migrate_to_versioned(name="a")
    my.uv.remove()
    assert not (root / "venv").exists() and not (root / "venv").is_symlink()
    assert not (root / "venvs" / "a").exists()


def test_version_names_sort_by_time():
    from datetime import datetime

    a = Uv.new_version_name(datetime(2026, 10, 2, 9, 5, 7))
    b = Uv.new_version_name(datetime(2026, 10, 2, 10, 0, 0))
    assert a == "2026-10-02T09-05-07" and a < b


# ---- root detection ------------------------------------------------------------


def test_own_installation_root_for_versioned_environment(tmp_path):
    root = tmp_path / "SEAMM_DEV"
    (root / "Jobs").mkdir(parents=True)
    assert own_installation_root(root / "venvs" / "2026-10-02T10-00-00") == root
    assert own_installation_root(root / "venv") == root
    assert own_installation_root(tmp_path / "tools" / "seamm-manager") is None


# ---- processes -----------------------------------------------------------------


def test_processes_using_matches_cmdline_and_exe(root, monkeypatch):
    monkeypatch.undo()  # the fixture stubbed processes_using; use the real one
    import psutil

    class P:
        def __init__(self, pid, name, cmdline, exe):
            self.info = {"pid": pid, "name": name, "cmdline": cmdline, "exe": exe}

    venv = "/r/venvs/a"
    procs = [
        P(1, "python", [f"{venv}/bin/python", f"{venv}/bin/run_from_jobserver"], None),
        P(
            2,
            "SEAMM-JobServer",
            ["/r/services/X.app/Contents/MacOS/X", f"{venv}/bin/seamm-jobserver"],
            "/uv/python",
        ),
        P(3, "orca", ["/opt/orca"], f"{venv}/bin/orca"),
        P(4, "other", ["/r/venvs/ab/bin/python"], None),  # a different version
        P(5, "none", None, None),
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: procs)
    found = versions.processes_using(venv)
    assert [pid for pid, _ in found] == [1, 2, 3]
    assert "run_from_jobserver" in found[0][1]


def test_unsafe_processes_only_when_linked(root, monkeypatch):
    make_venv(root / "venv")
    seen = []
    monkeypatch.setattr(
        versions, "processes_using", lambda p: seen.append(str(p)) or []
    )
    assert versions.unsafe_processes() == []
    assert seen == []  # a plain directory: nothing goes "through the link"
    my.uv.migrate_to_versioned(name="a")
    versions.unsafe_processes()
    assert seen == [str(root / "venv")]


# ---- switch, apply_change, prune, rollback --------------------------------------


def test_switch_refuses_with_unsafe_processes_unless_forced(root, monkeypatch, capsys):
    make_venv(root / "venv")
    my.uv.migrate_to_versioned(name="a")
    new = Uv(root, name="venvs/b")
    make_venv(new.path)
    monkeypatch.setattr(versions, "unsafe_processes", lambda: [(42, "python: x")])

    assert versions.switch(new) is False
    assert my.uv.current_version == "a"
    assert "42" in capsys.readouterr().out
    assert versions.switch(new, force=True) is True
    assert my.uv.current_version == "b"
    assert versions.switched


def test_apply_change_in_place_for_fresh_or_requested(root, monkeypatch):
    calls = []
    monkeypatch.setattr(
        Uv, "install", lambda self, *a, **k: calls.append((self.path, a, k))
    )
    # No environment yet: in place
    assert versions.apply_change(["seamm"]) is True
    assert calls[-1][0] == root / "venv"
    # Existing environment, --in-place
    make_venv(root / "venv")
    my.options.in_place = True
    assert versions.apply_change(["seamm"], upgrade=True) is True
    assert calls[-1][0] == root / "venv" and calls[-1][2]["upgrade"] is True
    assert not my.uv.is_versioned


def test_apply_change_builds_beside_and_switches(root, monkeypatch):
    make_venv(root / "venv")
    installs = []

    def fake_create(self, python_version=None, seed=True):
        make_venv(self.path)

    def fake_install(self, packages, constraints=None, upgrade=False, **kw):
        installs.append((self.path.name, list(packages), upgrade))

    def fake_run(self, *args, **kw):
        installs.append((self.path.name, list(map(str, args)), None))

    monkeypatch.setattr(Uv, "create", fake_create)
    monkeypatch.setattr(Uv, "install", fake_install)
    monkeypatch.setattr(Uv, "run", fake_run)
    monkeypatch.setattr(Uv, "freeze", lambda self: "seamm==1\nmolsystem==1\n")
    monkeypatch.setattr(Uv, "new_version_name", staticmethod(lambda now=None: "new"))
    monkeypatch.setattr(
        my.uv,
        "migrate_to_versioned",
        lambda name=None: Uv.migrate_to_versioned(my.uv, "old"),
    )

    assert versions.apply_change(["seamm==2"], upgrade=True) is True
    assert my.uv.is_versioned and my.uv.current_version == "new"
    assert (root / "venvs" / "old").is_dir()
    # Copied from the freeze, then the change applied, in the new environment
    assert installs[0][0] == "new" and "-r" in installs[0][1]
    assert installs[1] == ("new", ["seamm==2"], True)


def test_recreate_style_build_from_scratch(root, monkeypatch):
    make_venv(root / "venv")
    my.uv.migrate_to_versioned(name="old")
    installs = []
    monkeypatch.setattr(
        Uv, "create", lambda self, python_version=None, seed=True: make_venv(self.path)
    )
    monkeypatch.setattr(Uv, "install", lambda self, p, **k: installs.append(list(p)))
    monkeypatch.setattr(Uv, "run", lambda self, *a, **k: installs.append("freeze!"))
    new = versions.build_version(["seamm", "mopac-step"], from_freeze=False, name="new")
    assert new.path == root / "venvs" / "new"
    assert installs == [["seamm", "mopac-step"]]


def test_prune_policy(root, monkeypatch, capsys):
    make_venv(root / "venv")
    my.uv.migrate_to_versioned(name="2026-09-01T00-00-00")
    for name in ("2026-09-02T00-00-00", "2026-09-03T00-00-00", "2026-09-04T00-00-00"):
        make_venv(root / "venvs" / name)
    my.uv.switch_to(root / "venvs" / "2026-09-04T00-00-00")
    busy = root / "venvs" / "2026-09-02T00-00-00"
    monkeypatch.setattr(
        versions,
        "processes_using",
        lambda p: [(7, "python: job")] if Path(p) == busy else [],
    )

    removed = versions.prune(keep=2, min_age_days=1.0, dry_run=True)
    assert [p.name for p in removed] == ["2026-09-01T00-00-00"]
    assert (root / "venvs" / "2026-09-01T00-00-00").exists()  # dry run
    out = capsys.readouterr().out
    assert "in use" in out and "2026-09-02" in out

    removed = versions.prune(keep=2, min_age_days=1.0)
    assert [p.name for p in removed] == ["2026-09-01T00-00-00"]
    assert not (root / "venvs" / "2026-09-01T00-00-00").exists()
    assert busy.exists()
    # The current and the newest `keep` survive whatever their age
    assert versions.prune(keep=2, min_age_days=0) == []


def test_prune_respects_min_age(root):
    make_venv(root / "venv")
    my.uv.migrate_to_versioned()  # named for now
    for name in ("2026-09-02T00-00-00", "2026-09-03T00-00-00"):
        make_venv(root / "venvs" / name)
    my.uv.switch_to(root / "venvs" / "2026-09-03T00-00-00")
    # keep=1 would remove both others; the one made just now is too young
    removed = versions.prune(keep=1, min_age_days=1.0)
    assert [p.name for p in removed] == ["2026-09-02T00-00-00"]


def test_rollback(root, capsys):
    make_venv(root / "venv")
    my.uv.migrate_to_versioned(name="2026-09-01T00-00-00")
    make_venv(root / "venvs" / "2026-09-02T00-00-00")
    make_venv(root / "venvs" / "2026-09-03T00-00-00")
    my.uv.switch_to(root / "venvs" / "2026-09-03T00-00-00")

    assert versions.rollback() is True
    assert my.uv.current_version == "2026-09-02T00-00-00"
    assert versions.rollback("2026-09-01T00-00-00") is True
    assert my.uv.current_version == "2026-09-01T00-00-00"
    assert versions.rollback() is False  # nothing older
    assert versions.rollback("missing") is False
    assert "no version" in capsys.readouterr().out
