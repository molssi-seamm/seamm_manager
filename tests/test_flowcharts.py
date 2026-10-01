# -*- coding: utf-8 -*-

"""seamm-manager flowcharts: finding job flowcharts still in format 2.0."""

from seamm_manager import flowcharts


def job(root, project, name, header):
    path = root / "Jobs" / "projects" / project / name
    path.mkdir(parents=True)
    (path / "flowchart.flow").write_text(f"#!/usr/bin/env run_flowchart\n{header}\n")


def test_old_job_flowcharts(tmp_path):
    job(tmp_path, "a", "Job_000001", "!MolSSI flowchart 2.0")
    job(tmp_path, "a", "Job_000002", "format: MolSSI flowchart 3.0")
    job(tmp_path, "b", "Job_000003", "!MolSSI flowchart 1.0")
    assert flowcharts.old_job_flowcharts(tmp_path) == 2
    assert flowcharts.old_job_flowcharts(tmp_path, stop_at=1) == 1


def test_nothing_without_jobs(tmp_path):
    assert flowcharts.old_job_flowcharts(tmp_path) == 0


def test_work_keys_are_the_plan_summary_keys():
    """The keys that mean there is something to convert must match seamm.migrate3."""
    import pytest

    migrate3 = pytest.importorskip("seamm.migrate3")
    import inspect

    source = inspect.getsource(migrate3)
    for key in flowcharts._WORK:
        assert f'"{key}"' in source, key
