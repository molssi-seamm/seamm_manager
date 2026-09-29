# -*- coding: utf-8 -*-
"""update --all reinstalls the manager tool only when there is a newer release."""

import seamm_manager
from seamm_manager import update, util


def test_no_reinstall_when_current(monkeypatch):
    monkeypatch.setattr(seamm_manager, "__version__", "2026.9.29.1")
    monkeypatch.setattr(util, "pypi_latest", lambda name: "2026.9.29.1")
    assert not update._newer_manager_release()


def test_reinstall_when_newer(monkeypatch):
    monkeypatch.setattr(seamm_manager, "__version__", "2026.9.29.1")
    monkeypatch.setattr(util, "pypi_latest", lambda name: "2026.9.30")
    assert update._newer_manager_release()


def test_development_build_is_compared_by_its_release(monkeypatch):
    monkeypatch.setattr(seamm_manager, "__version__", "2026.9.29.1+2.gabc123.dirty")
    monkeypatch.setattr(util, "pypi_latest", lambda name: "2026.9.29.1")
    assert not update._newer_manager_release()


def test_pypi_unreachable_tries_the_upgrade(monkeypatch):
    monkeypatch.setattr(util, "pypi_latest", lambda name: None)
    assert update._newer_manager_release()
