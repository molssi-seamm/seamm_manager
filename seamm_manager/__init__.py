# -*- coding: utf-8 -*-

"""
seamm_manager
The installer/updater for SEAMM.
"""

# Bring up the classes so that they appear to be directly in
# the seamm_manager package.

from seamm_manager.conda import Conda, find_conda  # noqa: F401
from seamm_manager.configuration import Configuration  # noqa: F401
from seamm_manager.installer_base import InstallerBase  # noqa: F401
from seamm_manager import torch_support  # noqa: F401
from . import my  # noqa: F401
from seamm_manager.pip import Pip  # noqa: F401
from seamm_manager.uv import Uv, find_uv  # noqa: F401
import seamm_manager.my  # noqa: F401

# Handle versioneer
from ._version import get_versions

__author__ = """Paul Saxe"""
__email__ = "psaxe@molssi.org"
versions = get_versions()
__version__ = versions["version"]
__git_revision__ = versions["full-revisionid"]
del get_versions, versions
