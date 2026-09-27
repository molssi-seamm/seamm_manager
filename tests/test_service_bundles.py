# -*- coding: utf-8 -*-
"""macOS services run the interpreter from a named app bundle.

So they show up as e.g. SEAMM-JobServer with the SEAMM icon, not python3.12.
"""

import ctypes
import importlib.resources
import os
from pathlib import Path
import plistlib
import subprocess
import sys

import pytest

from seamm_manager import mac

darwin = pytest.mark.skipif(sys.platform != "darwin", reason="macOS services")
ICONS = importlib.resources.files("seamm_manager") / "data" / "SEAMM.icns"


def _static_python():
    """The running interpreter, if it can run from another directory.

    uv's Python is one statically linked file; framework or shared builds find
    libpython relative to themselves, so a link elsewhere cannot start.
    """
    real = Path(sys.executable).resolve()
    out = subprocess.run(["otool", "-L", str(real)], capture_output=True, text=True)
    return (
        None if "libpython" in out.stdout or "Python.framework" in out.stdout else real
    )


def _fake_venv(tmp_path, real):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(real)
    return venv / "bin" / "python"


@darwin
def test_bundle_structure(tmp_path):
    python = _fake_venv(tmp_path, Path(sys.executable).resolve())
    exe = mac.create_service_bundle(tmp_path / "services", "SEAMM-Test", python, ICONS)

    assert exe == tmp_path / "services/SEAMM-Test.app/Contents/MacOS/SEAMM-Test"
    assert exe.stat().st_ino == python.resolve().stat().st_ino  # hard link
    contents = exe.parent.parent
    assert (contents / "Resources" / "SEAMM.icns").exists()
    with (contents / "Info.plist").open("rb") as fd:
        info = plistlib.load(fd)
    assert info["CFBundleExecutable"] == "SEAMM-Test"
    assert info["LSUIElement"] is True
    assert info["SEAMMPython"] == str(python)

    # Current: nothing to do. Replaced interpreter: re-linked.
    assert mac.refresh_service_bundle(exe.parent.parent.parent) is False
    exe.unlink()
    exe.write_text("stale")
    assert mac.refresh_service_bundle(exe.parent.parent.parent) is True
    assert exe.stat().st_ino == python.resolve().stat().st_ino
    assert mac.refresh_service_bundle(tmp_path / "missing.app") is False


@darwin
def test_bundled_interpreter_is_named_and_uses_venv(tmp_path):
    real = _static_python()
    if real is None:
        pytest.skip("this Python is not a single static file (not uv's)")
    python = _fake_venv(tmp_path, real)
    (python.parent.parent / "pyvenv.cfg").write_text(f"home = {real.parent}\n")
    exe = mac.create_service_bundle(tmp_path / "services", "SEAMM-Test", python, ICONS)

    env = {**os.environ, "__PYVENV_LAUNCHER__": str(python)}
    env.pop("PYTHONPATH", None)
    code = (
        "import os, sys, time; print(sys.prefix); "
        "print(os.environ.get('__PYVENV_LAUNCHER__')); sys.stdout.flush(); "
        "time.sleep(3)"
    )
    proc = subprocess.Popen([str(exe), "-c", code], env=env, stdout=subprocess.PIPE)
    try:
        prefix = proc.stdout.readline().decode().strip()
        leaked = proc.stdout.readline().decode().strip()
        buf = ctypes.create_string_buffer(64)
        ctypes.CDLL("/usr/lib/libproc.dylib").proc_name(proc.pid, buf, 64)
    finally:
        proc.wait(timeout=30)
    assert buf.value.decode() == "SEAMM-Test"  # what Activity Monitor shows
    assert prefix == str(python.parent.parent)  # the venv
    assert leaked == "None"  # not passed on to the service's children


@darwin
def test_launchd_plist_gets_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    mgr = mac.ServiceManager(prefix="org.molssi.test")
    mgr.create(
        "svc",
        "/x/SEAMM-Test.app/Contents/MacOS/SEAMM-Test",
        "/x/venv/bin/seamm-jobserver",
        "--root",
        "/r",
        environment={"__PYVENV_LAUNCHER__": "/x/venv/bin/python"},
    )
    path = tmp_path / "Library/LaunchAgents/org.molssi.test.svc.plist"
    with path.open("rb") as fd:
        plist = plistlib.load(fd)
    assert plist["ProgramArguments"][:2] == [
        "/x/SEAMM-Test.app/Contents/MacOS/SEAMM-Test",
        "/x/venv/bin/seamm-jobserver",
    ]
    assert plist["EnvironmentVariables"] == {
        "__PYVENV_LAUNCHER__": "/x/venv/bin/python"
    }


def test_stop_waits_for_launchd(monkeypatch):
    """bootout returns early; stop must wait until the job is really gone."""
    calls = []
    prints = iter([0, 0, 0, 1])  # print succeeds (still there) until it fails

    class R:
        def __init__(self, rc):
            self.returncode = rc
            self.stderr = ""

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd.startswith("launchctl print"):
            return R(next(prints, 1))
        return R(0)

    monkeypatch.setattr(mac.subprocess, "run", fake_run)
    mgr = mac.ServiceManager(prefix="org.molssi.test")
    mgr._data = {"svc": ("gui/501", "gui/501/org.molssi.test.svc", Path("/x"))}
    monkeypatch.setattr(mgr, "list", lambda: ["svc"])
    mgr.stop("svc")
    assert calls[0].startswith("launchctl print")  # is_running
    assert calls[1].startswith("launchctl bootout")
    assert [c for c in calls[2:] if c.startswith("launchctl print")] == [
        "launchctl print gui/501/org.molssi.test.svc"
    ] * 3
