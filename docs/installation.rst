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
itself.

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

The environment
---------------

Everything Python lives in ``~/SEAMM/venv``. If it is ever damaged,

.. code-block:: console

    $ seamm-manager environment recreate

deletes and rebuilds it and reinstalls the packages that were in it, in well under
a minute. ``environment show`` describes it. You never need to activate it; the
manager, the services and the apps all use its interpreter directly.

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
packages named without a version (``torch``) are installed only if missing and
otherwise left as they are, while those with a version specifier are kept current
within it. So a torch build you installed by hand for your GPU driver survives
updates; to change it, reinstall it by hand in that environment.

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
