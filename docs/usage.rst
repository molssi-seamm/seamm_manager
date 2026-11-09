=====
Usage
=====

``seamm-manager`` is a command with sub-commands; ``seamm-manager --help`` lists them
and ``seamm-manager <command> --help`` the options of each. Global options come first:
``--root DIR`` chooses the SEAMM root (default ``$SEAMM_ROOT`` if set, else the
installation whose environment the manager runs from -- ``~/SEAMM_DEV/venv/bin/seamm-manager``
and the app ``SEAMM-Manager (SEAMM_DEV)`` work on ``~/SEAMM_DEV`` -- else ``~/SEAMM``), ``--development`` uses ``~/SEAMM_DEV`` and adds the development tools,
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
                                      interrupted install. Writes
                                      ``<root>/taskserver.ini``, the TaskServer's
                                      capacity, if it is missing.
``update --all`` / ``update <names>`` Update the manager, then the packages, to the versions in
                                      the published lock, in a new version of the environment
                                      (see below); restarts the services that were
                                      running, leaving stopped ones stopped.
``show``                              List the SEAMM packages with installed and available
                                      versions.
``uninstall <names>`` / ``--all``     Remove packages (running their plug-in uninstallers);
                                      ``--all`` removes the whole environment.
``environment show|create|recreate``  Inspect, create, or rebuild ``<root>/venv`` from scratch
``environment remove``                (``recreate`` builds a fresh version with the SEAMM
                                      packages that were there and switches to it,
                                      at the lock's versions, which may be older than
                                      what was installed; ``--latest`` takes each
                                      one's newest release on PyPI instead).
``environment versions|switch``       The versions of the environment; switch to one, go back
``environment rollback|prune``        to the previous one, or remove old unused ones.
``environment pin|unpin <version>``   Keep a version from prune, e.g. for jobs on a
                                      cluster's compute nodes that name it directly.
``compare <flowchart> -a X -b Y``     Run a flowchart in two environments (versions,
                                      installations) and compare every result file.
``services create|start|stop|...``    Manage the JobServer and web-interface background
                                      services (launchd on macOS, systemd on Linux).
``apps create|delete|show|update``    Desktop apps for the flowchart editor and services.
``datastore show|update``             Inspect or migrate the jobs database.
``datastore rebuild``                 Rebuild the jobs database from the job directories,
                                      keeping the accounts and job owners; the old database is
                                      kept as a dated backup.
``flowcharts status``                 Report how many job flowcharts are still in format 2.0.
``flowcharts migrate``                Convert the job flowcharts and the jobs database to
                                      flowchart format 3.0 (dry run and confirmation first;
                                      ``--dry-run``, ``--yes``).
``refresh-cache``                     Re-read the package list from Zenodo.
===================================== ==========================================================

Versions of the environment
---------------------------

``<root>/venv`` is a link to the current version of the environment, in
``<root>/venvs/<date and time>``. ``install`` and ``update`` never change the current
version while it may be in use: they build the next version beside it from a copy of
the current one plus the change, switch the link, and restart the services that
were running so that they run from it (a service stopped on purpose stays stopped). Jobs already running keep the version they started in, and the
services and apps always name the real path, never the link, since Python does not
follow the link when it starts (``--in-place`` changes the current environment
directly instead, which is only safe with no jobs running). ``environment versions``
lists the versions and the processes using each; ``rollback`` and ``switch`` move
the link; ``prune`` removes versions that are old, unused, unpinned and not among
the newest two.

A process started *through* the link (``<root>/venv/bin/...``) would see the new
version if the link moved under it, so while one is running the switch is held back.
The flowchart MCP servers of Claude sessions (``seamm-flowchart mcp``) are the
exception: they load everything when they start and keep it until restarted, so they
never hold back a switch; the manager says how many there are, and a ``/mcp``
reconnect in each Claude session moves it to the new version. For any other such
process the manager lists them and asks whether to switch anyway -- in the
SEAMM-Manager app with a dialog, on a terminal with a yes/no question. Switching anyway
is usually safe, since a running program keeps the code it has already loaded.
Without anyone to ask (a script or a service) the switch is refused and the new
version left ready for ``environment switch``; ``--force`` switches without asking.

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
version). Without the lock the manager resolves the whole installation together: the
packages being updated, their dependencies, and the requirements of every other
installed package. Dependencies are upgraded as far as all of them allow, and if no set
of versions satisfies everything the update stops, reports why, and changes nothing.
The lock never moves an installed package backwards: where the installed version is
newer than the lock's pin (a release made since the nightly list, or a development
build), that version is the floor instead, and the manager says which packages it kept.
Before switching to a new version of the environment the manager compares it with the
current one; if a package would go back to an older version you did not ask for, a
package would be removed, or an installed package's requirements would newly be unmet,
the manager says why and asks whether to use the new version anyway (in the app, with a
dialog). If not, or with no one to ask, the new version is left built but not switched
to, with what to run instead (``update --latest``, or ``environment switch`` to use it
anyway). The command then exits with status 1, as it does when a switch is refused
because processes started through the link are running, so scripts can tell that
nothing changed; the app says so in a message.
``environment recreate`` is the exception: it is a deliberate clean rebuild at the
lock's versions, so it is not checked this way and may move packages back; use
``environment recreate --latest`` to keep today's releases. After any install
or update it also warns about any package whose requirements are not met. If Zenodo
cannot be reached, the manager says so and uses the package list and lock it saved last
time.

When a plug-in's installer updates its code's conda environment, it applies the
plug-in's environment file only if the file changed since it was last applied, or if
that was more than a week ago, since re-solving a conda environment is slow.
``update --refresh-codes`` applies them all now, to pick up new builds of the codes.

The one exception is the manager itself: since the list is refreshed
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

Codes' environments as archives (clusters with a slow shared file system)
--------------------------------------------------------------------------

On some clusters the shared file system creates files very slowly -- on ARC's
``/projects``, from 1 to 30 files a second -- so a conda environment of ~30,000 files
takes hours to create or update in place, and as long to unpack there, while the
same environment builds in a few minutes on a compute node's local disk. An
installation that manages its codes (``own`` or ``prefixed``) can therefore keep
them as *archives* instead of directories::

    $ seamm-manager --root <root> install --code-environment-storage archive <plug-in>

(recorded as ``code-environment-storage`` in ``<root>/installation.ini``; the
default, ``directory``, keeps conda environments as usual, and is right for a
workstation or a cluster such as ChemAI). With archive storage, installing or
updating a plug-in's code:

#. builds its conda environment from the plug-in's environment file in ``$TMPDIR``
   on the compute node, with the packages cached there too,
#. packs it with conda-pack into one file,
   ``<root>/env-archives/<name>-<date>T<time>.tar``, with the exact package list
   (``.explicit.txt``) and the hash of the environment file (``.yml.sha256``) beside
   it, and
#. points ``<root>/env-archives/<name>.tar`` at it. Archives are never rewritten: a
   new version is a new file, and the link is switched at once, so a job unpacking
   an older one is not disturbed. The three newest versions, and any less than a day
   old, are kept.

An update rebuilds an archive only if the plug-in's environment file has changed, or
the archive is over a week old (``--refresh-codes`` forces it). These builds are
real work on local disk, so seamm-manager refuses them outside a Slurm job::

    $ sbatch -N1 -n1 -c4 --mem=16G -t 2:00:00 \
        --wrap 'seamm-manager --root <root> update --all'

(or set ``SEAMM_ARCHIVE_BUILD_DIR`` to a fast local directory). The code's
``<code>.ini`` is unchanged -- ``installation = conda``, ``conda-environment =
<name>`` -- and the codes not yet built this way (those needing PyTorch) stay
directories.

Jobs use the archives through ``<root>/bin/seamm-conda``, a wrapper for conda that
seamm-manager installs. The cluster queues' ``setup`` (in the JobServer's queue
configuration) exports it::

    setup = export CONDA_EXE=<root>/bin/seamm-conda

SEAMM runs a conda code as ``$CONDA_EXE run -n <name> <code>``. The wrapper unpacks
``<name>.tar`` on the job's node, under ``$TMPDIR/seamm-envs``, the first time a job
needs it there (about 10 s for Psi4's 2.4 GB), and runs the code in that copy; later
calls in the job reuse it. An environment without an archive, and any other conda
command, go to the real conda unchanged. If an archive exists but cannot be unpacked,
the command fails with a message beginning ``seamm-conda: FAILED`` rather than quietly
running in a different environment; ``$TMPDIR/seamm-envs/stage.log`` on the node
records each staging.

The SEAMM environment as an archive
-----------------------------------

The SEAMM environment itself, ``<root>/venv`` (about 46,000 files), has the same
problem: building a new version beside the current one on such a file system can
take hours, although the build takes about a minute on a compute node's local disk.
To store it as an archive too, run, inside a Slurm job::

    $ sbatch -N1 -n1 -c4 --mem=16G -t 0:30:00 \
        --wrap 'seamm-manager --root <root> environment archive'

This records ``seamm-environment-storage = archive`` in ``<root>/installation.ini``,
publishes the current version as ``<root>/env-archives/seamm-venv-<version>.tar``
(``seamm-venv.tar`` links to it), and installs ``<root>/bin/stage_seamm_venv.sh``
and the launchers ``<root>/bin/run_from_jobserver`` and ``run_flowchart``. Each
cluster queue whose jobs should run from the archive needs, in the JobServer's queue
configuration::

    setup = source <root>/bin/stage_seamm_venv.sh
    remote_run_from_jobserver = <root>/bin/run_from_jobserver

A job then unpacks the archive on each of its nodes into ``$TMPDIR/seamm-venv``
(about 30 s) and runs SEAMM from there. As with the codes, if the archive exists
but cannot be unpacked, the job fails with a message beginning
``stage_seamm_venv: FAILED`` rather than running from a different environment. Not
for queues with ``tasks = queue``: their task bundles are separate jobs that start
SEAMM's Python by its path in the main job.

From then on every install, update and ``environment recreate`` (all inside a Slurm
job, like the codes' builds):

#. unpacks the current version from its archive onto the node's local disk, and
   builds the new version there from it, as an update does beside the current one,
#. checks it as usual (nothing moved back, no newly unmet requirements), then packs
   and publishes it as ``seamm-venv-<version>.tar``. From this moment new jobs use it.
#. unpacks the archive into ``<root>/venvs/<version>`` with 32 tar streams at once
   (``SEAMM_UNPACK_STREAMS``), which on ARC writes the whole environment in about a
   minute and a half where one stream takes 20 minutes or more, and switches
   ``<root>/venv`` to it for everything that does not stage it: the login nodes,
   the ``tasks = queue`` queues and the plug-ins' installers.

The archive and the directory hold the same files, and share the version's name, so
``environment switch`` and ``rollback`` move the archive's link with the
directory's. ``--in-place`` has no effect with archive storage. If the job ends
after publishing but before switching, ``environment unpack`` (in a Slurm job)
finishes the unpacking and the switch. Old archives are pruned like the codes';
old directories with ``environment prune``.

Trying a new release beside production
--------------------------------------

To try new versions of SEAMM and the plug-ins without touching the installation you
use, make a second one, use it, and remove it::

    $ seamm-manager --root ~/SEAMM_NEW install --all
    $ seamm-manager --root ~/SEAMM_NEW update --all --latest    # today's releases
    $ seamm-manager --root ~/SEAMM_NEW install seamm-webui
    $ seamm-manager --root ~/SEAMM_NEW services create jobserver
    $ seamm-manager --root ~/SEAMM_NEW services create webui --webui-host 127.0.0.1
    $ seamm-manager --root ~/SEAMM_NEW apps create

The new installation shares ``~/SEAMM``'s codes (it copies their ``.ini`` files and
never creates or updates a conda environment), gets its own JobServer
(``jobserver-SEAMM_NEW``), web interface on the next free port (55056 beside
production's 55055) and apps (``SEAMM (SEAMM_NEW)``), and keeps its jobs in
``~/SEAMM_NEW/Jobs``. Submit jobs to it through its own web interface or app.

To remove it::

    $ seamm-manager --root ~/SEAMM_NEW services delete jobserver webui
    $ seamm-manager --root ~/SEAMM_NEW apps delete
    $ seamm-manager --root ~/SEAMM_NEW environment remove
    $ rm -rf ~/SEAMM_NEW

``environment remove`` removes only the Python environment; the last command removes
the rest (jobs, logs, configuration, the web interface's environment).

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

The queue file
--------------

``install`` also writes ``<root>/queues-example.ini``, an annotated example of
the JobServer's queue file ``<root>/<name>.ini`` (the hostname by default),
which says where jobs may be sent: this machine, its own SLURM, a cluster over
ssh. Copy it to that name, edit it and restart the JobServer. The JobServer's
user guide and the SEAMM documentation's how-to "Configure the JobServer's
Queues" describe the keys.
