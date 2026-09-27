=======
History
=======
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
