# -*- coding: utf-8 -*-
"""update also updates the web interface's own environment (venv-webui) and restarts
its service when anything there changed (found updating ~/SEAMM on 2026-10-01: the
web interface kept seamm-webui 2026.8.13.1 and a datastore that cannot read
flowchart format 3.0)."""

import types

import pytest

from seamm_manager import install, my, update, uv


class FakeUv:
    """A stand-in for the venv-webui environment."""

    versions = {}
    exists = True

    def __init__(self, root, name=None, python_version=None):
        assert name == "venv-webui"

    def list(self):
        return {k: {"version": v} for k, v in FakeUv.versions.items()}


class FakeMgr:
    def __init__(self, installed=True):
        self.installed = installed
        self.restarted = []

    def is_installed(self, name):
        return self.installed

    def restart(self, name):
        self.restarted.append(name)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(my, "root", tmp_path, raising=False)
    monkeypatch.setattr(
        my, "uv", types.SimpleNamespace(python_version="3.12"), raising=False
    )
    monkeypatch.setattr(uv, "Uv", FakeUv)
    mgr = FakeMgr()
    monkeypatch.setattr(update, "mgr", mgr)
    monkeypatch.setattr(update, "installation_service_name", lambda kind: f"{kind}-X")
    FakeUv.exists = True
    return mgr


def upgrade_to(monkeypatch, new_versions):
    calls = []

    def fake_install(update=False):
        calls.append(update)
        FakeUv.versions = dict(new_versions)

    monkeypatch.setattr(install, "install_seamm_webui", fake_install)
    return calls


def test_updated_and_restarted(setup, monkeypatch, capsys):
    FakeUv.versions = {"seamm-webui": "2026.8.13.1", "seamm-datastore": "2026.9.25"}
    calls = upgrade_to(
        monkeypatch, {"seamm-webui": "2026.10.1.1", "seamm-datastore": "2026.10.1"}
    )
    update.update_webui()
    assert calls == [True]
    assert setup.restarted == ["webui-X"]
    out = capsys.readouterr().out
    assert "seamm-webui: 2026.8.13.1 -> 2026.10.1.1" in out
    assert "seamm-datastore: 2026.9.25 -> 2026.10.1" in out


def test_up_to_date_is_not_restarted(setup, monkeypatch, capsys):
    FakeUv.versions = {"seamm-webui": "2026.10.1.1"}
    upgrade_to(monkeypatch, {"seamm-webui": "2026.10.1.1"})
    update.update_webui()
    assert setup.restarted == []
    assert "up to date" in capsys.readouterr().out


def test_no_webui_environment(setup, monkeypatch):
    FakeUv.exists = False
    calls = upgrade_to(monkeypatch, {})
    update.update_webui()
    assert calls == [] and setup.restarted == []


def test_no_service_not_restarted(setup, monkeypatch):
    setup.installed = False
    FakeUv.versions = {"seamm-webui": "1"}
    upgrade_to(monkeypatch, {"seamm-webui": "2"})
    update.update_webui()
    assert setup.restarted == []
