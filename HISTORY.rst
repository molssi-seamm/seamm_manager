=======
History
=======

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
