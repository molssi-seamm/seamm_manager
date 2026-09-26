# -*- coding: utf-8 -*-
"""find_conda must work without conda on the PATH (Dock apps, services)."""

import os

from seamm_manager import conda as conda_module
from seamm_manager.conda import find_conda


def test_conda_exe_env_wins(monkeypatch, tmp_path):
    exe = tmp_path / "conda"
    exe.write_text("")
    monkeypatch.setenv("CONDA_EXE", str(exe))
    assert find_conda() == str(exe)


def test_found_in_standard_location_and_added_to_path(monkeypatch, tmp_path):
    monkeypatch.delenv("CONDA_EXE", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    base = tmp_path / "miniforge3"
    (base / "condabin").mkdir(parents=True)
    (base / "condabin" / "conda").write_text("")
    monkeypatch.setattr(conda_module, "_CONDA_LOCATIONS", (str(base),))
    found = find_conda()
    assert found == str(base / "condabin" / "conda")
    assert os.environ["PATH"].startswith(str(base / "condabin"))


def test_not_found(monkeypatch):
    monkeypatch.delenv("CONDA_EXE", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setattr(conda_module, "_CONDA_LOCATIONS", ())
    assert find_conda() is None
