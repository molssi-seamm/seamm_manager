# -*- coding: utf-8 -*-

"""Metadata about packages, etc."""

core_packages = (
    "molsystem",
    "reference-handler",
    "seamm",
    "seamm-datastore",
    "seamm-ff-util",
    "seamm-manager",
    "seamm-jobserver",
    "seamm-thermochemistry",
    "seamm-util",
    "seamm-widgets",
)
molssi_plug_ins = (
    "control-parameters-step",
    "crystal-builder-step",
    "custom-step",
    "dftbplus-step",
    "forcefield-step",
    "geometry-analysis-step",
    "from-smiles-step",
    "gaussian-step",
    "lammps-step",
    "loop-step",
    "mopac-step",
    "nwchem-step",
    "packmol-step",
    "psi4-step",
    "qcarchive-step",
    "quickmin-step",
    "rdkit-step",
    "read-structure-step",
    "set-cell-step",
    "strain-step",
    "supercell-step",
    "table-step",
    "thermal-conductivity-step",
)
external_plug_ins = []
# Packages that install()/services.py handle directly (their own dedicated
# Conda environment, not the shared main one; no Zenodo package-registry
# entry) rather than through the generic install_packages()/per-package
# Installer machinery. See install.py's install_seamm_webui().
standalone_packages = ("seamm-webui",)

excluded_plug_ins = (
    "chemical-formula",
    "cms-plots",
    "seamm-dashboard-client",
    "seamm-cookiecutter",
    "cassandra-step",
    "solvate-step",
)
# The development tooling comes from the published package list
# (my.package_metadata["development packages"]); these are only the fallback
# if the list lacks it.
development_packages = (
    "black",
    "build",
    "codecov",
    "flake8",
    "pytest",
    "pytest-cov",
    "sphinx",
    "sphinx-copybutton",
    "sphinx-design",
    "pydata-sphinx-theme",
    "twine",
)
