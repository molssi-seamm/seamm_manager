# -*- coding: utf-8 -*-
"""The plug-ins' installers work on the manager's root, not always ~/SEAMM."""

import logging
from pathlib import Path
import subprocess
import sys

import pytest

from seamm_manager import my
from seamm_manager import util
from seamm_manager.installer_base import InstallerBase


@pytest.fixture(autouse=True)
def _harness(monkeypatch):
    """InstallerBase parses sys.argv when made; the manager logs via my.logger."""
    monkeypatch.setattr(sys, "argv", ["test-step-installer", "show"])
    monkeypatch.setattr(my, "logger", logging.getLogger("test"), raising=False)


def test_run_plugin_installer_passes_root(tmp_path, monkeypatch):
    seen = {}

    class _Uv:
        def which(self, name):
            return tmp_path / name

    def fake_run(cmd, capture_output, text, env=None):
        if env is not None:  # the installer itself (not the policy check)
            seen["env"] = env
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(my, "uv", _Uv())
    monkeypatch.setattr(my, "root", tmp_path / "SEAMM_NEW")
    monkeypatch.setattr(util.subprocess, "run", fake_run)
    util.run_plugin_installer("mopac-step", "install", verbose=False)
    assert seen["env"]["SEAMM_ROOT"] == str(tmp_path / "SEAMM_NEW")


def _installer(tmp_path, ini_text=""):
    ini = tmp_path / "seamm.ini"
    ini.write_text(ini_text)
    return InstallerBase(ini_file=str(ini))


def test_root_from_environment_beats_ini(tmp_path, monkeypatch):
    monkeypatch.setenv("SEAMM_ROOT", str(tmp_path / "A"))
    inst = _installer(tmp_path, "[SEAMM]\nroot = /from/ini\n")
    assert inst.root == tmp_path / "A"


def test_root_from_ini_then_installation_then_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SEAMM_ROOT", raising=False)
    assert _installer(tmp_path, "[SEAMM]\nroot = /from/ini\n").root == Path("/from/ini")

    root = tmp_path / "SEAMM_NEW"
    (root / "venv").mkdir(parents=True)
    (root / "Jobs").mkdir()
    monkeypatch.setattr(sys, "prefix", str(root / "venv"))
    import seamm_util

    if hasattr(seamm_util, "installation_root"):  # seamm-util 2026.9.27 or later
        assert _installer(tmp_path).root == root
    else:  # older seamm-util: no inference, the default as before
        assert _installer(tmp_path).root == Path("~/SEAMM").expanduser()

    monkeypatch.setattr(sys, "prefix", str(tmp_path / "elsewhere"))
    assert _installer(tmp_path).root == Path("~/SEAMM").expanduser()
