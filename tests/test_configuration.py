#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `seamm_manager` package."""

from pathlib import Path

import pytest  # noqa: F401
import seamm_manager  # noqa: F401


def test_construction():
    """Just create an object and test its type."""
    result = seamm_manager.Configuration()
    assert str(type(result)) == (
        "<class 'seamm_manager.configuration.Configuration'>"  # noqa: E501
    )


def test_sections(seamm_conf):
    """Test getting the sections from the configuration file."""
    answer = [
        "default",
        "seamm",
        "dftbplus-step",
        "from-smiles-step",
        "lammps-step",
        "mopac-step",
        "packmol-step",
        "psi4-step",
    ]
    sections = seamm_conf.sections()
    if sections != answer:
        print(sections)
    assert sections == answer


def test_get_values(seamm_conf):
    """Get the values from a section."""
    answer = {"datastore": "/Users/psaxe/Jobs", "project": "dev"}
    values = seamm_conf.get_values("SEAMM")
    if values != answer:
        print(values)
    assert values == answer


def test_get_values_with_empty_value(seamm_conf):
    """Get the values from a section where some have no value."""
    answer = {
        "installation": "conda",
        "conda-environment": "seamm-lammps",
        "module": "",
        "lammps-path": "/Users/psaxe/opt/miniconda3/envs/seamm-lammps/bin",
    }
    values = seamm_conf.get_values("lammps-step")
    if values != answer:
        print(values)
    assert values == answer


def test_to_string(seamm_conf):
    answer = """\
[lammps-step]
# How many cores to use for LAMMPS.  Set to 1 to use only the serial
# version of LAMMPS. LAMMPS will try to choose a reasonable number of
# cores based on the size of the system and other parameters. The
# option 'lammps-atoms-per-core' can be used to tune this estimate.
#
# The default is 'available', meaning use all the cores available to
# the calculation if that makes sense based on the type of
# calculation. Otherwise you can give a number here. Note that the
# [DEFAULT] section may override the default.

# ncores = available

# The optimal number of atoms per core. You may wish to change this if
# you consistently use expensive potentials, or have e.g. GPUs. The
# default is 500.

# lammps-atoms-per-core = 500

# Information about where/how the executables are installed
# installation may be 'user', 'conda' or 'module'. If a module is
# specified it will be loaded and those executables used.  In this
# case, any path specified using lammps-path will be ignored.

installation = conda
conda-environment = seamm-lammps
module =

# The path to the executables. Can be empty or not present, in which
# case the default PATH is used.  If a path is given, lmp_serial and
# lmp_mpi from this location will be used. If mpiexec is also present
# it will be used; otherwise mpiexec from the normal PATH will be
# used. If mpiexec or lmp_mpi is not found, only the serial version of
# LAMMPS will be used. Conversely, if lmp_serial is not present,
# lmp_mpi will always be used, though possible on just one core for
# smaller calculations.
#
# Ignored if a module is used. The default is to use the PATH
# environment variable.

lammps-path = /Users/psaxe/opt/miniconda3/envs/seamm-lammps/bin

"""

    result = seamm_conf.to_string("lammps-step")
    if result != answer:
        print(result)
    assert result == answer


def test_set_value(seamm_conf):
    answer = """\
[lammps-step]
# How many cores to use for LAMMPS.  Set to 1 to use only the serial
# version of LAMMPS. LAMMPS will try to choose a reasonable number of
# cores based on the size of the system and other parameters. The
# option 'lammps-atoms-per-core' can be used to tune this estimate.
#
# The default is 'available', meaning use all the cores available to
# the calculation if that makes sense based on the type of
# calculation. Otherwise you can give a number here. Note that the
# [DEFAULT] section may override the default.

# ncores = available

# The optimal number of atoms per core. You may wish to change this if
# you consistently use expensive potentials, or have e.g. GPUs. The
# default is 500.

lammps-atoms-per-core = 1000

# Information about where/how the executables are installed
# installation may be 'user', 'conda' or 'module'. If a module is
# specified it will be loaded and those executables used.  In this
# case, any path specified using lammps-path will be ignored.

installation = conda
conda-environment = seamm-lammps
module =

# The path to the executables. Can be empty or not present, in which
# case the default PATH is used.  If a path is given, lmp_serial and
# lmp_mpi from this location will be used. If mpiexec is also present
# it will be used; otherwise mpiexec from the normal PATH will be
# used. If mpiexec or lmp_mpi is not found, only the serial version of
# LAMMPS will be used. Conversely, if lmp_serial is not present,
# lmp_mpi will always be used, though possible on just one core for
# smaller calculations.
#
# Ignored if a module is used. The default is to use the PATH
# environment variable.

lammps-path = /Users/psaxe/opt/miniconda3/envs/seamm-lammps/bin

"""

    seamm_conf.set_value("lammps-step", "lammps-atoms-per-core", "1000")
    result = seamm_conf.to_string("lammps-step")
    if result != answer:
        print(result)
    assert result == answer


def test_add_section(seamm_conf):
    text = """\
# This is a test section

value1 = 53
value2 = 54

# The end!
"""
    seamm_conf.add_section("test", text)
    assert seamm_conf.to_string("TEST") == "[test]\n" + text


def test_get_prolog(seamm_conf):
    """Test getting the prolog."""
    answer = """\
# Configuration options for SEAMM.
#
# The options in this file override any defaults in SEAMM
# and it plug-ins; however, command-line arguments will
# in turn override the values here.
#
# The keys may have either underscores '_' or dashes '-' separating
# words. In either case, the command line options is
# '--<key with dashes>' and the variable name inside SEAMM is
# '<key with underscores>', e.g. 'log_level' or 'log-level' are
# identical in this file. The command line key would be '--log-level'
# and the variable in SEAMM 'log_level'.
#
# The file is broken into sections, with a name in square brackets,
# like [lammps-step]. Within each section there can be a series of
# option = value statements. ';' or '#' introduce comment lines. The
# section names are case-sensitive but variables within sections are
# not.
#
# Two sections are special: [DEFAULT] and [global]. All other sections
# correspond to plug-ins in SEAMM, and generally have the form
# [xxxxx-step], in lowercase.
#
# [DEFAULT] provides default values for any other section. If an
# option is requested for a section, but does not exist in that
# section, the option is looked for in the [DEFAULT] section. If it
# exists there, the corresponding value is used.
#
# Finally, options can refer to options in the same or other sections
# with a syntax like ${section:option}. If the section is omitted, it
# looks in the current section and [DEFAULTS], in that
# order. Otherwise it looks in the given section and [DEFAULTS].
#
# The [SEAMM] section contains options for the SEAMM environment
# itself. On the command line these come before any options for
# plug-ins, which follow the name of the plug-in, which is the section
# in this file.

"""
    assert seamm_conf.get_prolog() == answer


def test_create_configuration(conf):
    """Test creating a configuration from scratch."""

    prolog = """\
This is a simple prolog.

"""
    section_data = """\
# This is a test section.

value1 = 53
value2 = 54
"""
    conf2 = seamm_manager.Configuration()
    conf2.add_prolog(prolog)
    conf2.add_section("TEST", section_data)

    assert str(conf2) == str(conf)
    assert conf2 == conf


def test_set_value_not_existing(conf):
    """Test setting a key that does no exist."""
    answer = """\
This is a simple prolog.

[TEST]
# This is a test section.

value1 = 53
value2 = 54
value3 = 55

"""
    conf.set_value("Test", "value3", 55)
    assert str(conf) == answer


def test_set_value_force(conf):
    """Test setting a key that does no exist, using force."""
    answer = """\
This is a simple prolog.

[TEST]
# This is a test section.

value1 = 53
value2 = 54

"""
    with pytest.raises(KeyError, match="'value3' not in section Test."):
        conf.set_value("Test", "value3", 55, strict=True)
    assert str(conf) == answer


def test_add_prolog_error(conf):
    """Test trying to overwrite the prolog."""
    with pytest.raises(KeyError, match="The prolog already exists."):
        conf.add_prolog("This will cause an error!")


def test_add_section_error(conf):
    """Test trying to overwrite a section."""
    with pytest.raises(KeyError, match="Section 'TEST' already exists."):
        conf.add_section("TEST", "This will cause an error!")


def test_exists():
    """Test the functionality for whether the file exists."""
    conf = seamm_manager.Configuration()
    assert not conf.file_exists()
    conf.path = "./does_not_exist.ini"
    assert not conf.file_exists()

    path = Path(__file__).resolve().parent
    conf.path = path / "data" / "seamm.ini"
    assert conf.file_exists()


def test_empty_prolog():
    """Test what happens when ther is no prolog."""
    conf = seamm_manager.Configuration()
    assert conf.get_prolog() == ""


def test_empty_configuration_to_string():
    """An empty configuration (a plug-in's .ini that does not exist yet) must
    serialize, not raise."""
    import seamm_manager

    conf = seamm_manager.Configuration()
    assert conf.to_string() == "\n"
    conf.from_string("")
    assert conf.to_string() == "\n"
