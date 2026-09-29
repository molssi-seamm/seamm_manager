# -*- coding: utf-8 -*-
"""The code-environment policy: own, shared or prefixed conda environments."""

import logging
import sys

import pytest

from seamm_manager import my, policy
from seamm_manager.installer_base import InstallerBase


@pytest.fixture
def roots(tmp_path, monkeypatch):
    default = tmp_path / "SEAMM"
    new = tmp_path / "SEAMM_NEW"
    default.mkdir()
    new.mkdir()
    monkeypatch.setattr(policy, "DEFAULT_ROOT", default)
    monkeypatch.setattr(sys, "argv", ["mopac-step-installer", "show"])
    monkeypatch.setattr(my, "logger", logging.getLogger("test"), raising=False)
    return default, new


def test_policy_defaults_and_setting(roots):
    default, new = roots
    assert policy.code_environment_policy(default) == "own"
    assert policy.code_environment_policy(new) == "shared"
    policy.set_code_environment_policy(new, "prefixed")
    assert policy.code_environment_policy(new) == "prefixed"
    with pytest.raises(ValueError):
        policy.set_code_environment_policy(default, "shared")
    with pytest.raises(ValueError):
        policy.set_code_environment_policy(new, "borrowed")


def test_prefixed_environment():
    assert policy.prefixed_environment("seamm-lammps", "SEAMM_NEW") == (
        "seamm-SEAMM_NEW-lammps"
    )
    assert policy.prefixed_environment("seamm-lammps", "") == "seamm-lammps"


class _Conda:
    def __init__(self, existing=("seamm-mopac",)):
        self.calls = []
        self.existing = set(existing)

    def exists(self, name):
        return name in self.existing

    def create_environment(self, path, name=None):
        self.calls.append(("create", name))

    def update_environment(self, path, name=None, **kw):
        self.calls.append(("update", name))

    def remove_environment(self, name):
        self.calls.append(("remove", name))


def _installer(tmp_path, monkeypatch, root):
    monkeypatch.setenv("SEAMM_ROOT", str(root))
    ini = tmp_path / "seamm.ini"
    ini.write_text("")
    inst = InstallerBase(ini_file=str(ini))
    inst.section = "mopac-step"
    inst.environment = "seamm-mopac"
    inst.environment_file = tmp_path / "seamm-mopac.yml"
    inst._conda = _Conda()
    return inst


MOPAC_INI = (
    "[local]\ninstallation = conda\nconda-environment = seamm-mopac\ncode = mopac\n"
)


def test_shared_installation_never_touches_conda(roots, tmp_path, monkeypatch):
    default, new = roots
    (default / "mopac.ini").write_text(MOPAC_INI)
    inst = _installer(tmp_path, monkeypatch, new)
    assert inst.shared_codes
    inst.install()
    assert (new / "mopac.ini").read_text() == MOPAC_INI  # the default's, copied
    inst.update()
    inst.uninstall()
    assert inst.conda.calls == []


def test_shared_installation_reports_missing_code(roots, tmp_path, monkeypatch, capsys):
    default, new = roots
    inst = _installer(tmp_path, monkeypatch, new)
    inst.install()
    assert "install the code there first" in capsys.readouterr().out
    assert not (new / "mopac.ini").exists()
    assert inst.conda.calls == []


def test_prefixed_installation_makes_its_own_environment(roots, tmp_path, monkeypatch):
    default, new = roots
    policy.set_code_environment_policy(new, "prefixed")
    inst = _installer(tmp_path, monkeypatch, new)
    monkeypatch.setattr(inst, "check_exe_configuration_file", lambda: None)
    (new / "mopac.ini").write_text("[local]\n")
    inst.exe_config.path = new / "mopac.ini"
    monkeypatch.setattr(inst.exe_config, "save", lambda: None)
    inst.install()
    assert inst.conda.calls == [("create", "seamm-SEAMM_NEW-mopac")]


def test_default_installation_owns_its_environments(roots, tmp_path, monkeypatch):
    default, new = roots
    inst = _installer(tmp_path, monkeypatch, default)
    inst._conda = _Conda(existing=())
    monkeypatch.setattr(inst, "check_exe_configuration_file", lambda: None)
    (default / "mopac.ini").write_text("[local]\n")
    inst.exe_config.path = default / "mopac.ini"
    monkeypatch.setattr(inst.exe_config, "save", lambda: None)
    inst.install()
    assert inst.conda.calls == [("create", "seamm-mopac")]


def test_tool_refuses_installers_with_an_old_venv_manager(roots, monkeypatch, capsys):
    import subprocess as sp

    from seamm_manager import util

    default, new = roots
    ran = []

    class _Uv:
        def which(self, name):
            return new / "venv" / "bin" / name

    def fake_run(cmd, **kwargs):
        if cmd[1:3] == ["-c", "import seamm_manager.policy"]:
            return sp.CompletedProcess(cmd, 1, "", "ModuleNotFoundError")
        ran.append(cmd)
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(my, "uv", _Uv())
    monkeypatch.setattr(my, "root", new)  # a shared installation
    monkeypatch.setattr(util.subprocess, "run", fake_run)
    util.run_plugin_installer("mopac-step", "install", verbose=False)
    assert ran == []
    assert "too old" in capsys.readouterr().out
    util.run_plugin_installer("mopac-step", "show", verbose=False)  # read-only: runs
    assert len(ran) == 1

    monkeypatch.setattr(my, "root", default)  # the default installation: always runs
    util.run_plugin_installer("mopac-step", "install", verbose=False)
    assert len(ran) == 2


def test_install_keeps_an_existing_environment(roots, tmp_path, monkeypatch, capsys):
    """A reinstall uses the environment that is there; 'update' refreshes it."""
    default, new = roots
    inst = _installer(tmp_path, monkeypatch, default)
    monkeypatch.setattr(inst, "check_exe_configuration_file", lambda: None)
    (default / "mopac.ini").write_text("[local]\n")
    inst.exe_config.path = default / "mopac.ini"
    monkeypatch.setattr(inst.exe_config, "save", lambda: None)
    inst.install()
    assert inst.conda.calls == []
    assert (
        "Using the existing Conda environment 'seamm-mopac'" in capsys.readouterr().out
    )
