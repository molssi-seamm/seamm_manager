# -*- coding: utf-8 -*-
"""Applying an environment file must not upgrade a bare pip requirement such as
torch, while requirements with a version specifier are kept current."""

import logging
from pathlib import Path

from seamm_manager.conda import Conda, split_environment_file

XNN_YML = """\
name: seamm-xnn
channels:
  - conda-forge
dependencies:
  - python=3.12
  - pip
  - pymdi          # provides `import mdi` for the MDI engine
  - pip:
    - torch
    - e3nn==0.4.4
    - xnns>=0.3.0
    - --extra-index-url https://example.invalid/simple
"""


def _conda(calls):
    conda = Conda.__new__(Conda)
    conda.conda_exe = "/fake/conda"
    conda.logger = logging.getLogger("test")
    conda._resolve_environment_path = lambda name: Path("/envs") / name
    conda._execute = lambda command, **kw: calls.append(command)
    return conda


def test_split(tmp_path):
    f = tmp_path / "env.yml"
    f.write_text(XNN_YML)
    conda_text, bare, specified = split_environment_file(f)
    assert bare == ["torch"]
    assert specified == ["e3nn==0.4.4", "xnns>=0.3.0"]
    assert "pip" not in conda_text.replace("- pip\n", "")
    assert "pymdi" in conda_text and "torch" not in conda_text


def test_update_environment_commands(tmp_path):
    f = tmp_path / "env.yml"
    f.write_text(XNN_YML)
    calls = []
    _conda(calls).update_environment(f, name="seamm-lammps")
    assert len(calls) == 3
    assert calls[0].startswith("'/fake/conda' env update --file")
    assert "--prefix '/envs/seamm-lammps'" in calls[0]
    assert calls[1] == "'/fake/conda' run -p '/envs/seamm-lammps' pip install 'torch'"
    assert calls[2] == (
        "'/fake/conda' run -p '/envs/seamm-lammps' pip install --upgrade "
        "'e3nn==0.4.4' 'xnns>=0.3.0'"
    )


def test_conda_policy_unchanged(tmp_path):
    f = tmp_path / "env.yml"
    f.write_text(XNN_YML)
    calls = []
    _conda(calls).update_environment(f, name="x", pip_policy="conda")
    assert len(calls) == 1 and str(f) in calls[0]
