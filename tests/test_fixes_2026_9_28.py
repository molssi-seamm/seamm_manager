# -*- coding: utf-8 -*-
"""The fixes in 2026.9.28: service listing, datastore, package list, code updates."""

import logging
import sqlite3
import sys

import pytest

from seamm_manager import datastore, my, util
from seamm_manager.installer_base import InstallerBase

# ---- the service listing ignores editor backups ---------------------------


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS services")
def test_mac_listing_ignores_non_plist(tmp_path, monkeypatch):
    from seamm_manager import mac

    monkeypatch.setenv("HOME", str(tmp_path))
    agents = tmp_path / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    for name in ("org.molssi.seamm.webui.plist", "org.molssi.seamm.webui.plist~"):
        (agents / name).write_bytes(b"")
    assert list(mac.ServiceManager(prefix="org.molssi.seamm").data) == ["webui"]


def test_datastore_uses_the_services_prefix():
    assert datastore.mgr.prefix == "org.molssi.seamm"
    assert hasattr(datastore.mgr, "stop") and hasattr(datastore.mgr, "start")


# ---- the datastore: seeding and unversioned databases --------------------------


def _db(path, statements):
    with sqlite3.connect(path) as db:
        for s in statements:
            db.execute(s)
    return path


def test_seed_state(tmp_path):
    empty = _db(tmp_path / "a.db", ["create table alembic_version (version_num text)"])
    assert datastore._seed_state(empty) == "no tables"
    no_users = _db(tmp_path / "b.db", ["create table users (id integer)"])
    assert datastore._seed_state(no_users) == "no users"
    seeded = _db(
        tmp_path / "c.db",
        ["create table users (id integer)", "insert into users values (1)"],
    )
    assert datastore._seed_state(seeded) == "seeded"


FLOWCHARTS = "create table flowcharts (id integer, sha256_strict text{extra})"


def test_unversioned_revision(tmp_path):
    base = _db(
        tmp_path / "base.db", [FLOWCHARTS.format(extra=", flowchart_metadata json")]
    )
    assert datastore.unversioned_revision(base) == "7b24598d1fee"
    head = _db(
        tmp_path / "head.db",
        [
            FLOWCHARTS.format(
                extra=", flowchart_metadata json, "
                "constraint uq_flowcharts_sha256_strict unique (sha256_strict)"
            )
        ],
    )
    assert datastore.unversioned_revision(head) == "d7d6859198e9"
    unnamed = _db(  # as seamm_datastore creates it: an unnamed UNIQUE
        tmp_path / "unnamed.db",
        [FLOWCHARTS.format(extra=", flowchart_metadata json, UNIQUE (sha256_strict)")],
    )
    assert datastore.unversioned_revision(unnamed) == "d7d6859198e9"
    old = _db(tmp_path / "old.db", [FLOWCHARTS.format(extra=", path text")])

    assert datastore.unversioned_revision(old) is None  # alembic migrates it
    versioned = _db(
        tmp_path / "v.db",
        [
            FLOWCHARTS.format(extra=", flowchart_metadata json"),
            "create table alembic_version (version_num text)",
        ],
    )
    assert datastore.unversioned_revision(versioned) is None


# ---- the package list falls back to the last copy -----------------------------


class _Unreachable:
    def get_latest_public_record(self, concept_id):
        raise ConnectionError("Failed to resolve 'zenodo.org'")


def test_package_list_falls_back_to_cached_copy(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(my, "root", tmp_path)
    monkeypatch.setattr(my, "logger", logging.getLogger("test"), raising=False)
    monkeypatch.setattr(util, "Zenodo", _Unreachable)
    with pytest.raises(util.PackageListUnavailable):
        util.find_packages(progress=False)

    (tmp_path / "environments").mkdir()
    (tmp_path / "environments" / "SEAMM_packages.json").write_text(
        '{"format": 2, "packages": {"seamm": {"version": "1"}}}'
    )
    (tmp_path / "environments" / "seamm.lock.txt").write_text("seamm==1\n")
    assert util.find_packages(progress=False) == {"seamm": {"version": "1"}}
    assert "using the copy from" in capsys.readouterr().out
    assert my.lock == tmp_path / "environments" / "seamm.lock.txt"


# ---- unchanged environment files are not applied again -----------------------


class _Conda:
    def __init__(self, prefix):
        self.prefix = prefix
        self.calls = []

    def exists(self, name):
        return True

    def path(self, name):
        return self.prefix

    def update_environment(self, path, name=None, **kw):
        self.calls.append(name)


def test_update_skips_unchanged_environment_file(tmp_path, monkeypatch):
    import os
    import time

    monkeypatch.setattr(sys, "argv", ["mopac-step-installer", "show"])
    monkeypatch.setattr(my, "logger", logging.getLogger("test"), raising=False)
    monkeypatch.setenv("SEAMM_ROOT", str(tmp_path / "SEAMM"))
    monkeypatch.delenv("SEAMM_REFRESH_CODES", raising=False)
    from seamm_manager import policy

    monkeypatch.setattr(policy, "DEFAULT_ROOT", tmp_path / "SEAMM")  # an own root
    (tmp_path / "SEAMM").mkdir()
    (tmp_path / "seamm.ini").write_text("")
    inst = InstallerBase(ini_file=str(tmp_path / "seamm.ini"))
    inst.section = "mopac-step"
    inst.environment = "seamm-mopac"
    env_file = tmp_path / "seamm-mopac.yml"
    env_file.write_text("dependencies: [mopac]\n")
    inst.environment_file = env_file
    inst._conda = _Conda(tmp_path / "envs" / "seamm-mopac")
    (tmp_path / "SEAMM" / "mopac.ini").write_text(
        "[local]\ninstallation = conda\nconda-environment = seamm-mopac\n"
    )
    inst.exe_config.path = tmp_path / "SEAMM" / "mopac.ini"
    monkeypatch.setattr(inst.exe_config, "save", lambda: None)

    inst.update()  # nothing recorded yet: applied
    inst.update()  # unchanged and recent: skipped
    assert inst.conda.calls == ["seamm-mopac"]

    monkeypatch.setenv("SEAMM_REFRESH_CODES", "1")  # update --refresh-codes
    inst.update()
    monkeypatch.delenv("SEAMM_REFRESH_CODES")
    env_file.write_text("dependencies: [mopac, numpy]\n")  # the plug-in changed it
    inst.update()
    assert inst.conda.calls == ["seamm-mopac"] * 3

    marker = inst._applied_marker("seamm-mopac")  # a week later: applied again
    old = time.time() - 8 * 86400
    os.utime(marker, (old, old))
    inst.update()
    assert len(inst.conda.calls) == 4


def test_update_creates_rather_than_migrates_an_empty_file(tmp_path, monkeypatch):
    (tmp_path / "Jobs").mkdir()
    (tmp_path / "Jobs" / "seamm.db").write_bytes(b"")
    monkeypatch.setattr(my, "root", tmp_path)
    calls = []
    monkeypatch.setattr(datastore, "ensure", lambda: calls.append("ensure") or True)
    monkeypatch.setattr(datastore, "update_db", lambda: calls.append("migrate"))
    datastore.update()
    assert calls == ["ensure"]
