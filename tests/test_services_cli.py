# -*- coding: utf-8 -*-
"""The services sub-commands call the right functions and report errors."""

import argparse
from types import SimpleNamespace

from seamm_manager import my
from seamm_manager import services


def _parse(*argv):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    services.setup(subparsers)
    return parser.parse_args(["services", *argv])


def test_each_command_is_wired_to_its_function():
    for command in ("create", "delete", "start", "stop", "restart", "show", "status"):
        assert _parse(command).func is getattr(services, command), command


class _Mgr:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def restart(self, name):
        self.calls.append(("restart", name))
        if name == self.fail:
            raise RuntimeError(f"Starting the service '{name}' was not successful")


def test_restart_restarts_and_reports_errors(monkeypatch, capsys):
    mgr = _Mgr(fail="webui")
    monkeypatch.setattr(services, "mgr", mgr)
    monkeypatch.setattr(my, "development", False)
    monkeypatch.setattr(my, "options", SimpleNamespace(services=["jobserver", "webui"]))
    services.restart()
    assert mgr.calls == [("restart", "jobserver"), ("restart", "webui")]
    out = capsys.readouterr().out
    assert "The service 'jobserver' was restarted." in out
    assert "Starting the service 'webui' was not successful" in out
