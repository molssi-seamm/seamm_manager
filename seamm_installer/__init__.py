# -*- coding: utf-8 -*-
"""Compatibility shim: ``seamm_installer`` is now ``seamm_manager``.

The plug-ins' own installers (``<plug-in>-step-installer``) subclass
``seamm_installer.InstallerBase``. Until each of them is released importing
``seamm_manager`` instead, this module keeps that import working inside a
seamm-manager environment. It is deliberately tiny: everything comes from
seamm_manager.
"""

from seamm_manager import Conda, Configuration, InstallerBase, Pip, my  # noqa: F401
from seamm_manager import __version__  # noqa: F401
