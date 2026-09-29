=======
History
=======
2026.9.29.1 -- Bugfix: works with a cluster's central conda and Python
    * The codes' conda environments were always looked for, and made, in the conda
      installation's own ``envs`` directory. With a centrally provided conda, as on
      many clusters, that directory is read-only and the environments are elsewhere
      (``envs_dirs`` in ``~/.condarc``), so no environment could be found, updated or
      created. Environments are now found wherever conda has them, and new ones go in
      the first writable directory of ``envs_dirs``, as ``conda create -n`` would put
      them.
    * Installing no longer tries to recreate a code's conda environment that already
      exists; it uses it, and ``update`` brings it up to date.
    * The environment ``<root>/venv`` and the manager itself always use a Python
      installed by uv. When a conda environment was active -- as the central conda's
      base often is on a cluster -- uv used its Python instead, and the environment
      would break whenever that installation changed.

2026.9.29 -- Licensed codes get their configuration file on install
    * Installing the plug-in for a code you install yourself -- ORCA, Gaussian, VASP,
      FHI-aims -- now writes the plug-in's commented template, e.g. ``~/SEAMM/vasp.ini``,
      and says to edit it to give the code's location. Before, it only said to give the
      location in a file that did not exist. An existing file is never changed.
    * ``update`` no longer prints "Unable to update the executables because they were
      not installed using Conda" for these codes.

2026.9.28.1 -- Bugfix: updates respect every installed package's requirements
    * ``update --latest`` and ``--no-constraints`` resolved only the packages being
      updated and their dependencies, ignoring what the other installed packages
      require: updating seamm-thermochemistry moved pint to 0.26.1, breaking mendeleev,
      which needs ``pint<0.25``. Updates without the lock now resolve the whole
      installation at once -- the packages being updated, their dependencies and the
      requirements of everything else installed -- so dependencies are still brought
      up to date as far as every package allows, and if no set of versions satisfies
      them all the update stops with uv's explanation and changes nothing. With the
      lock (the default) everything is brought to the tested set, as before.
    * After installing or updating, the manager checks the environment and warns about
      any installed package whose requirements are not met.

2026.9.28 -- Bugfixes: the right installation, a sturdier datastore, quicker updates
    * The manager run from an installation's own environment -- such as
      ``~/SEAMM_DEV/venv/bin/seamm-manager``, or the app ``SEAMM-Manager (SEAMM_DEV)``
      -- worked on ``~/SEAMM``, showing production's services and shortcuts. It now
      works on the installation it runs from (``--root``, ``--development`` and
      ``$SEAMM_ROOT`` still take precedence), and treats ``~/SEAMM_DEV`` as the
      development installation.
    * ``update --all`` no longer re-solves every code's conda environment each time:
      a plug-in's environment file is applied again only if it changed, or after a
      week. ``update --refresh-codes`` applies them all now.
    * A jobs database that was never put under version control (as older development
      databases were) is now recognised and brought up to date instead of failing
      part-way; a new database is marked with its version when created; and an empty
      ``seamm.db`` (left by a JobServer started before the datastore was installed) or
      one without user accounts is set up properly instead of being taken as ready.
    * Updating the database while the JobServer ran would have crashed, and never
      stopped the JobServer first: it looked for the services under the wrong name.
    * When Zenodo cannot be reached, the manager uses the package list and lock it
      saved last time, with a one-line note, instead of printing a traceback.
    * On macOS, an editor's backup of a service file (``...plist~``) no longer shows up
      as a service.
    * Documentation: running several installations side by side, and trying a new
      release beside production.

2026.9.27.6 -- A trial installation cannot change production's codes
    * Each installation now has a code-environment policy for the external codes'
      conda environments, kept in ``<root>/installation.ini``. ``own`` (always the case
      for ``~/SEAMM``) creates and updates them as before. ``shared``, the default for
      any other installation, uses ``~/SEAMM``'s: installing a plug-in copies its
      ``<code>.ini`` from ``~/SEAMM``, and installing, updating or uninstalling never
      touches a conda environment, only reports. ``prefixed`` gives the installation its
      own copies named ``seamm-<name>-<code>``. ``install --code-environments`` chooses
      it and ``environment show`` shows it.
    * Before, installing plug-ins in a second installation recreated the shared
      environments, which is how a test on 2026-09-27 replaced the codes' environments
      on one machine.
    * The policy is applied by the seamm-manager in the installation's own
      environment. If that copy is too old to know about it, the manager now skips the
      plug-ins' install, update and uninstall steps in a non-default installation
      instead of letting them run.

2026.9.27.5 -- Several installations side by side; update --latest fixed
    * The services, desktop apps and macOS service bundles of an installation other
      than ``~/SEAMM`` now carry its name, which is the root's directory name unless
      the new ``--name`` option gives another: ``jobserver-SEAMM_NEW``,
      ``SEAMM (SEAMM_NEW)``, ``SEAMM-JobServer-SEAMM_NEW``. Before, any root other than
      ``~/SEAMM`` and ``~/SEAMM_DEV`` used the same names as ``~/SEAMM``, so creating
      its services replaced production's. ``~/SEAMM_DEV`` now follows the same rule
      (``jobserver-SEAMM_DEV`` rather than ``dev_jobserver``).
    * ``services create`` stops and replaces any other SEAMM service of the same kind
      started with the same root, whatever its name, so two JobServers never share one
      datastore. It gives the web interface the service's existing port, or else the
      first free port from 55055, so a second installation's web interface does not
      clash with the first's.
    * ``services status --all`` and ``services show --all`` list every installation's
      services, with their roots. The manager's window shows which installation it is
      working on, and its Services tab can now create the web interface service.
    * The root defaults to ``$SEAMM_ROOT`` when set.
    * ``update --latest`` asked PyPI's JSON API, which could return a stale copy
      shortly after a release; it now asks the simple index that uv installs from.
    * Bugfix: after installing seamm-jobserver, the manager restarted a service named
      after the package, which never exists, so the JobServer was not restarted.

2026.9.27.4 -- Bugfix: plug-in installers use the installation being worked on
    * The plug-ins' installers always wrote their code's ``.ini`` file (``mopac.ini``,
      ``lammps.ini``, ...) into ``~/SEAMM``, even for ``seamm-manager --root X`` or
      ``--development``. The manager now tells them its root, so the files go into the
      installation being installed or updated.
    * An installer run by hand from an installation's environment
      (``<root>/venv/bin/<plug-in>-installer``) works on that installation. ``root`` in
      the per-user ``seamm.ini`` is still honoured but deprecated, as it is shared by
      every installation.

2026.9.27.3 -- Bugfix: services restart now restarts the services
    * ``seamm-manager services restart`` did nothing: it ran the start command, which
      reported that the service was already running. It now stops and starts each
      service, on macOS and Linux. (The restart that ``update`` does after upgrading the
      JobServer was not affected.)
    * When starting, stopping or restarting a service failed, the command and the
      manager's Services tab crashed with an AttributeError instead of showing what
      went wrong. They now print the error.

2026.9.27.2 -- The Mac services show up by name, with the SEAMM icon
    * On macOS the JobServer and the web interface showed up in Activity Monitor and
      ``ps`` as ``python3.12``. They now run as ``SEAMM-JobServer`` and ``SEAMM-WebUI``
      with the SEAMM icon: ``services create`` puts the environment's Python
      interpreter in a small background app under ``~/SEAMM/services`` (a hard link,
      so no extra disk space) and runs the service with it. Jobs are started exactly as
      before.
    * Existing services keep working as they are. ``seamm-manager update`` says how to
      convert them (``seamm-manager services create --force jobserver webui``, when no
      jobs are running), and keeps the bundles' interpreter in step with the
      environment.
    * ``services create --force`` sometimes left the new service stopped, without any
      message: launchd was still removing the old one when it was started. Stopping a
      service now waits until launchd has finished.

2026.9.27.1 -- Bugfix: the Mac apps no longer ask for Rosetta
    * On an Apple Silicon Mac without Rosetta, starting SEAMM or SEAMM-Manager from its
      app showed a dialog asking to install Rosetta. The app's executable was a shell
      script, which carries no architecture, so macOS assumed it might need Intel code.
      The apps now use a small compiled launcher, built for both Apple Silicon and
      Intel, which runs the same script from the app's Resources folder. Nothing in
      SEAMM needs Rosetta.
    * ``seamm-manager update`` converts existing apps automatically (and keeps their
      version current); ``seamm-manager apps update`` does the same on its own.
    * The app's process is now SEAMM itself rather than a shell waiting on it.

2026.9.27 -- update --latest picks up a same-day release from PyPI
    * ``seamm-manager update`` takes the available version of each package from the
      package list published nightly, so a release made today was reported as
      "Everything is up to date" until the next day, and ``--no-constraints`` did not
      help. The new ``--latest`` option asks PyPI for each package's newest release,
      pins it exactly when it is newer than the list's, and updates without the lock
      file (which would pin yesterday's version). If PyPI cannot be reached the
      package list is used as before.

2026.9.26.6 -- Bugfix: environment files no longer upgrade a machine's torch
    * Applying a plug-in's environment file to an existing conda environment no
      longer upgrades bare pip requirements. Conda runs a file's ``pip:`` section
      with ``pip install -U``, so ``torch`` in xnn_step's file was upgraded, in the
      ``seamm-lammps`` environment that xnn.ini on ChemAI shares with LAMMPS, to a
      CUDA 13 build the driver cannot run. Now a bare name is installed only if
      missing, while a requirement with a version specifier (``xnns>=0.3.0``,
      ``e3nn==0.4.4``) is kept current within it. The plug-in that adds the MLFF
      engine to LAMMPS's environment keeps doing so; the machine's driver-matched
      torch is left alone.

2026.9.26.5 -- Bugfix: the manager's release was only synced alongside other updates
    * The step added in 2026.9.26.4 that puts the running manager's release into the
      environment ran only when some other package was being installed or updated, so
      an environment with nothing else to update kept the older manager. It now runs
      every time.

2026.9.26.4 -- The environment keeps the manager's own release; manual codes
    * After installing or updating, the manager puts its own release into the
      environment if the package list still names an older one. The list is refreshed
      nightly, so for up to a day after a manager release the environment -- and with it
      the plug-ins' installers -- used to get the previous version.
    * A plug-in installer for a code that is not installed automatically (ORCA,
      Gaussian, VASP) now says so when asked to install, instead of failing with an
      AttributeError about a missing environment file.

2026.9.26.3 -- Bugfixes from the first Linux migration (ChemAI)
    * ``update --all`` upgrades the manager itself with a forced, index-refreshing
      reinstall; ``uv tool upgrade`` could report "Nothing to upgrade" minutes after a
      release because uv reused its cached view of PyPI.
    * The datastore version check ran ``alembic`` from the PATH, which the
      manager's own tool environment does not have; it now runs the environment's
      alembic, like the migration itself. On ChemAI this made a fresh install end
      in "updated to version unknown, but it should be None".
    * ``services create`` on Linux crashed after deleting the old unit and before
      writing the new one (the executable path is now a ``Path``), leaving no
      service. Found on ChemAI; the unit was restored by hand.

2026.9.26.2 -- Bugfixes from a first installation on a brand-new Mac
    * On a fresh Mac ``uv tool install seamm-manager`` built the manager on the
      system Python 3.9, because nothing declared a minimum version. The package now
      requires Python 3.12 or later, so uv installs one if needed.
    * A plug-in's own installer that fails (for instance because conda is not
      installed) now reports what went wrong, instead of leaving the code silently
      uninstalled.
    * The datastore is created at installation, and before a service is started,
      rather than by the web interface's first start; a JobServer created first
      used to crash-loop on the missing database.

2026.9.26.1 -- Bugfixes from the first real migration
    * Conda could not be found by a manager or plug-in installer launched from the
      Dock or as a service, whose PATH is minimal, so the GUI showed a traceback in
      each plug-in's description. Conda is now found through ``$CONDA_EXE``, the PATH,
      or the usual installation directories, and its directory is passed on to
      sub-processes. With no conda environment active the base installation is taken
      from ``root_prefix`` rather than the (empty) active prefix.
    * The services and datastore commands used the raw ``--root`` option, which is
      empty when the default root applies; the post-install step crashed. They now
      use the resolved root.
    * A plug-in installer writing a fresh ``<code>.ini`` crashed serializing an empty
      configuration.
    * The manager's desktop app is ``SEAMM-Manager``, running ``seamm-manager``.
    * ``install`` runs the per-package steps (datastore update, the plug-ins' own
      installers) for the packages it installed or updated; ``--rerun-installers``
      runs them for every requested package, which recovers an interrupted install.

2026.9.26 -- First release of seamm-manager
    * seamm-manager replaces seamm-installer. It manages a SEAMM installation in a
      uv-managed Python virtual environment under the SEAMM root (``~/SEAMM/venv``):
      every package comes from PyPI, resolved against the published lock file, so an
      installation is reproducible and takes seconds rather than minutes. Conda is
      used only for the external codes' own environments (MOPAC, Psi4, LAMMPS, ...).
    * ``seamm-manager install --all`` creates the environment (Python 3.12 via uv) and
      installs SEAMM with all the MolSSI plug-ins in one constrained step; ``update``
      keeps the manager and the packages current; a new ``environment`` command shows,
      creates, recreates or removes the environment. Services, desktop apps and the
      datastore migration use the environment's own executables.
    * seamm-installer stays available for existing conda-based installations, which
      keep working but no longer receive updates; see the migration guide in the
      installation documentation. A ``seamm_installer`` compatibility module keeps the
      plug-ins' own installers working inside the new environment.
