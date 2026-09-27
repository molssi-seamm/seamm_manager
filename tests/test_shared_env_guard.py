# -*- coding: utf-8 -*-
"""A plug-in installer's update must not touch an environment it does not own."""

from seamm_manager.installer_base import InstallerBase


class _Conda:
    def __init__(self):
        self.updated = []

    def update_environment(self, *args, **kwargs):
        self.updated.append((args, kwargs))


class _Config:
    def __init__(self, data):
        self._data = data
        self.path = "/nonexistent/test.ini"

    def get_values(self, section):
        return dict(self._data)

    def set_value(self, *a, **k):
        pass

    def save(self):
        pass


def _installer(env_in_ini):
    inst = InstallerBase.__new__(InstallerBase)
    inst.environment = "seamm-xnn"
    inst.environment_file = "seamm-xnn.yml"
    inst._conda = _Conda()
    inst._exe_config = _Config(
        {"installation": "conda", "conda-environment": env_in_ini}
    )
    inst.check_exe_configuration_file = lambda: None
    inst.logger = __import__("logging").getLogger("test")
    return inst


def test_shared_environment_is_left_alone(capsys):
    inst = _installer("seamm-lammps")
    inst.update()
    assert inst._conda.updated == []
    assert "shared" in capsys.readouterr().out


def test_own_environment_is_updated():
    inst = _installer("seamm-xnn")
    inst.update()
    assert len(inst._conda.updated) == 1
