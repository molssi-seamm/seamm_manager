# -*- coding: utf-8 -*-
"""The manager works on the installation it runs from unless told otherwise."""

from seamm_manager.__main__ import choose_root


def test_choose_root(tmp_path, monkeypatch):
    monkeypatch.delenv("SEAMM_ROOT", raising=False)
    dev = tmp_path / "SEAMM_DEV"
    (dev / "venv").mkdir(parents=True)
    (dev / "Jobs").mkdir()
    venv = dev / "venv"

    assert choose_root(prefix=venv) == str(dev)  # its own installation
    assert choose_root(prefix=tmp_path / "tools" / "seamm-manager") == "~/SEAMM"
    assert choose_root("/else", prefix=venv) == "/else"  # --root wins
    assert choose_root(development=True, prefix=venv) == "~/SEAMM_DEV"
    monkeypatch.setenv("SEAMM_ROOT", "/from/env")
    assert choose_root(prefix=venv) == "/from/env"
