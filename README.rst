=============
SEAMM Manager
=============

| |pull| |CI| |docs| |coverage| |lgtm| |PyUp|
| |Release| |PyPi|

Installs, updates and configures SEAMM (the Simulation Environment for Atomistic and
Molecular Simulations) in a uv-managed Python environment.

* Free software: GNU Lesser General Public License v3+
* Documentation: https://molssi-seamm.github.io/seamm_manager/index.html

.. |pull| image:: https://img.shields.io/github/issues-pr-raw/molssi-seamm/seamm_manager
   :target: https://github.com/molssi-seamm/seamm_manager/pulls
   :alt: GitHub pull requests

.. |CI| image:: https://github.com/molssi-seamm/seamm_manager/workflows/CI/badge.svg
   :target: https://github.com/molssi-seamm/seamm_manager/actions?query=workflow%3ACI
   :alt: CI status

.. |docs| image:: https://github.com/molssi-seamm/seamm_manager/workflows/Documentation/badge.svg
   :target: https://github.com/molssi-seamm/seamm_manager/actions?query=workflow%3ADocumentation
   :alt: Documentation Status

.. |coverage| image:: https://codecov.io/gh/molssi-seamm/seamm_manager/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/molssi-seamm/seamm_manager
   :alt: Code coverage

.. |lgtm| image:: https://img.shields.io/lgtm/grade/python/g/molssi-seamm/seamm_manager.svg?logo=lgtm&logoWidth=18
   :target: https://lgtm.com/projects/g/molssi-seamm/seamm_manager/context:python
   :alt: Code Quality

.. |PyUp| image:: https://pyup.io/repos/github/molssi-seamm/seamm_manager/shield.svg
   :target: https://pyup.io/repos/github/molssi-seamm/seamm_manager/
   :alt: Updates for requirements

.. |Release| image:: https://github.com/molssi-seamm/seamm_manager/workflows/Release/badge.svg
   :target: https://github.com/molssi-seamm/seamm_manager/actions?query=workflow%3ARelease
   :alt: CI status for releases

.. |PyPi| image:: https://img.shields.io/pypi/v/seamm_manager.svg
   :target: https://pypi.python.org/pypi/seamm_manager
   :alt: Release version

Features
--------

* **One environment, all from PyPI.** SEAMM and every plug-in are installed into a
  Python virtual environment under the SEAMM root (``~/SEAMM/venv``) with `uv`_,
  constrained to a published lock file, so every installation gets the same
  known-good set of versions and installs in seconds.
* **The interpreter comes with it.** ``uv`` installs Python (with Tk for the
  graphical editor); no conda, no system Python needed for SEAMM itself.
* **Conda only for the codes.** External programs (MOPAC, Psi4, DFTB+, LAMMPS, ...)
  are installed by their plug-ins into their own conda environments, exactly as
  before; conda is only needed if you install one of those plug-ins.
* Services (the JobServer and the web interface), desktop apps, and the datastore are
  set up and kept current by the same tool.

Getting started
---------------

.. code-block:: bash

    curl -LsSf https://astral.sh/uv/install.sh | sh    # once, if you do not have uv
    uv tool install seamm-manager
    seamm-manager install --all

That creates ``~/SEAMM``, the environment inside it, and installs SEAMM with all the
MolSSI plug-ins. ``seamm-manager update --all`` keeps everything current; without any
arguments ``seamm-manager`` opens a graphical installer.

Coming from seamm-installer
---------------------------

``seamm-manager`` replaces ``seamm-installer``, which managed a conda environment.
Existing conda-based installations keep working but no longer receive updates. To
move: run the three lines above, then ``seamm-manager services create`` and
``seamm-manager apps create`` to point the JobServer, web interface and desktop apps
at the new environment. Your jobs, configuration files and the codes' own conda
environments are untouched. Remove the old conda environment when you are happy.

.. _uv: https://docs.astral.sh/uv/

Acknowledgements
----------------

This package is based on ``seamm-installer``, and was developed by the Molecular
Sciences Software Institute (MolSSI_), which receives funding from the `National
Science Foundation`_ under awards OAC-1547580 and CHE-2136142.

.. _MolSSI: https://www.molssi.org
.. _`National Science Foundation`: https://www.nsf.gov
