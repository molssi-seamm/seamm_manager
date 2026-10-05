# -*- coding: utf-8 -*-
"""PyTorch in a code environment: the build the machine needs, probing an
environment, judging it, and the installer's handling (seamm_manager#31)."""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from seamm_manager import torch_support as ts
from seamm_manager.installer_base import InstallerBase, environment_created_by_seamm


# ---------------------------------------------------------------- the target
def test_recommend_tag():
    assert ts.recommend_tag((13, 0)) == "cu130"
    assert ts.recommend_tag((12, 8)) == "cu128"
    assert ts.recommend_tag((12, 2)) == "cu128"  # ChemAI's 535 driver
    assert ts.recommend_tag((12, 1)) == "cu128"
    assert ts.recommend_tag((12, 0)) == "cu118"
    assert ts.recommend_tag((11, 8)) == "cu118"
    assert ts.recommend_tag((11, 4)) is None


def test_target_linux_gpu():
    t = ts.torch_target(system="Linux", driver=(12, 2))
    assert t["tag"] == "cu128"
    assert t["index_url"] == "https://download.pytorch.org/whl/cu128"
    assert ts.pip_index_args(t) == [
        "--index-url",
        "https://download.pytorch.org/whl/cu128",
        "--extra-index-url",
        "https://pypi.org/simple",
    ]


def test_target_linux_no_driver_is_undecided():
    t = ts.torch_target(system="Linux", driver=None)
    assert t["tag"] is None and t["index_url"] is None


def test_target_linux_old_driver_is_cpu():
    t = ts.torch_target(system="Linux", driver=(11, 2))
    assert t["tag"] == "cpu"
    assert t["index_url"].endswith("/cpu")


def test_target_mac_is_default_index():
    t = ts.torch_target(system="Darwin", driver=None)
    assert t["tag"] == "default" and t["index_url"] is None
    assert ts.pip_index_args(t) == []


def test_forced_tag_wins():
    t = ts.torch_target(forced="cu118", system="Linux", driver=(12, 8))
    assert t["tag"] == "cu118"
    assert "forced" in t["reason"]
    t = ts.torch_target(forced="auto", system="Linux", driver=(12, 8))
    assert t["tag"] == "cu128"


def test_detect_parses_nvidia_smi(monkeypatch):
    monkeypatch.setattr(ts.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(
        ts.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            stdout="| NVIDIA-SMI 535.104.05   Driver Version: 535.104.05   "
            "CUDA Version: 12.2 |"
        ),
    )
    assert ts.detect_cuda_driver() == (12, 2)
    monkeypatch.setattr(ts.shutil, "which", lambda name: None)
    assert ts.detect_cuda_driver() is None


# ---------------------------------------------------------------- the probe
def test_probe_script_runs_here():
    """The probe runs with this python (torch probably absent) and reports."""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-c", ts.probe_script(("json", "no_such_module_xyz"))],
        capture_output=True,
        text=True,
    ).stdout
    probe = ts.parse_probe(out)
    assert probe is not None
    assert probe["imports"]["json"] is True
    assert "No module" in probe["imports"]["no_such_module_xyz"]
    assert ts.parse_probe("garbage") is None


def _probe(**kw):
    p = {
        "torch": True,
        "torch_version": "2.13.0+cu126",
        "cuda_build": "12.6",
        "cuda_available": True,
        "mps_available": False,
        "device_count": 1,
        "imports": {},
    }
    p.update(kw)
    return p


def test_assess():
    gpu = ts.torch_target(system="Linux", driver=(12, 2))
    cpu_machine = ts.torch_target(system="Linux", driver=None)
    assert ts.assess(None, gpu)[0] == "unknown"
    assert ts.assess(_probe(torch=False), gpu)[0] == "missing"
    assert ts.assess(_probe(), gpu)[0] == "ok"
    s, note = ts.assess(_probe(cuda_available=False, device_count=0), gpu)
    assert s == "gpu-unusable" and "too old" in note
    s, _ = ts.assess(_probe(cuda_build=None, cuda_available=False), gpu)
    assert s == "cpu-on-gpu"
    # No GPU here: any torch is fine
    assert ts.assess(_probe(cuda_available=False), cpu_machine)[0] == "ok"
    assert (
        ts.assess(_probe(cuda_build=None, cuda_available=False), cpu_machine)[0] == "ok"
    )


# ------------------------------------------------- who made the environment
def _env(tmp_path, cmd):
    prefix = tmp_path / "env"
    meta = prefix / "conda-meta"
    meta.mkdir(parents=True)
    (meta / "history").write_text(
        f"==> 2026-06-19 16:58:38 <==\n# cmd: {cmd}\n# conda version: 24.11.3\n"
        "+conda-forge/noarch::pip-26.1.2-pyh8b19718_0\n"
    )
    return prefix


def test_created_by_seamm(tmp_path):
    ours = _env(tmp_path / "a", "/x/conda env create --file seamm-mopac.yml")
    assert environment_created_by_seamm(ours) is True
    ours2 = _env(
        tmp_path / "b",
        "/x/conda env create --file /tmp/seamm-env-k2/seamm-xnn.yml --prefix /e/x",
    )
    # The stripped copy a torch-managed install creates from keeps the file's name
    assert environment_created_by_seamm(ours2) is True
    tmpname = _env(tmp_path / "d", "/x/conda env create --file /tmp/tmpab12.yml")
    assert environment_created_by_seamm(tmpname) is False
    hand = _env(tmp_path / "c", "/x/conda create -n seamm-lammps-xnndev python=3.12")
    assert environment_created_by_seamm(hand) is False
    assert environment_created_by_seamm(tmp_path / "nowhere") is None


def _installer(tmp_path, envs):
    """An InstallerBase with a fake conda knowing ``envs`` {name: prefix}."""
    inst = InstallerBase.__new__(InstallerBase)
    inst.logger = logging.getLogger("test")
    inst.environment = "seamm-xnn"
    inst.section = "xnn-step"
    inst.options = SimpleNamespace(torch_tag=None)
    inst._conda = SimpleNamespace(
        exists=lambda name: name in envs,
        path=lambda name: envs[name],
    )
    return inst


def test_not_ours(tmp_path):
    hand = _env(tmp_path / "hand", "/x/conda create -n seamm-lammps-xnndev python=3.12")
    # ... even with the records a mistaken update left behind
    (hand / "conda-meta" / "seamm-xnn-step.sha256").write_text("abc\n")
    ours = _env(tmp_path / "ours", "/x/conda env create --file seamm-lammps.yml")
    nohist = tmp_path / "nohist"
    (nohist / "conda-meta").mkdir(parents=True)
    (nohist / "conda-meta" / "seamm-lammps-step.sha256").write_text("abc\n")
    envs = {
        "seamm-lammps-xnndev": hand,
        "seamm-lammps": ours,
        "old": nohist,
        "seamm-xnn": tmp_path / "own",
    }
    inst = _installer(tmp_path, envs)
    assert inst._not_ours("seamm-lammps-xnndev") is True
    assert inst._not_ours("seamm-lammps") is False
    assert inst._not_ours("old") is False  # no history: the records decide
    assert inst._not_ours("seamm-xnn") is False  # SEAMM's own name
    assert inst._not_ours("absent") is False


# ---------------------------------------------------------------- the flow
class FakeConda:
    def __init__(self, probes):
        self.probes = list(probes)  # successive probe results
        self.calls = []

    def run_python(self, environment, script, timeout=600):
        import json

        probe = self.probes.pop(0)
        return None if probe is None else "PROBE " + json.dumps(probe)

    def pip_install(self, environment, requirements, upgrade=False, index_args=()):
        self.calls.append(("pip", list(requirements), upgrade, list(index_args)))

    def update_environment(self, environment_file, name=None, index_args=(), **kw):
        self.calls.append(("apply", name, list(index_args)))


def _flow(monkeypatch, probes, driver=(12, 2), torch_tag=None, system="Linux"):
    inst = InstallerBase.__new__(InstallerBase)
    inst.logger = logging.getLogger("test")
    inst.environment = "seamm-xnn"
    inst.section = "xnn-step"
    inst.environment_file = Path("/x/seamm-xnn.yml")
    inst.torch_managed = True
    inst.torch_imports = ("torch", "xnn")
    inst.options = SimpleNamespace(torch_tag=torch_tag)
    inst._exe_config = SimpleNamespace(get_values=lambda s: {"torch-build": "auto"})
    inst._conda = FakeConda(probes)
    inst._record_applied = lambda env: None
    monkeypatch.setattr(ts, "detect_cuda_driver", lambda: driver)
    monkeypatch.setattr(ts.platform, "system", lambda: system)
    monkeypatch.delenv("SEAMM_REFRESH_CODES", raising=False)
    return inst


def test_missing_torch_is_installed_from_the_right_index(monkeypatch, capsys):
    ok = _probe(imports={"torch": True, "xnn": True})
    inst = _flow(monkeypatch, [_probe(torch=False), ok])
    assert inst._ensure_torch("seamm-xnn") is True
    pip, apply = inst.conda.calls
    assert pip[1] == ["torch"] and pip[2] is False
    assert pip[3][1] == "https://download.pytorch.org/whl/cu128"
    assert apply[2] == pip[3]  # the file's pip part on the same index
    assert "Installing torch" in capsys.readouterr().out


def test_working_torch_is_left_alone(monkeypatch):
    ok = _probe(imports={"torch": True, "xnn": True})
    inst = _flow(monkeypatch, [ok, ok])
    assert inst._ensure_torch("seamm-xnn") is True
    assert [c[0] for c in inst.conda.calls] == ["apply"]


def test_unusable_torch_is_not_replaced_silently(monkeypatch, capsys):
    bad = _probe(cuda_available=False, device_count=0, imports={"torch": True})
    inst = _flow(monkeypatch, [bad])
    assert inst._ensure_torch("seamm-xnn") is False
    assert inst.conda.calls == []  # nothing applied either
    out = capsys.readouterr().out
    assert "left as it is" in out and "--torch-tag cu128" in out


def test_unusable_torch_is_replaced_when_asked(monkeypatch):
    bad = _probe(cuda_available=False, device_count=0)
    ok = _probe(imports={"torch": True, "xnn": True})
    inst = _flow(monkeypatch, [bad, ok], torch_tag="cu128")
    assert inst._ensure_torch("seamm-xnn") is True
    pip = inst.conda.calls[0]
    assert pip[0] == "pip" and pip[2] is True  # --upgrade: a replacement


def test_no_driver_and_no_torch_asks_for_a_decision(monkeypatch, capsys):
    inst = _flow(monkeypatch, [_probe(torch=False)], driver=None)
    assert inst._ensure_torch("seamm-xnn") is False
    assert inst.conda.calls == []
    assert "torch-build = <tag>" in capsys.readouterr().out


def test_no_driver_with_forced_cpu_installs(monkeypatch):
    ok = _probe(
        cuda_build=None, cuda_available=False, imports={"torch": True, "xnn": True}
    )
    inst = _flow(monkeypatch, [_probe(torch=False), ok], driver=None, torch_tag="cpu")
    assert inst._ensure_torch("seamm-xnn") is True
    assert inst.conda.calls[0][3][1].endswith("/cpu")


def test_failed_import_after_apply_is_reported(monkeypatch, capsys):
    ok = _probe(imports={"torch": True, "xnn": "No module named 'xnn'"})
    inst = _flow(monkeypatch, [ok, ok])
    assert inst._ensure_torch("seamm-xnn") is False
    assert "xnn: No module" in capsys.readouterr().out


def test_mac_uses_pypi(monkeypatch):
    ok = _probe(
        cuda_build=None,
        cuda_available=False,
        mps_available=True,
        imports={"torch": True, "xnn": True},
    )
    inst = _flow(monkeypatch, [_probe(torch=False), ok], driver=None, system="Darwin")
    assert inst._ensure_torch("seamm-xnn") is True
    assert inst.conda.calls[0][3] == []  # plain PyPI


@pytest.mark.parametrize("flag", ["install", "update"])
def test_torch_tag_option_exists(flag, monkeypatch):
    monkeypatch.setattr("sys.argv", ["x", flag, "--torch-tag", "cu128"])
    inst = InstallerBase.__new__(InstallerBase)
    inst.logger = logging.getLogger("test")
    inst.subparser = {}
    inst.setup_parser()
    assert inst.options.torch_tag == "cu128"


def test_conda_only_create_keeps_the_file_name(tmp_path):
    from seamm_manager.conda import Conda

    f = tmp_path / "seamm-xnn.yml"
    f.write_text(
        "name: seamm-xnn\nchannels: [conda-forge]\n"
        "dependencies:\n  - python=3.12\n  - pip:\n    - torch\n"
    )
    calls = []
    conda = Conda.__new__(Conda)
    conda.conda_exe = "/fake/conda"
    conda.logger = logging.getLogger("test")
    conda._resolve_environment_path = lambda name: Path("/envs") / name
    conda._execute = lambda command, **kw: calls.append(command)
    conda.create_environment(f, name="seamm-xnn", conda_only=True)
    (command,) = calls
    used = Path(command.split("--file '")[1].split("'")[0])
    assert used.name == "seamm-xnn.yml" and used != f
    assert "torch" not in used.read_text()
