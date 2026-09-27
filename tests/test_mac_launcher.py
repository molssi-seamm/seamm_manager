# -*- coding: utf-8 -*-
"""The macOS app bundles use a compiled launcher, not a script, as their executable.

A script executable makes Apple Silicon Macs without Rosetta ask to install it.
"""

import importlib.resources
import plistlib
import subprocess
import sys

import pytest

from seamm_manager import mac

darwin = pytest.mark.skipif(sys.platform != "darwin", reason="macOS app bundles")


def _target(tmp_path):
    """A stand-in for the SEAMM executable that records its arguments."""
    out = tmp_path / "ran.txt"
    exe = tmp_path / "fake_seamm"
    exe.write_text(f'#!/bin/bash\necho "$@" > "{out}"\n')
    exe.chmod(0o755)
    return exe, out


def _icons(tmp_path):
    icons = tmp_path / "x.icns"
    icons.write_bytes(b"icns")
    return icons


def test_shipped_launcher_is_universal():
    launcher = importlib.resources.files("seamm_manager") / "data" / "macos_launcher"
    assert launcher.read_bytes()[:4] == b"\xca\xfe\xba\xbe"  # universal Mach-O


def test_is_macho(tmp_path):
    script = tmp_path / "s"
    script.write_text("#!/bin/bash\n")
    assert not mac.is_macho(script)
    assert not mac.is_macho(tmp_path / "missing")


@darwin
def test_create_app_uses_launcher(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    exe, out = _target(tmp_path)
    mac.create_app(
        exe, "--root", "/r", name="Test", user_only=True, icons=_icons(tmp_path)
    )
    contents = tmp_path / "Applications" / "Test.app" / "Contents"
    executable = contents / "MacOS" / "Test"
    assert mac.is_macho(executable)
    script = (contents / "Resources" / "Test.sh").read_text()
    assert f'exec "{exe}" --root /r "$@"' in script
    with (contents / "Info.plist").open("rb") as fd:
        assert plistlib.load(fd)["CFBundleExecutable"] == "Test"

    subprocess.run([str(executable), "extra"], check=True, timeout=30)
    assert out.read_text().strip() == "--root /r extra"


@darwin
def test_update_app_converts_script_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    exe, out = _target(tmp_path)
    contents = tmp_path / "Applications" / "Old.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    old = contents / "MacOS" / "Old"
    old.write_text(f'#!/bin/bash\n"{exe}" --old\n')
    old.chmod(0o755)
    with (contents / "Info.plist").open("wb") as fd:
        plistlib.dump(
            {"CFBundleExecutable": "Old", "CFBundleShortVersionString": "1"}, fd
        )

    mac.update_app("Old", "2")

    assert mac.is_macho(old)
    assert (
        (contents / "Resources" / "Old.sh")
        .read_text()
        .endswith(f'exec "{exe}" --old "$@"\n')
    )
    with (contents / "Info.plist").open("rb") as fd:
        assert plistlib.load(fd)["CFBundleShortVersionString"] == "2"
    subprocess.run([str(old)], check=True, timeout=30)
    assert out.read_text().strip() == "--old"

    # A second update leaves the launcher alone
    mac.update_app("Old", "3")
    assert (contents / "Resources" / "Old.sh").read_text().count("exec ") == 1


def test_exec_script():
    old = '#!/bin/bash\n"/x/seamm"\n'
    assert mac._exec_script(old) == '#!/bin/bash\nexec "/x/seamm" "$@"\n'
    new = '#!/bin/bash\nexec "/x/seamm" "$@"\n'
    assert mac._exec_script(new) == new
