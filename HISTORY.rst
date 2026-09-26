=======
History
=======
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
