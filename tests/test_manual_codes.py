# -*- coding: utf-8 -*-
"""Hand-installed codes (ORCA, Gaussian, VASP, ...) get their .ini template."""

import logging
import sys

import pytest

from seamm_manager import my, policy
from seamm_manager.installer_base import InstallerBase

TEMPLATE = "# How to run VASP\n[local]\ninstallation = local\n# code = vasp_std\n"


@pytest.fixture
def default_root(tmp_path, monkeypatch):
    root = tmp_path / "SEAMM"
    root.mkdir()
    monkeypatch.setattr(policy, "DEFAULT_ROOT", root)
    monkeypatch.setattr(sys, "argv", ["vasp-step-installer", "show"])
    monkeypatch.setattr(my, "logger", logging.getLogger("test"), raising=False)
    monkeypatch.setenv("SEAMM_ROOT", str(root))
    return root


def _installer(tmp_path, template=True):
    ini = tmp_path / "seamm.ini"
    ini.write_text("")
    inst = InstallerBase(ini_file=str(ini))
    inst.section = "vasp-step"
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    if template:
        (data / "vasp.ini").write_text(TEMPLATE)
    inst.resource_path = data
    return inst


def test_install_writes_the_template(default_root, tmp_path, capsys):
    inst = _installer(tmp_path)
    assert inst.manual_code
    inst.install()
    assert (default_root / "vasp.ini").read_text() == TEMPLATE
    out = capsys.readouterr().out
    assert "Install it yourself, then edit" in out and "vasp.ini" in out


def test_existing_file_is_never_changed(default_root, tmp_path, capsys):
    mine = "[local]\ninstallation = local\ncode = mpiexec -np {NTASKS} vasp_std\n"
    (default_root / "vasp.ini").write_text(mine)
    inst = _installer(tmp_path)
    inst.install()
    inst.update()
    assert (default_root / "vasp.ini").read_text() == mine
    assert "Unable to update" not in capsys.readouterr().out


def test_update_writes_a_missing_template_quietly_otherwise(
    default_root, tmp_path, capsys
):
    inst = _installer(tmp_path)
    inst.update()
    assert (default_root / "vasp.ini").exists()
    assert "Unable to update" not in capsys.readouterr().out


def test_no_template_just_says_where(default_root, tmp_path, capsys):
    inst = _installer(tmp_path, template=False)
    inst.install()
    assert not (default_root / "vasp.ini").exists()
    assert "give its location in" in capsys.readouterr().out


def test_conda_codes_are_not_manual(default_root, tmp_path):
    inst = _installer(tmp_path)
    inst.environment = "seamm-mopac"
    inst.environment_file = tmp_path / "seamm-mopac.yml"
    assert not inst.manual_code
