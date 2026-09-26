# -*- coding: utf-8 -*-
"""Tests for the Uv wrapper: command construction (mocked) and, when uv is
present, a real environment in a temporary directory."""

import json
from pathlib import Path
import subprocess

import pytest

from seamm_manager.uv import Uv, UvError, find_uv, normalize


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def uv(tmp_path, monkeypatch):
    """A Uv whose subprocess calls are recorded, not run."""
    calls = []

    def fake_run(command, capture_output, text, env):
        calls.append(command)
        if command[1:3] == ["pip", "list"]:
            return _Result(stdout=json.dumps([{"name": "Seamm_Util", "version": "1"}]))
        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    u = Uv(tmp_path, python_version="3.12")
    u._uv = "/fake/uv"
    u.calls = calls
    return u


def test_paths(tmp_path):
    u = Uv(tmp_path)
    assert u.path == tmp_path / "venv"
    assert u.python == tmp_path / "venv" / "bin" / "python"
    assert u.bin("jobserver") == tmp_path / "venv" / "bin" / "jobserver"
    assert not u.exists
    assert u.which("jobserver") is None


def test_normalize():
    assert normalize("Seamm_Util") == "seamm-util"


def test_create_commands(uv):
    uv.create()
    assert uv.calls[0] == ["/fake/uv", "python", "install", "3.12"]
    assert uv.calls[1] == [
        "/fake/uv",
        "venv",
        "--python",
        "3.12",
        "--seed",
        str(uv.path),
    ]


def test_install_commands(uv, tmp_path):
    lock = tmp_path / "seamm.lock.txt"
    lock.write_text("seamm==1\n")
    uv.install(["seamm", "molsystem==2"], constraints=lock, upgrade=True)
    cmd = uv.calls[-1]
    assert cmd[:3] == ["/fake/uv", "pip", "install"]
    assert "--refresh" in cmd and "--upgrade" in cmd
    assert cmd[cmd.index("--constraints") + 1] == str(lock)
    assert cmd[-4:] == ["seamm", "molsystem==2", "--python", str(uv.python)]

    uv.install("seamm", refresh=False)
    assert "--refresh" not in uv.calls[-1]
    uv.install([])
    assert uv.calls[-1][1:3] == ["pip", "install"]  # unchanged: nothing run


def test_list_normalizes(uv, monkeypatch):
    monkeypatch.setattr(type(uv), "exists", property(lambda self: True))
    assert uv.list() == {"seamm-util": {"version": "1"}}


def test_run_error(uv, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _Result(returncode=2, stderr="boom")
    )
    with pytest.raises(UvError, match="boom"):
        uv.run("pip", "install", "x")


@pytest.mark.skipif(find_uv() is None, reason="uv not installed")
def test_real_environment(tmp_path):
    """Create a real environment, install a tiny package, list, remove."""
    u = Uv(tmp_path, python_version="3.12")
    u.create()
    assert u.exists
    assert u.python_version_installed().startswith("3.12")
    u.install("six", refresh=False)
    assert "six" in u.list()
    assert u.which("python") == u.python
    assert "six==" in u.freeze()
    u.uninstall("six")
    assert "six" not in u.list()
    u.remove()
    assert not Path(u.path).exists()


def test_tool_upgrade_refreshes(uv):
    assert uv.tool_upgrade("seamm-manager")
    cmd = uv.calls[-1]
    assert cmd[1:3] == ["tool", "install"]
    assert "--force" in cmd and "--refresh" in cmd
    assert cmd[cmd.index("--python") + 1] == "3.12"
    assert cmd[-1] == "seamm-manager"
