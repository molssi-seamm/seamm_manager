# -*- coding: utf-8 -*-
"""The environment gets the running manager's release when the package list lags."""

import seamm_manager
from seamm_manager import my
from seamm_manager.util import sync_manager


class _Uv:
    def __init__(self, installed):
        self.installed = installed
        self.calls = []

    def list(self):
        return {"seamm-manager": {"version": self.installed}} if self.installed else {}

    def install(self, packages, **kw):
        self.calls.append(packages)


def test_older_in_env_is_updated(monkeypatch):
    monkeypatch.setattr(seamm_manager, "__version__", "2026.9.26.3")
    uv = _Uv("2026.9.26"); monkeypatch.setattr(my, "uv", uv)
    assert sync_manager() == "2026.9.26.3"
    assert uv.calls == ["seamm-manager==2026.9.26.3"]


def test_same_or_newer_left_alone(monkeypatch):
    monkeypatch.setattr(seamm_manager, "__version__", "2026.9.26.3")
    for v in ("2026.9.26.3", "2026.9.27"):
        uv = _Uv(v); monkeypatch.setattr(my, "uv", uv)
        assert sync_manager() is None and uv.calls == []


def test_dev_build_and_absent_do_nothing(monkeypatch):
    monkeypatch.setattr(seamm_manager, "__version__", "2026.9.26.3+2.gabc.dirty")
    uv = _Uv("2026.9.26"); monkeypatch.setattr(my, "uv", uv)
    assert sync_manager() is None
    monkeypatch.setattr(seamm_manager, "__version__", "2026.9.26.3")
    uv = _Uv(None); monkeypatch.setattr(my, "uv", uv)
    assert sync_manager() is None
