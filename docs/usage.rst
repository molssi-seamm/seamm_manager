=====
Usage
=====

``seamm-manager`` is a command with sub-commands; ``seamm-manager --help`` lists them
and ``seamm-manager <command> --help`` the options of each. Global options come first:
``--root DIR`` chooses the SEAMM root (default ``$SEAMM_ROOT`` if set, else
``~/SEAMM``), ``--development`` uses ``~/SEAMM_DEV`` and adds the development tools,
``--name`` sets the installation's name in its services and apps, and ``--log-level``
controls verbosity. With no command the graphical installer opens.

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
resolve. Because the list is refreshed nightly, a release made today is invisible to
``update`` until tomorrow; ``update --latest`` asks PyPI for each package's newest
release instead, pins it exactly, and skips the lock (which would pin yesterday's
version). The one exception is the manager itself: since the list is refreshed
nightly, after an install or update the manager makes sure the environment holds
the same release it is running, so the plug-ins' installers never run on an older
one. After every change the manager writes ``<root>/environments/<timestamp>_*.txt``
with the full ``pip freeze`` of the environment as a record.

Several installations
---------------------

Any number of installations can live side by side, e.g. production in ``~/SEAMM``,
development in ``~/SEAMM_DEV`` and a trial of a new release in ``~/SEAMM_NEW``. Each
has its own environment, configuration, data and jobs; SEAMM finds the installation
from the environment it runs in, so nothing needs ``--root`` once installed.

The default installation ``~/SEAMM`` has the plain names: services ``jobserver`` and
``webui``, the app ``SEAMM``. Any other installation carries its name, which is the
root's directory name unless ``--name`` gives another: ``jobserver-SEAMM_NEW``,
``SEAMM (SEAMM_NEW).app``, and on macOS the process ``SEAMM-JobServer-SEAMM_NEW``.
``seamm-manager services status --all`` lists every installation's services.

``services create`` gives the web interface the service's existing port, or else
the first free port from 55055, so a second installation's web interface does not
clash with the first's; ``--port`` chooses one. It also stops and replaces any other
SEAMM service of the same kind started with the same root, whatever its name (such
as an older ``dev_jobserver``), so two JobServers never share one datastore.

Reference data -- VASP potentials, ``local:`` forcefields and models, the
thermochemistry database, ``dashboards.ini`` -- is taken from the installation's own
root if it has a copy, else from ``~/SEAMM``, so a new installation works without
copying it.

The external codes' conda environments (``seamm-lammps``, ``seamm-mopac``, ...) are
governed by the installation's *code-environment policy*, kept in
``<root>/installation.ini`` and shown by ``environment show``:

``own``
    The plug-ins create and update the codes' environments. Always the case for
    ``~/SEAMM``.
``shared``
    The default for any other installation. Installing a plug-in copies ``~/SEAMM``'s
    ``<code>.ini`` into the root, so the code runs from the same environment; installing
    or updating never creates, updates or removes a conda environment, and a code that
    ``~/SEAMM`` lacks is reported instead. So a trial installation cannot change the
    codes production uses.
``prefixed``
    The installation gets its own copies, named ``seamm-<name>-<code>`` (e.g.
    ``seamm-SEAMM_NEW-lammps``), for trying new versions of the codes themselves.

Choose it with ``seamm-manager --root <root> install --code-environments <policy>``.
The plug-ins' installers honour it through the seamm-manager in the installation's
own environment; if that copy is too old to know about policies, the manager skips
their install, update and uninstall steps rather than risk the shared environments.

Where things are
----------------

::

    ~/SEAMM/                 the root (--root)
    ~/SEAMM/venv/            the Python environment: SEAMM and all plug-ins
    ~/SEAMM/venv-webui/      the web interface's environment (optional)
    ~/SEAMM/environments/    the lock file and per-change snapshots
    ~/SEAMM/Jobs/            the datastore (jobs and their files)
    ~/SEAMM/services/        on macOS, the apps the services run as (SEAMM-JobServer, ...)
    ~/SEAMM/*.ini            configuration for SEAMM and each code

On macOS each service runs the environment's Python from a small background app in
``~/SEAMM/services``, so it shows up in Activity Monitor as ``SEAMM-JobServer`` or
``SEAMM-WebUI`` with the SEAMM icon rather than as ``python3.12``.

The manager itself, installed with ``uv tool install``, lives in uv's tool directory
and is also installed into ``~/SEAMM/venv`` so that the plug-ins' own installers can
import it there.
