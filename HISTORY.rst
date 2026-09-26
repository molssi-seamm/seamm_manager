=======
History
=======

(unreleased) -- First release of seamm-manager
    * seamm-manager replaces seamm-installer. It manages a SEAMM installation in a
      uv-managed Python virtual environment under the SEAMM root (``~/SEAMM/venv``):
      every package comes from PyPI, resolved against the published lock file, so an
      installation is reproducible and takes seconds rather than minutes. Conda is
      used only for the external codes' own environments (MOPAC, Psi4, LAMMPS, ...).
    * seamm-installer stays available for existing conda-based installations, which
      keep working but no longer receive updates; see the migration guide.
