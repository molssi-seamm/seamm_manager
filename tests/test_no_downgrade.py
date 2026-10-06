# -*- coding: utf-8 -*-
"""seamm_manager#34: install and update never move a package backwards."""

from types import SimpleNamespace

from seamm_manager import versions
from seamm_manager.uv import floored_constraints, freeze_without

LOCK = """\
# The published lock (nightly)
alembic==1.20.0
seamm-exec==2026.10.5.2
pywin32==312 ; sys_platform == 'win32'
orca-step==2026.10.6
"""


def test_a_pin_below_the_installed_version_becomes_a_floor():
    text, floored = floored_constraints(
        LOCK, {"seamm_exec": "2026.10.6.1", "alembic": "1.20.0", "pywin32": "300"}
    )
    lines = text.splitlines()
    assert "seamm-exec>=2026.10.6.1" in lines
    assert floored == ["seamm-exec"]
    # Unchanged: equal or older installed versions, markers, comments, the rest
    assert "alembic==1.20.0" in lines
    assert "pywin32==312 ; sys_platform == 'win32'" in lines
    assert "orca-step==2026.10.6" in lines
    assert lines[0].startswith("#")


def test_a_floor_keeps_its_marker():
    text, floored = floored_constraints(LOCK, {"pywin32": "320"})
    assert 'pywin32>=320 ; sys_platform == "win32"' in text.splitlines()
    assert floored == ["pywin32"]


def test_nothing_installed_leaves_the_lock_as_it_is():
    text, floored = floored_constraints(LOCK, {})
    assert text.splitlines() == LOCK.splitlines()
    assert floored == []


FREEZE = """\
dftbplus-step==2026.10.6
seamm-exec==2026.10.5.2
-e file:///Users/me/Work/SEAMM/seamm_manager
seamm_widgets @ file:///Users/me/Work/SEAMM/seamm_widgets
orca-step==2026.10.6.1
"""


def test_the_packages_being_changed_are_left_out_of_the_copy():
    """The copy of a downgraded environment pinned seamm-exec==2026.10.5.2 next
    to dftbplus-step==2026.10.6 (needs >=2026.10.6), which no resolver can
    satisfy, so an update could not even start."""
    kept = freeze_without(FREEZE, ["seamm_exec"]).splitlines()
    assert "seamm-exec==2026.10.5.2" not in kept
    assert "dftbplus-step==2026.10.6" in kept
    assert "-e file:///Users/me/Work/SEAMM/seamm_manager" in kept
    assert "orca-step==2026.10.6.1" in kept
    # A direct-URL line is matched by name too
    assert not any(
        line.startswith("seamm_widgets")
        for line in freeze_without(FREEZE, ["seamm-widgets"]).splitlines()
    )


def test_nothing_to_leave_out():
    assert freeze_without(FREEZE, []) == FREEZE


class FakeEnvironment:
    def __init__(self, versions_, conflicts=""):
        self._versions = versions_
        self._conflicts = conflicts

    def list(self):
        return {k: {"version": v} for k, v in self._versions.items()}

    def report_conflicts(self, quiet=False):
        return self._conflicts


def test_regressions_finds_a_downgrade_and_new_conflicts():
    current = FakeEnvironment(
        {"seamm-exec": "2026.10.6.1", "orca-step": "2026.10.6.1", "mbe-step": "1"}
    )
    new = FakeEnvironment(
        {"seamm-exec": "2026.10.5.2", "orca-step": "2026.10.6.1", "mbe-step": "2"},
        conflicts="orca-step 2026.10.6.1 has requirement seamm-exec>=2026.10.6.1",
    )
    problems = versions.regressions(current, new, ["mbe-step"])
    assert problems == [
        "seamm-exec would go back from 2026.10.6.1 to 2026.10.5.2",
        "newly unmet: orca-step 2026.10.6.1 has requirement seamm-exec>=2026.10.6.1",
    ]


def test_regressions_allows_an_explicit_older_pin_and_old_conflicts():
    old_conflict = "x 1 has requirement y>2"
    current = FakeEnvironment({"seamm": "2026.10.5"}, conflicts=old_conflict)
    new = FakeEnvironment({"seamm": "2026.10.2"}, conflicts=old_conflict)
    assert versions.regressions(current, new, ["seamm==2026.10.2"]) == []


def test_regressions_ignores_upgrades():
    current = FakeEnvironment({"seamm-exec": "2026.10.5.2"})
    new = FakeEnvironment({"seamm-exec": "2026.10.6.1"})
    assert versions.regressions(current, new, ["seamm-exec"]) == []


def test_apply_change_does_not_switch_to_a_regressed_build(monkeypatch, capsys):
    from seamm_manager import my, util

    current = FakeEnvironment({"seamm-exec": "2026.10.6.1"})
    current.exists = True
    new = FakeEnvironment({"seamm-exec": "2026.10.5.2"})
    new.path = SimpleNamespace(name="2026-10-06T14-00-00")
    monkeypatch.setattr(my, "uv", current)
    monkeypatch.setattr(my, "options", SimpleNamespace(in_place=False, force=False))
    monkeypatch.setattr(versions, "ensure_versioned", lambda: None)
    monkeypatch.setattr(versions, "build_version", lambda *a, **k: new)
    monkeypatch.setattr(util, "sync_manager", lambda: None)
    switched = []
    monkeypatch.setattr(versions, "switch", lambda *a, **k: switched.append(1) or True)

    assert versions.apply_change(["mbe-step"]) is False
    assert switched == []
    out = capsys.readouterr().out
    assert "NOT switched" in out and "seamm-exec would go back" in out
    assert "environment switch 2026-10-06T14-00-00" in out


def test_a_taken_version_name_moves_to_the_next_second(tmp_path):
    from datetime import datetime

    from seamm_manager.uv import Uv

    current = Uv(tmp_path, name="venv")
    (tmp_path / "venvs" / "2026-10-06T16-08-35").mkdir(parents=True)
    (tmp_path / "venvs" / "2026-10-06T16-08-36").mkdir()
    name = versions._free_version_name(current, datetime(2026, 10, 6, 16, 8, 35))
    assert name == "2026-10-06T16-08-37"


def test_regressions_reports_a_removed_package_unless_asked_for():
    current = FakeEnvironment({"seamm-exec": "2026.10.6.1", "torch": "2.8.0"})
    new = FakeEnvironment({"seamm-exec": "2026.10.6.1"})
    assert versions.regressions(current, new, ["mbe-step"]) == [
        "torch 2.8.0 would be removed"
    ]
    assert versions.regressions(current, new, [], removing=["Torch"]) == []


def _refusing_setup(monkeypatch, switch_result=True):
    from seamm_manager import my, util

    current = FakeEnvironment({"seamm-exec": "2026.10.6.1"})
    current.exists = True
    new = FakeEnvironment({"seamm-exec": "2026.10.6.1"})
    new.path = SimpleNamespace(name="2026-10-06T14-00-00")
    monkeypatch.setattr(my, "uv", current)
    monkeypatch.setattr(my, "options", SimpleNamespace(in_place=False, force=False))
    monkeypatch.setattr(versions, "ensure_versioned", lambda: None)
    monkeypatch.setattr(versions, "build_version", lambda *a, **k: new)
    monkeypatch.setattr(util, "sync_manager", lambda: None)
    monkeypatch.setattr(versions, "switch", lambda *a, **k: switch_result)
    monkeypatch.setattr(versions, "refused", False)
    return new


def test_a_refused_switch_is_recorded(monkeypatch):
    """install and update exit non-zero when a change was built but not
    switched to, whether for a regression or processes using the link."""
    _refusing_setup(monkeypatch, switch_result=False)
    assert versions.apply_change(["mbe-step"]) is False
    assert versions.refused is True


def test_a_successful_switch_is_not_refused(monkeypatch):
    _refusing_setup(monkeypatch, switch_result=True)
    assert versions.apply_change(["mbe-step"]) is True
    assert versions.refused is False


def test_update_exits_non_zero_when_refused(monkeypatch):
    from seamm_manager import my
    from seamm_manager import update as update_module

    monkeypatch.setattr(
        my,
        "options",
        SimpleNamespace(all=False, modules=["mbe-step"], gui_only=False, latest=False),
    )
    monkeypatch.setattr(my, "uv", SimpleNamespace(exists=True))
    monkeypatch.setattr(my, "development", False, raising=False)
    monkeypatch.setattr(update_module, "package_info", lambda p: (None, None))
    monkeypatch.setattr(update_module, "update_packages", lambda *a, **k: None)
    monkeypatch.setattr(update_module, "installation_service_name", lambda n: n)
    import seamm_manager.apps
    import seamm_manager.flowcharts
    import seamm_manager.services

    monkeypatch.setattr(seamm_manager.apps, "refresh_apps", lambda: None)
    monkeypatch.setattr(seamm_manager.services, "refresh_service_bundles", lambda: None)
    monkeypatch.setattr(seamm_manager.flowcharts, "notice", lambda: None)

    monkeypatch.setattr(versions, "refused", True)
    assert update_module.update() == 1
    monkeypatch.setattr(versions, "refused", False)
    assert update_module.update() == 0
