# -*- coding: utf-8 -*-
"""The comparison harness: tolerant comparison of two result trees."""

import json
from types import SimpleNamespace

import pytest

from seamm_manager import compare, my
from seamm_manager.uv import Uv


def test_json_tolerance_and_volatile_keys():
    a = {
        "energy": 1.0000000,
        "elapsed time": 3.2,
        "n": 3,
        "items": [1.0, 2.0],
        "s": "x",
    }
    b = {
        "energy": 1.0000005,
        "elapsed time": 9.9,
        "n": 3,
        "items": [1.0, 2.0],
        "s": "x",
    }
    assert compare.compare_json(a, b, 1e-6, 1e-9) == []
    b["energy"] = 1.001
    b["items"] = [1.0, 2.5]
    diffs = compare.compare_json(a, b, 1e-6, 1e-9)
    assert any("/energy" in d for d in diffs) and any("/items[1]" in d for d in diffs)
    # Numeric strings compare as numbers; booleans do not become numbers
    assert compare.compare_json({"v": "1.0e-3"}, {"v": "0.001"}, 1e-9, 0) == []
    assert compare.compare_json({"v": True}, {"v": 1}, 1e-9, 0) != []
    assert compare.compare_json({"k": 1}, {"j": 1}, 1e-9, 0) == [
        "/j: only in b",
        "/k: only in a",
    ]


def test_csv():
    a = "name,E\nwater,-53.123456\n"
    b = "name,E\nwater,-53.123457\n"
    assert compare.compare_csv(a, b, 1e-6, 1e-9) == []
    assert compare.compare_csv(a, b, 1e-9, 0) == [
        "row 1 col 1: -53.123456 vs -53.123457"
    ]
    assert compare.compare_csv(a, a + "x,1\n", 1e-6, 0) == ["2 vs 3 rows"]


def test_numeric_text():
    a = "3\nwater\nO 0.0 0.0 0.1\nH 0.7 0.0 -0.4\n"
    b = "3\nwater\nO 0.0 0.0 0.10000001\nH 0.7 0.0 -0.4\n"
    assert compare.compare_numeric_text(a, b, 1e-6, 1e-9) == []
    b = b.replace("H 0.7", "H 0.8")
    assert compare.compare_numeric_text(a, b, 1e-6, 1e-9) == ["line 4: 0.7 vs 0.8"]


def test_text_normalization():
    a = "Energy = -53.1\nElapsed time: 0:00:45.0\n"
    a += "Friday 2026.10.02 14:31:03\nrun in /w/a/x\n"
    b = "Energy = -53.1\nElapsed time: 0:01:02.3\n"
    b += "Monday 2026.10.05 09:00:00\nrun in /w/b/x\n"
    assert compare.compare_text(a, b, (("/w/a", "<WORK>"), ("/w/b", "<WORK>"))) == []
    b = b.replace("-53.1", "-53.2")
    diff = compare.compare_text(a, b, (("/w/a", "<WORK>"), ("/w/b", "<WORK>")))
    assert diff == ["-Energy = -53.1", "+Energy = -53.2"]


def test_mopac_timing_lines_and_job_data_header(tmp_path):
    a = "          WALL-CLOCK TIME         =      0.008 SECONDS\n"
    a += " CPU_TIME:SEC=+0.78D-02\n"
    a += (
        " CPU_TIME:SECONDS[1]=        0.01\n TOTAL JOB TIME:             0.01 SECONDS\n"
    )
    a += " HEAT OF FORMATION = -57.8 KCAL/MOL\n"
    b = (
        a.replace("0.008", "0.027")
        .replace("0.78D-02", "0.27D-01")
        .replace("0.01", "0.04")
    )
    assert compare.compare_text(a, b) == []
    assert compare.compare_text(a, b.replace("-57.8", "-57.9")) != []
    path = tmp_path / "job_data.json"
    path.write_text('!MolSSI job_data 1.0\n{"state": "finished", "time": 1}\n')
    assert compare._load_json(path) == {"state": "finished", "time": 1}
    path.write_text('{"command line": ["x", "/r/A/Jobs"], "E": 1}')
    assert compare._load_json(path, (("/r/A", "<ROOT>"),)) == {
        "command line": ["x", "<ROOT>/Jobs"],
        "E": 1,
    }
    # A job's uuid differs every run
    assert (
        compare.compare_json({"uuid": "a", "E": 1}, {"uuid": "b", "E": 1}, 0, 0) == []
    )


def test_compare_trees(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        (d / "1").mkdir(parents=True)
        (d / "job.out").write_text(
            f"Running in '{d}'\nE = 1.0\nElapsed time: 1:00:00\n"
        )
        (d / "1" / "Results.json").write_text(json.dumps({"E": 1.0, "time": str(d)}))
        (d / "t.csv").write_text("x\n1.0\n")
        (d / "s.xyz").write_text("1\n\nO 0 0 0\n")
        (d / "blob.bin").write_bytes(b"\0\1\2")
    (b / "1" / "Results.json").write_text(json.dumps({"E": 1.0000001, "time": "z"}))
    (b / "t.csv").write_text("x\n2.0\n")
    (a / "only_a.txt").write_text("x\n")
    (b / "harness_run.log").write_text("ignored\n")

    results = {str(r): (s, d) for r, s, d in compare.compare_trees(a, b)}
    assert results["job.out"][0] == "within tolerance"  # the directory differs
    assert results["1/Results.json"][0] == "within tolerance"
    assert results["t.csv"][0] == "different"
    assert results["s.xyz"][0] == "identical"
    assert results["blob.bin"][0] == "not compared"
    assert results["only_a.txt"][0] == "only in a"
    assert "harness_run.log" not in results
    assert compare.report(compare.compare_trees(a, b)) is False
    (b / "t.csv").write_text("x\n1.0\n")
    (a / "only_a.txt").unlink()
    assert compare.report(compare.compare_trees(a, b)) is True
    # One root a prefix of the other: the longer is replaced first
    (a / "r.json").write_text('{"command line": ["/u/SEAMM"]}')
    (b / "r.json").write_text('{"command line": ["/u/SEAMM_DEV"]}')
    roots = (("/u/SEAMM", "<ROOT>"), ("/u/SEAMM_DEV", "<ROOT>"))
    results = {str(r): s for r, s, _ in compare.compare_trees(a, b, replacements=roots)}
    assert results["r.json"] == "within tolerance"


def test_resolve_environment(tmp_path, monkeypatch):
    root = tmp_path / "SEAMM"
    for name in ("2026-09-01T00-00-00", "2026-09-02T00-00-00"):
        d = root / "venvs" / name / "bin"
        d.mkdir(parents=True)
        (d / "run_flowchart").write_text("#!x\n")
        (d.parent / "pyvenv.cfg").write_text("")
    (root / "venv").symlink_to("venvs/2026-09-02T00-00-00", target_is_directory=True)
    monkeypatch.setattr(my, "uv", Uv(root))

    assert compare.resolve_environment("current") == (
        root / "venvs" / "2026-09-02T00-00-00",
        root,
    )
    assert compare.resolve_environment("newest")[0].name == "2026-09-02T00-00-00"
    assert compare.resolve_environment("previous")[0].name == "2026-09-01T00-00-00"
    assert (
        compare.resolve_environment("2026-09-01T00-00-00")[0].name
        == "2026-09-01T00-00-00"
    )
    # Another installation, by root, and an environment by path
    other = tmp_path / "OTHER"
    (other / "venv" / "bin").mkdir(parents=True)
    (other / "venv" / "bin" / "run_flowchart").write_text("")
    assert compare.resolve_environment(str(other)) == (
        (other / "venv").resolve(),
        other,
    )
    env, r = compare.resolve_environment(str(root / "venvs" / "2026-09-01T00-00-00"))
    assert r == root
    with pytest.raises(ValueError):
        compare.resolve_environment("nonsense")


def test_compare_command_same_environment(tmp_path, monkeypatch, capsys):
    root = tmp_path / "SEAMM"
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "run_flowchart").write_text("")
    flow = tmp_path / "x.flow"
    flow.write_text("")
    monkeypatch.setattr(my, "uv", Uv(root))
    monkeypatch.setattr(
        my,
        "options",
        SimpleNamespace(
            flowchart=str(flow),
            a="current",
            b=str(root),
            work=None,
            keep=False,
            rtol=1e-6,
            atol=1e-9,
            no_run=True,
            args=[],
        ),
    )
    assert compare.compare() == 1
    assert "same environment" in capsys.readouterr().out
