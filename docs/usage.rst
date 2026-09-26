=====
Usage
=====

``seamm-manager`` is a command with sub-commands; ``seamm-manager --help`` lists them
and ``seamm-manager <command> --help`` the options of each. Global options come first:
``--root DIR`` chooses the SEAMM root (default ``~/SEAMM``), ``--development`` uses
``~/SEAMM_DEV``, ``--log-level`` controls verbosity. With no command the graphical
installer opens.

===================================== ==========================================================
Command                               What it does
===================================== ==========================================================
``install --all``                     Install SEAMM and all MolSSI plug-ins (creating the
                                      environment if needed); ``--third-party`` adds those;
                                      ``install <names>`` installs specific packages;
                                      ``install seamm-webui`` sets up the web interface's
                                      own environment; ``install development`` adds tooling;
                                      ``--rerun-installers`` redoes the per-package steps
                                      (datastore update, the codes' installers) after an
                                      interrupted install.
``update --all`` / ``update <names>`` Update the manager, then the packages, to the versions in
                                      the published lock; restarts the JobServer when needed.
``show``                              List the SEAMM packages with installed and available
                                      versions.
``uninstall <names>`` / ``--all``     Remove packages (running their plug-in uninstallers);
                                      ``--all`` removes the whole environment.
``environment show|create|recreate``  Inspect, create, or rebuild ``<root>/venv`` from scratch
``environment remove``                (``recreate`` reinstalls what was there).
``services create|start|stop|...``    Manage the JobServer and web-interface background
                                      services (launchd on macOS, systemd on Linux).
``apps create|delete|show|update``    Desktop apps for the flowchart editor and services.
``datastore show|update``             Inspect or migrate the jobs database.
``refresh-cache``                     Re-read the package list from Zenodo.
===================================== ==========================================================

Versions and the lock file
--------------------------

The package list and a *lock file* -- the pinned versions of every SEAMM package and
every dependency that resolved together -- are published nightly to Zenodo by
``seamm_packaging``. ``install`` and ``update`` pass that lock to ``uv`` as
constraints, so what you get is the tested set, and two installations made the same
day are identical. ``--no-constraints`` opts out and takes the newest releases that
resolve. After every change the manager writes ``<root>/environments/<timestamp>_*.txt``
with the full ``pip freeze`` of the environment as a record.

Where things are
----------------

::

    ~/SEAMM/                 the root (--root)
    ~/SEAMM/venv/            the Python environment: SEAMM and all plug-ins
    ~/SEAMM/venv-webui/      the web interface's environment (optional)
    ~/SEAMM/environments/    the lock file and per-change snapshots
    ~/SEAMM/Jobs/            the datastore (jobs and their files)
    ~/SEAMM/*.ini            configuration for SEAMM and each code

The manager itself, installed with ``uv tool install``, lives in uv's tool directory
and is also installed into ``~/SEAMM/venv`` so that the plug-ins' own installers can
import it there.
