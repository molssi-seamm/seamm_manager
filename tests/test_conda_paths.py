# -*- coding: utf-8 -*-
"""Where conda environments are found and made (e.g. a cluster's central conda)."""

from pathlib import Path

from seamm_manager.conda import Conda


def _conda(tmp_path, envs, envs_dirs):
    conda = Conda.__new__(Conda)  # no call to conda itself
    conda.root_path = tmp_path / "apps" / "Miniforge3"
    conda._data = {
        "envs": [str(e) for e in envs],
        "envs_dirs": [str(d) for d in envs_dirs],
    }
    return conda


def test_existing_environment_is_found_wherever_it_is(tmp_path):
    lammps = tmp_path / "projects" / "conda" / "envs" / "seamm-lammps"
    conda = _conda(tmp_path, [tmp_path / "apps" / "Miniforge3", lammps], [])
    assert conda._resolve_environment_path("seamm-lammps") == lammps


def test_new_environment_goes_in_the_first_writable_envs_dir(tmp_path):
    read_only = tmp_path / "apps" / "Miniforge3" / "envs"
    read_only.mkdir(parents=True)
    read_only.chmod(0o555)
    projects = tmp_path / "projects" / "conda" / "envs"  # made when needed
    try:
        conda = _conda(tmp_path, [], [read_only, projects])
        assert conda._resolve_environment_path("seamm-xnn") == projects / "seamm-xnn"
    finally:
        read_only.chmod(0o755)


def test_without_envs_dirs_the_base_installation_is_used(tmp_path):
    conda = _conda(tmp_path, [], [])
    assert conda._resolve_environment_path("seamm-xnn") == (
        tmp_path / "apps" / "Miniforge3" / "envs" / "seamm-xnn"
    )


def test_absolute_paths_are_used_as_given(tmp_path):
    conda = _conda(tmp_path, [], [])
    assert conda._resolve_environment_path(str(tmp_path / "x")) == Path(tmp_path / "x")
