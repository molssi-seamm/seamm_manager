# -*- coding: utf-8 -*-
"""seamm-installer must leave the environment before seamm-manager enters it."""

from seamm_manager import my
from seamm_manager.util import retire_installer


class _Uv:
    def __init__(self):
        self.removed = []

    def uninstall(self, packages):
        self.removed.append(packages)


def test_retires_when_manager_requested(monkeypatch):
    uv = _Uv()
    monkeypatch.setattr(my, "uv", uv)
    assert retire_installer(["seamm", "seamm-manager==1"], {"seamm-installer": {}})
    assert uv.removed == ["seamm-installer"]


def test_nothing_when_not_requested_or_not_installed(monkeypatch):
    uv = _Uv()
    monkeypatch.setattr(my, "uv", uv)
    assert not retire_installer(["seamm"], {"seamm-installer": {}})
    assert not retire_installer(["seamm-manager"], {"seamm": {}})
    assert uv.removed == []
