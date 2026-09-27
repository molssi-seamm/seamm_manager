# -*- coding: utf-8 -*-
"""Installation names, ports and same-root replacement for services."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from seamm_manager import my, naming, services


def test_compute_tag(tmp_path):
    assert naming.compute_tag("~/SEAMM") == ""
    assert naming.compute_tag("~/SEAMM_DEV") == "SEAMM_DEV"
    assert naming.compute_tag(tmp_path / "SEAMM_NEW") == "SEAMM_NEW"
    assert naming.compute_tag("~/SEAMM", name="Prod") == "Prod"


@pytest.mark.parametrize(
    "tag, service, app, bundle",
    [
        ("", "jobserver", "SEAMM", "SEAMM-JobServer"),
        (
            "SEAMM_DEV",
            "jobserver-SEAMM_DEV",
            "SEAMM (SEAMM_DEV)",
            "SEAMM-JobServer-SEAMM_DEV",
        ),
    ],
)
def test_names(monkeypatch, tag, service, app, bundle):
    monkeypatch.setattr(my, "tag", tag)
    assert naming.service_name("jobserver") == service
    assert naming.app_name("SEAMM") == app
    assert naming.bundle_name("SEAMM-JobServer") == bundle


def test_service_kind():
    for name in ("jobserver", "jobserver-SEAMM_NEW", "dev_jobserver"):
        assert naming.service_kind(name) == "jobserver"
    assert naming.service_kind("webui-SEAMM_DEV") == "webui"


class _Mgr:
    """A stand-in for the platform service manager."""

    def __init__(self, services):
        self.services = dict(services)  # name -> {"root", "port"}
        self.deleted, self.created, self.started = [], [], []

    def list(self):
        return list(self.services)

    def status(self, name):
        s = self.services[name]
        return {
            "running": True,
            "root": s.get("root"),
            "port": s.get("port"),
            "dashboard name": None,
        }

    def delete(self, name):
        self.deleted.append(name)
        self.services.pop(name, None)

    def create(self, name, program, *args, **kwargs):
        self.created.append((name, [str(a) for a in args]))
        self.services[name] = {}

    def start(self, name):
        self.started.append(name)


@pytest.fixture
def dev(tmp_path, monkeypatch):
    root = tmp_path / "SEAMM_DEV"
    (root / "venv-webui" / "bin").mkdir(parents=True)
    (root / "venv-webui" / "bin" / "seamm-webui").write_text("")
    monkeypatch.setattr(my, "root", root)
    monkeypatch.setattr(my, "tag", "SEAMM_DEV")
    monkeypatch.setattr(my, "uv", SimpleNamespace(root=root, which=lambda n: f"/x/{n}"))
    monkeypatch.setattr(services, "_launch", lambda s, exe: (exe, [], None))
    monkeypatch.setattr(services.datastore, "ensure", lambda: None)
    monkeypatch.setattr(services, "_port_available", lambda port: port != 55056)
    return root


def test_create_replaces_old_dev_service_on_same_root(dev, monkeypatch):
    mgr = _Mgr(
        {
            "jobserver": {"root": str(Path.home() / "SEAMM")},  # production: kept
            "dev_jobserver": {"root": str(dev)},  # the old name, same root: replaced
        }
    )
    monkeypatch.setattr(services, "mgr", mgr)
    assert services.create_service("jobserver")
    assert mgr.deleted == ["dev_jobserver"]
    assert mgr.created[0][0] == "jobserver-SEAMM_DEV"
    assert "jobserver" in mgr.services


def test_webui_port_reused_from_replaced_service(dev, monkeypatch):
    mgr = _Mgr({"dev_webui": {"root": str(dev), "port": "55155"}})
    monkeypatch.setattr(services, "mgr", mgr)
    services.create_service("webui", webui_host="127.0.0.1")
    name, args = mgr.created[0]
    assert name == "webui-SEAMM_DEV"
    assert args[args.index("--port") + 1] == "55155"


def test_webui_gets_first_free_port(dev, monkeypatch):
    # 55055 is production's, 55056 is taken by something else on the machine
    mgr = _Mgr({"webui": {"root": str(Path.home() / "SEAMM"), "port": "55055"}})
    monkeypatch.setattr(services, "mgr", mgr)
    services.create_service("webui")
    args = mgr.created[0][1]
    assert args[args.index("--port") + 1] == "55057"
    assert mgr.deleted == []  # production's web interface is untouched


def test_existing_service_needs_force(dev, monkeypatch):
    mgr = _Mgr({"jobserver-SEAMM_DEV": {"root": str(dev)}})
    monkeypatch.setattr(services, "mgr", mgr)
    assert services.create_service("jobserver") is False
    assert mgr.created == []
    assert services.create_service("jobserver", force=True)
    assert mgr.deleted == ["jobserver-SEAMM_DEV"]
