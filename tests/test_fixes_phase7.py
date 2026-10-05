# -*- coding: utf-8 -*-
"""seamm_manager#26-#29 (phase 7 of the parallel-execution campaign)."""

from pathlib import Path
from types import SimpleNamespace

from seamm_manager import my
from seamm_manager import services as services_module
from seamm_manager import update as update_module
from seamm_manager.installer_base import InstallerBase

# ---- #29: no installer for a package refused as not a SEAMM package ---------


class _Uv:
    exists = False

    def __init__(self, installed):
        self.installed = installed

    def list(self):
        return {k: {"version": v} for k, v in self.installed.items()}

    def install(self, *args, **kwargs):
        pass

    def freeze(self):
        return ""


def test_refused_package_gets_no_installer(monkeypatch, tmp_path):
    uv = _Uv({"seamm": "2026.10.5", "pyxtal-step": "2024.1.1"})
    monkeypatch.setattr(my, "uv", uv)
    monkeypatch.setattr(my, "options", SimpleNamespace(no_constraints=False))
    monkeypatch.setattr(my, "lock", None)
    packages = {"seamm": {"version": "2026.10.5", "type": "Core package"}}
    monkeypatch.setattr(update_module, "find_packages", lambda progress=False: packages)
    monkeypatch.setattr(update_module, "get_metadata", lambda: {"gui-only": False})
    monkeypatch.setattr(update_module, "sync_manager", lambda: None)
    ran = []
    monkeypatch.setattr(
        update_module, "run_plugin_installer", lambda p, how: ran.append(p)
    )
    update_module.update_packages(["seamm", "pyxtal-step"])
    assert ran == ["seamm"]


# ---- #28: an environment SEAMM did not make is left alone --------------------


class _Conda:
    def __init__(self, root):
        self.root = Path(root)

    def exists(self, name):
        return (self.root / name).is_dir()

    def path(self, name):
        return self.root / name


def test_hand_built_environment_is_not_ours(tmp_path):
    for name in ("seamm-xnn", "seamm-lammps-xnndev", "made-by-seamm-renamed"):
        (tmp_path / name / "conda-meta").mkdir(parents=True)
    (tmp_path / "made-by-seamm-renamed" / "conda-meta" / "seamm-xnn.sha256").write_text(
        "abc\n"
    )
    installer = SimpleNamespace(conda=_Conda(tmp_path), environment="seamm-xnn")
    not_ours = InstallerBase._not_ours.__get__(installer)
    assert not_ours("seamm-lammps-xnndev")  # hand-built: no record, other name
    assert not not_ours("seamm-xnn")  # SEAMM's own name, made before records
    assert not not_ours("made-by-seamm-renamed")  # carries SEAMM's record
    assert not not_ours("missing")  # to be created


# ---- #26: a stopped service stays stopped ------------------------------------


class _Mgr:
    def __init__(self, running):
        self.running = running
        self.calls = []

    def is_installed(self, name):
        return True

    def is_running(self, name):
        return self.running

    def status(self, name):
        return {"running": self.running}

    def restart(self, name, ignore_errors=False):
        self.calls.append(("restart", name))

    def stop(self, name, ignore_errors=False):
        self.calls.append(("stop", name))

    def start(self, name):
        self.calls.append(("start", name))


def test_restart_if_running(monkeypatch):
    mgr = _Mgr(running=False)
    monkeypatch.setattr(services_module, "mgr", mgr)
    assert services_module.restart_if_running("jobserver") is False
    assert mgr.calls == []
    mgr.running = True
    assert services_module.restart_if_running("jobserver") is True
    assert mgr.calls == [("restart", "jobserver")]


def test_relinking_a_stopped_service_never_starts_it(monkeypatch):
    mgr = _Mgr(running=False)
    monkeypatch.setattr(services_module, "mgr", mgr)
    monkeypatch.setattr(
        my, "uv", SimpleNamespace(which=lambda name: Path("/venv/bin/seamm-jobserver"))
    )
    monkeypatch.setattr(services_module, "_program_arguments", lambda name: [])
    created = []
    monkeypatch.setattr(
        services_module,
        "create_service",
        lambda service, **kwargs: created.append((service, kwargs.get("start"))),
    )
    assert services_module.relink_services() == []
    assert created and all(start is False for _, start in created)
    assert ("start", "jobserver") not in mgr.calls


# ---- #27: recreate --latest ---------------------------------------------------


def test_recreate_latest_pins_pypi_releases(monkeypatch, tmp_path):
    from seamm_manager import environment as environment_module
    from seamm_manager import util as util_module
    from seamm_manager import versions as versions_module

    uv = SimpleNamespace(exists=True, list=lambda: {"seamm": {}, "loop-step": {}})
    monkeypatch.setattr(my, "uv", uv)
    monkeypatch.setattr(my, "options", SimpleNamespace(latest=True, force=False))
    monkeypatch.setattr(
        util_module,
        "find_packages",
        lambda progress=False: {"seamm": {}, "loop-step": {}},
    )
    monkeypatch.setattr(util_module, "constraints", lambda: tmp_path / "lock.txt")
    monkeypatch.setattr(
        util_module, "pypi_latest", lambda p: {"seamm": "2026.10.5"}.get(p)
    )
    monkeypatch.setattr(util_module, "write_environment_snapshot", lambda tag: tmp_path)
    monkeypatch.setattr(versions_module, "ensure_versioned", lambda: None)
    built = {}

    def build_version(specs, constraints=None, from_freeze=True, **kwargs):
        built["specs"], built["constraints"] = list(specs), constraints
        return SimpleNamespace()

    monkeypatch.setattr(versions_module, "build_version", build_version)
    monkeypatch.setattr(versions_module, "switch", lambda new, force=False: False)
    environment_module.recreate()
    assert sorted(built["specs"]) == ["loop-step", "seamm==2026.10.5"]
    assert built["constraints"] is None


def test_taskserver_ini_written_once(tmp_path):
    import configparser

    from seamm_manager.install import write_taskserver_ini

    path = write_taskserver_ini(tmp_path)
    config = configparser.ConfigParser()
    config.read(path)
    assert int(config["taskserver"]["cores"]) >= 1
    assert config["taskserver"]["memory"].endswith("GB")
    path.write_text("[taskserver]\ncores = 2\n")
    assert write_taskserver_ini(tmp_path) is None  # never overwritten
    assert path.read_text() == "[taskserver]\ncores = 2\n"
