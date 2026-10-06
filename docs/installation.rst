.. highlight:: shell

============
Installation
============

SEAMM Manager is the one tool you install by hand; it installs everything else.

1. Install ``uv`` if you do not have it. It is a single binary with no dependencies:

   .. code-block:: console

       $ curl -LsSf https://astral.sh/uv/install.sh | sh

   then open a new shell (or ``source ~/.local/bin/env``) so ``uv`` is on your path.
   On a cluster, do this in your own account; no administrator access is needed.

2. Install the manager as a uv *tool*, i.e. in its own small environment, outside
   the one it will manage:

   .. code-block:: console

       $ uv tool install seamm-manager

3. Install SEAMM:

   .. code-block:: console

       $ seamm-manager install --all

   This creates the SEAMM root (``~/SEAMM`` by default; ``--root`` chooses another),
   installs Python 3.12 and a virtual environment ``~/SEAMM/venv`` inside it, and
   installs SEAMM with all the MolSSI plug-ins from PyPI, constrained to the
   published lock file so the versions are a tested set. Add ``--third-party`` for
   the third-party plug-ins, or name individual plug-ins instead of ``--all``.

The installation also creates the jobs database (the *datastore*) under
``~/SEAMM/Jobs`` with an administrator account ``admin`` whose password is ``admin``;
change it from the web interface once that is running. Running a flowchart locally
with ``run_flowchart`` needs no account at all.

Optional: ``seamm-manager services create jobserver`` sets up the JobServer to run
in the background, ``seamm-manager install seamm-webui`` and ``... services create
webui`` the web interface, and ``seamm-manager apps create`` desktop apps for the
flowchart editor.

Updating
--------

.. code-block:: console

    $ seamm-manager update --all

updates the manager itself (if PyPI has a newer release), every installed SEAMM package
(to the versions in the current lock file), and restarts the JobServer if it needs to
be. If the installation has the web interface (its own environment, ``venv-webui``), it
is updated to the newest release on PyPI too, and its service restarted when anything
in it changed; ``update seamm-webui`` updates just the web interface. ``--no-constraints``
ignores the lock and takes the newest releases. ``--latest`` also asks PyPI directly, so
a release made today is picked up rather than waiting for the nightly list.

If the installation still has job flowcharts in the old format 2.0 and the updated SEAMM
can convert them, ``update`` ends with a short notice saying so. It never converts them
itself. Once a scan (or ``flowcharts migrate``) finds none left, that is recorded in
``<root>/installation.ini`` and later updates skip the scan, which on a cluster with
many jobs takes minutes; ``flowcharts status`` always scans and refreshes the record.

Converting the flowcharts to format 3.0
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

SEAMM 2026.10 introduced flowchart format 3.0. To convert an installation's job
flowcharts, and the jobs database's record of them, after updating:

.. code-block:: console

    $ seamm-manager flowcharts status     # how many are still in format 2.0
    $ seamm-manager flowcharts migrate

``migrate`` first shows what it would change and asks for confirmation. It then stops
the JobServer and web interface, backs up the jobs database, renames each job's original
flowchart to ``flowchart.v2.flow`` (unchanged) beside the new ``flowchart.flow``,
converts the database, restarts the services, and says where the backup and the manifest
of file changes are. Back up the ``Jobs`` directory first. ``--dry-run`` stops after the
report; ``--yes`` skips the question.

Moving the jobs database aside and letting the web interface rebuild it is *not* a
conversion: the rebuilt database keeps no accounts and converts nothing.
``seamm-manager datastore rebuild`` keeps the accounts and job owners, but converts
nothing either.

`Upgrading to flowchart format 3.0 <https://molssi-seamm.github.io/getting_started/installation/upgrading_format3.html>`_, in the main SEAMM documentation, is the
step-by-step guide, including the messages you may see, how to undo the conversion,
and how to convert your own flowcharts.

The environment
---------------

Everything Python lives in ``~/SEAMM/venv``. You never need to activate it; the
manager, the services and the apps all use its interpreter directly.

The environment is *versioned*: ``~/SEAMM/venv`` is a link to the current version,
which lives in ``~/SEAMM/venvs/<date and time>``. An update never changes the
environment that running jobs are using. Instead it builds a new version beside the
current one, from a copy of the current one plus the changes, and switches the link
when it is done; the services are restarted so they run from the new version, and
jobs that were already running finish in the old one. The first update with this
manager moves an existing ``venv`` directory into ``venvs/`` itself, which is safe
while jobs run.

.. code-block:: console

    $ seamm-manager environment versions     # the versions, and what uses them
    $ seamm-manager environment rollback     # back to the previous version
    $ seamm-manager environment prune        # remove old, unused versions

``prune`` keeps the current version, the newest two for ``rollback``, anything
younger than a day and anything a running process uses. A switch is refused, and the
new version left ready for ``environment switch``, if a process started *through* the
link, for example a job begun before the environment was versioned, is still running;
``--force`` switches anyway. ``update --in-place`` and ``install --in-place`` change
the current environment directly, as earlier versions of the manager did; do that only
when no jobs are running.

If the environment is ever damaged,

.. code-block:: console

    $ seamm-manager environment recreate

builds a fresh version from scratch with the SEAMM packages that were in it, in well
under a minute, and switches to it. ``environment show`` describes the environment.

To check a new version before switching to it, run a flowchart in both:

.. code-block:: console

    $ seamm-manager compare my.flow -a current -b newest

runs the flowchart with each version and compares every file the two runs produce
(numbers within a tolerance, timestamps and the like ignored); see ``compare --help``
for the other things a side can be, such as another installation's root.

Conda
-----

Conda is **not** needed for SEAMM itself. The plug-ins for external codes -- MOPAC,
Psi4, DFTB+, LAMMPS, xTB, Packmol, ... -- install the code into a conda environment of
its own, so conda (Miniforge is recommended) is needed on a machine where you install
one of those. The plug-in's installer tells you if it is missing.

The environments go where conda keeps them: an existing one is used wherever it is,
and a new one goes in the first writable directory of conda's ``envs_dirs`` (set in
``~/.condarc``), as ``conda create -n`` would put it. So a conda provided centrally on
a cluster, whose own directories are read-only, works too. SEAMM's own environment
never uses conda's Python, even when a conda environment is active.

When a plug-in updates its code environment from its environment file, pip
packages named without a version are installed only if missing and otherwise left
as they are, while those with a version specifier are kept current within it.

A plug-in whose code needs PyTorch (xnn-step) installs torch itself rather than
from its environment file, because PyPI's default torch bundles the newest CUDA
runtime, which an older NVIDIA driver cannot run -- torch then silently uses the
CPU. The installer reads the driver's CUDA version from ``nvidia-smi``, installs
torch from the matching PyTorch index (and the environment's other pip packages
from that index too), and checks afterwards that torch sees the GPU and the code
imports. A torch that works is never replaced, and one that does not -- perhaps a
build you made on purpose -- only when you ask. On a machine without a driver,
such as a cluster's login node whose compute nodes have the GPUs, it cannot tell
which build is wanted and says so; choose one with ``torch-build = <tag>`` in the
plug-in's ``.ini`` file (``cu128`` for a current driver, ``cpu`` for no GPU,
``auto`` to detect), or run the plug-in's installer with ``--torch-tag``, e.g.
``~/SEAMM/venv/bin/xnn-step-installer install --torch-tag cu128``, which also
replaces a torch that cannot use the GPU.

An environment that SEAMM did not create -- one you built by hand and named in a
plug-in's ``.ini`` file -- is left alone. Whether SEAMM created it is read from
conda's own history of the environment.

Licensed codes -- ORCA, Gaussian, VASP, FHI-aims -- are not installed at all: you
install them yourself. Installing their plug-in writes a commented template,
``~/SEAMM/<code>.ini`` (e.g. ``vasp.ini``), for you to edit to say where the code is
and how to run it. An existing file is never changed.

Migrating from seamm-installer
------------------------------

``seamm-installer`` managed SEAMM in a conda environment. Such an installation keeps
working, but it reads a frozen package list and no longer receives updates. To move
to the manager: follow the three steps above, then

.. code-block:: console

    $ seamm-manager services create jobserver     # if you ran the JobServer
    $ seamm-manager apps create                   # if you had desktop apps

so they use the new environment. Jobs, ``~/SEAMM/*.ini`` configuration and the codes'
conda environments are shared and untouched. Once satisfied, remove the old conda
environment (``conda env remove -n seamm``).

Development installation
------------------------

.. code-block:: console

    $ seamm-manager --development install --all development

uses ``~/SEAMM_DEV`` and adds the development tooling. Its services and apps carry
the installation's name (``jobserver-SEAMM_DEV``, ``SEAMM (SEAMM_DEV).app``); see
*Several installations* in the usage guide. To work on a package, install
your checkout into the environment with ``~/SEAMM_DEV/venv/bin/pip install -e .`` or
the package's ``make install`` with that environment activated.
