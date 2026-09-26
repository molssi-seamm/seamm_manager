#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Fixtures for testing the `seamm-manager` package."""

from pathlib import Path

import pytest

import seamm_manager

path = Path(__file__).resolve().parent
data_path = path / "data"


@pytest.fixture()
def seamm_conf():
    """Create a configuration initialized with seamm.ini."""
    return seamm_manager.Configuration(data_path / "seamm.ini")


@pytest.fixture()
def conf():
    """Create a simple configuration for scratch."""
    text = """\
This is a simple prolog.

[TEST]
# This is a test section.

value1 = 53
value2 = 54
"""
    conf = seamm_manager.Configuration()
    conf.from_string(text)
    return conf
