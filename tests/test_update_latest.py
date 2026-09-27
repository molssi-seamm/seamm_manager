# -*- coding: utf-8 -*-
"""``update --latest`` takes a same-day release from PyPI, unconstrained."""

from types import SimpleNamespace

from seamm_manager import my
from seamm_manager import update as update_module
from seamm_manager.util import pypi_latest


class _Uv:
    def __init__(self, installed):
        self.installed = installed
        self.calls = []

    def list(self):
        return {k: {"version": v} for k, v in self.installed.items()}

    def install(self, packages, constraints=None, upgrade=False, **kw):
        self.calls.append((list(packages), constraints, upgrade))

    def freeze(self):
        return ""


def _setup(monkeypatch, tmp_path, pypi):
    uv = _Uv({"xnn-step": "2026.9.26", "seamm": "2026.9.25.1"})
    monkeypatch.setattr(my, "uv", uv)
    monkeypatch.setattr(my, "options", SimpleNamespace(no_constraints=False))
    lock = tmp_path / "seamm.lock.txt"
    lock.write_text("xnn-step==2026.9.26\n")
    monkeypatch.setattr(my, "lock", lock)
    packages = {
        "xnn-step": {"version": "2026.9.26", "type": "Plug-in"},
        "seamm": {"version": "2026.9.25.1", "type": "Core package"},
    }
    monkeypatch.setattr(update_module, "find_packages", lambda progress=False: packages)
    monkeypatch.setattr(update_module, "get_metadata", lambda: {"gui-only": True})
    monkeypatch.setattr(update_module, "sync_manager", lambda: None)
    monkeypatch.setattr(update_module, "write_environment_snapshot", lambda tag: lock)
    monkeypatch.setattr(update_module, "pypi_latest", lambda p: pypi.get(p))
    return uv, lock


def test_latest_pins_pypi_release_without_lock(monkeypatch, tmp_path):
    uv, lock = _setup(monkeypatch, tmp_path, {"xnn-step": "2026.9.27", "seamm": None})
    update_module.update_packages(["xnn-step", "seamm"], latest=True)
    assert uv.calls == [(["xnn-step==2026.9.27"], None, True)]


def test_without_latest_the_list_and_lock_rule(monkeypatch, tmp_path):
    uv, lock = _setup(monkeypatch, tmp_path, {"xnn-step": "2026.9.27"})
    update_module.update_packages(["xnn-step"], latest=False)
    assert uv.calls == []  # the list says 2026.9.26 is current


def test_latest_falls_back_when_pypi_unreachable(monkeypatch, tmp_path):
    uv, lock = _setup(monkeypatch, tmp_path, {})
    update_module.update_packages(["xnn-step"], latest=True)
    assert uv.calls == []


def test_pypi_latest_uses_the_simple_index(monkeypatch):
    import requests

    seen = {}

    class _R:
        def __init__(self, status, data):
            self.status_code = status
            self._data = data

        def json(self):
            return self._data

    def fake_get(url, headers, timeout):
        seen["url"], seen["headers"] = url, headers
        return _R(
            200,
            {
                "versions": ["2026.9.20", "2026.9.27", "2026.9.28rc1", "2026.9.29"],
                "files": [
                    {"filename": "x-2026.9.27-py3-none-any.whl", "yanked": False},
                    {"filename": "x-2026.9.29-py3-none-any.whl", "yanked": "bad"},
                ],
            },
        )

    monkeypatch.setattr(requests, "get", fake_get)
    # the pre-release and the yanked 2026.9.29 are skipped
    assert pypi_latest("x") == "2026.9.27"
    assert seen["url"] == "https://pypi.org/simple/x/"
    assert seen["headers"]["Accept"] == "application/vnd.pypi.simple.v1+json"
    assert seen["headers"]["Cache-Control"] == "no-cache"


def test_pypi_latest_handles_failures(monkeypatch):
    import requests

    class _R:
        status_code = 404

        def json(self):
            return {}

    monkeypatch.setattr(requests, "get", lambda url, headers, timeout: _R())
    assert pypi_latest("no-such-seamm-package") is None

    def boom(url, headers, timeout):
        raise OSError("offline")

    monkeypatch.setattr(requests, "get", boom)
    assert pypi_latest("seamm") is None
