2026-09-25 -- Move SEAMM off conda: a uv-managed environment, PyPI only
========================================================================

Status (2026-09-27): **complete and deployed.** Phases 0-4 done: uv-managed
environment, PyPI-only packages, new Zenodo package list + universal lock (concept
record 22970126; the old 7789853 is frozen), CI on uv, ``seamm-manager`` released
(2026.9.26 through 2026.9.27: find_conda, datastore.ensure, sync_manager,
conservative pip policy for the plug-ins' conda environment files,
``update --latest``), and all four machines migrated with an end-to-end job each
(this Mac, paul.local, ChemAI, MolSSI10; ``NOTES_phase4.rst``). The 2026-09-27
incident (a shared conda environment's torch and xnns upgraded by a plug-in's
environment file) and its fixes are in ``NOTES_phase4.rst``. What is left is
listed under *Outstanding* at the end.

.. toctree::
   :maxdepth: 1

   NOTES_phase0
   NOTES_phase0_uv
   NOTES_phase1_audit
   NOTES_phase4

Why
---

Eight core packages are installed from conda-forge while the ~45 plug-ins and
the other core libraries are installed with pip, all into one conda
environment. The mixed model causes recurring problems:

1. **Release lag.** A conda-forge feedstock publishes hours to days after the
   PyPI release and needs a separate PR per package. Measured in Phase 0:
   the production ``molsystem`` was three months behind PyPI.
2. **Two resolvers, one environment.** Conda solves its packages ignoring
   everything pip installed; conda then runs ``pip install -U`` on the pip
   list; pip *does* see conda's packages and upgrades them when asked; the
   next conda solve puts the conda copy back. This is the source of the
   "conda ``pytorch`` replaced the pip CUDA torch" and "pip ``pymdi``
   replaced conda's MPI-linked MDI" incidents. Phase 0 showed the same
   thing in a dry run: ``conda update --all`` on a mixed environment would
   reinstall a conda ``pillow`` over the pip one and walk ``bibtexparser``
   past the ``<2`` bound that four SEAMM packages declare.
3. **The installer cannot change a package's channel** (``install.py`` /
   ``update.py`` ``raise NotImplementedError``), so the metadata cannot be
   changed without breaking every existing installation.
4. **Environment-level rot.** ``create_env`` lists the ``defaults`` channel;
   production has a ``pkgs/main`` ``sqlite`` and a conda-forge
   ``libsqlite`` that both own ``lib/libsqlite3.dylib``.

The original reason for conda was compiled dependencies with no wheels,
chiefly ``openbabel`` and ``rdkit``. That reason is gone (survey below).
The one thing pip cannot supply is the interpreter, with its ``tkinter`` and
``sqlite3``; ``uv`` supplies exactly that. Conda remains the right tool for
the external codes, which are not Python packages.

Survey: what actually needed conda
----------------------------------

Packages on the conda-forge channel in ``seamm_packaging``'s ``metadata.py``::

    molsystem  seamm  seamm-dashboard  seamm-datastore
    seamm-ff-util  seamm-installer  seamm-util  seamm-widgets

plus ``reference-handler``, which is conda-forge in production but absent
from that list. ``seamm-dashboard`` is being retired.

PyPI wheels for every compiled dependency, checked 2026-09-25:

============== ========== ===========================================
Package        Version    Wheels
============== ========== ===========================================
openbabel      3.2.1      official (upstream); macOS x86_64 + arm64,
                          manylinux x86_64 + aarch64, Windows;
                          cp310 -- cp314
rdkit          2026.3.6   macOS arm64, manylinux, Windows; cp310 -- cp315
psutil, pillow current    all platforms
spglib,        current    all platforms
pycifrw
scipy, numpy,  current    all platforms
statsmodels,
sqlalchemy
apsw           3.53.4.0   all platforms (qcportal's compiled dependency)
kaleido, pmw   current    PyPI only -- already pip
============== ========== ===========================================

What the interpreter must bring: ``tkinter`` with Tk, and ``sqlite3``.
The uv-managed ``cpython-3.12.14`` (python-build-standalone) brings
**Tk 9.0.4** and SQLite 3.53.1. The python.org 3.12 installer brings Tk
8.6 and is the fallback interpreter if Tk 9 proves a problem; uv can
create the venv from it.

What Phase 0 established
------------------------

Full detail in the two NOTES files. The short version:

- **Everything works on pip wheels**, on macOS arm64, both in a conda
  environment with the conda copies removed (``NOTES_phase0``) and on a
  conda-free uv-managed Python (``NOTES_phase0_uv``): openbabel, rdkit,
  molsystem round trips, datastore login, ``PIL.ImageTk``.
- **Tk 9.0.4 works headlessly** for Pmw 2.1.1, seamm_widgets (incl.
  PeriodicTable, UnitEntry) and ``TkFlowchart``. Appearance not yet judged.
- **A uv install of the core set takes 42 s; the venv is 521 MB** (conda
  environment: 2.4 GB). ``uv pip compile --universal`` locks it in 1 s.
- **The in-place path is the hard part.** After moving the SEAMM packages,
  ~150 conda Python packages remain and ``conda update --all`` clobbers pip.
  A fresh environment has none of this. Hence the decision to drop in-place.
- **Undeclared dependencies surface at once on a pip-only base.** The
  universal lock had no ``openbabel`` because ``molsystem``'s
  ``install_requires`` does not list it (only the conda recipe did).

Retiring seamm-dashboard
------------------------

All three fragile pins in the metadata (``connexion <3.0``,
``flask-jwt-extended =4.5.3``, ``pyjwt =2.9.0``) belong to the dashboard and
go with it, as do ~20 Flask packages and ``sqlalchemy<2.0``.

``seamm-datastore`` **stays**: it is the data layer of ``seamm_webui`` (its
``db.py`` and every router import the datastore models) and of
``seamm_exec`` (``exec_flowchart.py`` creates and updates the Job row). The
JobServer reads job status through ``sqlite3`` directly and does not import
it. The core ``seamm`` package lists it in ``requirements.txt`` without
importing it; that dependency can be dropped.

Target architecture
-------------------

**Main environment.** A uv-managed CPython 3.12 (later 3.13) in a venv at a
fixed location under the SEAMM root, e.g. ``~/SEAMM/venv`` (decision
below). Every SEAMM package and every Python dependency from PyPI via
``uv pip install``. No conda anywhere in it.

**Installer.** ``seamm-manager`` (new package, decision 4) installed with
``uv tool install`` into its own isolated environment, *outside* the
environment it manages, and also into the venv for the plug-in installer
scripts. It can
therefore create, delete and recreate the SEAMM venv freely, and updating
the installer (``uv tool upgrade seamm-installer``) never reinstalls a
package that is currently running.

**Known-good set.** ``seamm_packaging`` publishes, nightly, a universal
lock (``uv pip compile --universal``) alongside the package list. The
installer passes it as a constraints file by default; ``--no-constraints``
opts out (default in development mode).

**Code environments.** Unchanged: the plug-in installers create conda
environments for Psi4, MOPAC, DFTB+, LAMMPS, xtb, Packmol, TorchANI via
conda-forge. The ``Conda`` class stays for this. Conda is required on the
machine only when one of those plug-ins is installed; the installer should
say so at that point rather than at bootstrap. Docker remains the other
route.

**Migration.** No in-place conversion. Users create the new environment
with the bootstrap below, then delete (or keep, renamed) the old conda
environment. The old package list on Zenodo is left as is, so old
installations freeze cleanly rather than break (decision below).

**Bootstrap** (the whole user-facing story, same on macOS and Linux)::

    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv tool install seamm-manager
    seamm-manager install all              # creates the venv, installs, sets up services/apps

Phases
------

Phase 0 -- validate (done)
~~~~~~~~~~~~~~~~~~~~~~~~~~

Done 2026-09-25 for macOS arm64; see the NOTES. Remaining, before Phase 3
is finalized:

- Open the flowchart editor and two or three step dialogs under Tk 9 by
  eye (Paul). A durable test environment for this is at
  ``~/Work/SEAMM/Testing/uvenv`` (core + the MolSSI plug-ins); launch with
  ``~/Work/SEAMM/Testing/uvenv/bin/seamm``. If Tk 9 is unacceptable, the
  python.org interpreter is the base and ``uv venv --python <path>`` points
  at it; the rest of the plan is unchanged.
- Run ``phase0_checks.py`` (in the session scratchpad; recreate from the
  NOTES if lost) on ChemAI with a uv-managed Linux Python. Needs uv
  installed in that account -- ask first.

Phase 1 -- make the packages honest about their dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Independent of the installer; ordinary PyPI releases. Pip only knows
``install_requires``, so every dependency that today lives in a conda
recipe or in the packaging metadata's side-table must move into the
package.

- **Audit ``install_requires``** of ``molsystem``, ``seamm``,
  ``seamm-datastore``, ``seamm-ff-util``, ``seamm-installer``,
  ``seamm-util``, ``seamm-widgets``, ``reference-handler`` against their
  ``conda/meta.yaml`` ``run:`` lists and the metadata ``dependencies``
  tables. Known gaps: ``molsystem`` lacks ``openbabel``; ``seamm-util``
  lacks ``kaleido``. Check the plug-ins the same way where they have a
  recipe.
- **Stdlib removals hidden by conda's setuptools.** ``lammps_step`` imports
  ``GPUtil``, which imports ``distutils`` (gone in 3.12); it only loads in
  conda envs because they ship setuptools. Replace GPUtil with a
  ``shutil.which("nvidia-smi")`` check. Grep all plug-ins for ``distutils``,
  ``pkg_resources`` (torchani_step) and ``imp``.
- ``molsystem/setup.py``: fix the stale "openbabel has no wheels" comment.
- ``seamm/requirements.txt``: drop ``seamm-datastore``.
- ``seamm-installer``: add ``uv`` handling (Phase 3) but *not* a hard
  dependency on conda; ``psutil`` etc. are ordinary requirements.
- ``devtools/conda-envs/test_env.yaml`` in each: SEAMM deps in the ``pip:``
  sublist per the existing CI convention (or switch CI to uv outright --
  separate decision, not required here).
- Delete or archive ``conda/meta.yaml`` and the feedstocks with a pointer to
  PyPI once Phase 4 is done. No further conda-forge releases are needed
  for correctness because nothing in the new design reads conda-forge.

Phase 1b -- CI on uv instead of conda
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Why: every package's CI builds a hand-maintained
``devtools/conda-envs/test_env.yaml`` with setup-miniconda and then runs
``pip install . --no-deps``, so ``install_requires`` is never exercised. The
env file is a second copy of the dependency list (hence ``check_deps.py``),
49 of the 75 files take ``seamm`` from conda-forge and so inherit openbabel
from the conda recipe, and a fix released to PyPI is not testable
downstream until conda-forge catches up. molsystem's missing openbabel
survived for years because CI could not see it; the energy_scan CI failure
on 2026-09-25 was the same mechanism.

What changes, in ``molssi-seamm/devops`` (one change, every package uses
the reusable workflows at ``@main``):

- The four workflows (``CI``, ``BranchCI``, ``Docs``, ``Release``) gain a
  **uv path** beside the conda path, selected per step with
  ``if: hashFiles('devtools/conda-envs/test_env.yaml') == ''``. A package
  with the env file keeps the conda path unchanged; a package that deletes
  it gets uv. Migration is therefore per package, at its own pace.
- The uv path: ``astral-sh/setup-uv`` with the matrix Python, ``uv venv
  --seed .venv`` (seeded so ``python -m pip`` in ``buildDocs.sh`` still
  works), the venv's ``bin`` on ``GITHUB_PATH``, then one
  ``uv pip install '.[test,docs]'`` **with dependencies** plus the fixed
  tooling set: pytest, pytest-cov, black, flake8, codecov, and the docs
  tools every package uses (pydata-sphinx-theme, sphinx-design,
  sphinx-copybutton, sphinxnotes-strike, sphinx-rtd-theme, rinohtype,
  pystemmer, pygments). uv ignores extras a package does not define, so
  ``[test,docs]`` costs nothing where absent and lets a package add its own.
- ``conda list`` becomes ``uv pip list`` / ``pip list``; the ``deploy`` job
  (already conda-free) stops calling ``conda list``.
- Compiled dependencies (openbabel, rdkit, numpy, scipy) come from wheels,
  which is exactly what users get.

Per package, when it next releases: delete ``test_env.yaml``; add a
``[test]``/``[docs]`` extra only if it needs something beyond the fixed
set. ``check_deps.py`` becomes unnecessary for converted packages. Update
the cookiecutter template first (drop ``test_env.yaml`` from the plug-in
and substep templates).

Validation: push the devops change on a branch, point one package's
``BranchCI`` caller at ``@<branch>`` on a throwaway branch with
``test_env.yaml`` deleted, confirm lint/tests/docs pass on ubuntu and macOS
for 3.11 and 3.12, then merge devops to main. Pilot packages: molsystem
(compiled wheels) and seamm_widgets (Tk). Remember the reusable-workflow
rerun gotcha: a re-run keeps the old devops version; push a new commit.

Phase 2 -- seamm_packaging: the package list and the lock
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Implemented 2026-09-25 in seamm_packaging PR #1**, as below, with these
details: the database is ``"format": 2`` with ``python``, ``lock``, ``doi``,
``conceptdoi`` and ``zenodo_id`` fields; the first upload (no ``zenodo_id``)
creates a new deposition with a pre-reserved DOI, later ones add a version;
a ``packaging_dry_run`` command creates and discards a draft;
``resolve_packages`` resolves without touching Zenodo; the whole 57-package
set resolves in ~3 s to 776 lock lines. ``seamm-installer`` stays in the
list until ``seamm-manager`` is on PyPI.

**Published.** The first ``check_for_changes`` after the merge created Zenodo
record 22970127 under **concept record 22970126** (``SEAMM Package List``,
CC-BY-4.0, files ``SEAMM_packages.json`` + ``seamm.lock.txt``), committed as
seamm_packaging 2026.9.25.1. The old record (concept 7789853) is frozen. The
installer's lookup is "latest version of concept 22970126".

- **Metadata.** Remove the ``repository`` field's role (everything is
  PyPI); move ``seamm-dashboard`` to ``excluded plug-ins``; delete the
  ``dependencies`` side-tables (their content now lives in
  ``install_requires`` per Phase 1); the ``libsqlite`` pin becomes a
  documentation note about interpreter builds, since SQLite now comes with
  the interpreter.
- **Resolution.** Replace the conda dry-run in ``create_full_environment``
  with ``uv pip compile --universal --python-version 3.12`` over the full
  package set. Output: ``SEAMM_packages.json`` (name, version, type,
  description -- no channel) and ``seamm.lock.txt`` (the universal lock).
  Drop ``seamm.yml`` / ``seamm_pinned.yml``. The nightly job installs uv
  with the official script.
- **Zenodo.** Publish to a **new** Zenodo record. The installer reads the
  record ID from code; the new installer reads the new record. The old
  record's last version is left untouched so the old installer keeps
  working against a frozen list and old environments simply stop
  updating. (Decision below; the alternative, updating the old record,
  needs an old-installer release to avoid ``NotImplementedError``.)
- Keep the draft-reuse / discard-on-failure logic from 2026-09-19.

Phase 3 -- seamm_manager: uv-hosted environment, direct installs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

(Decision 4: this is a **new package** ``seamm_manager`` built from the
``seamm_installer`` code base, not an in-place change to ``seamm_installer``.
Everything below refers to the new package; ``seamm_installer`` is frozen.)

The bulk of the code work. Files: ``install.py``, ``update.py``,
``uninstall.py``, ``util.py`` (``create_env``, ``find_packages``,
``package_info``), ``my.py``, ``services.py``, ``apps.py``, ``mac.py`` /
``linux.py``, ``datastore.py``, ``data/``.

- **New ``Uv`` class** (``uv.py``) beside ``Conda``: ``python_install``,
  ``venv``, ``pip_install(packages, constraints=None, upgrade=False)``,
  ``pip_list`` (``--format json``), ``pip_uninstall``, ``locate`` (find
  ``uv`` on PATH or at ``~/.local/bin/uv``). Thin subprocess wrappers, like
  ``Conda``.
- **Environment model.** ``my.environment`` becomes a venv path under the
  root (default ``<root>/venv``); ``my.python`` its interpreter. Created on
  first ``install`` if absent; ``seamm-installer environment recreate``
  deletes and rebuilds it (cheap: 42 s). No ``conda activate`` anywhere.
- **Install / update / uninstall** become one uv command each:
  ``uv pip install [-c lock] pkg ...``, ``uv pip install -U [-c lock] pkg
  ...``, ``uv pip uninstall pkg ...``. A ``pinned`` entry in the package list
  is ``pkg==ver``. Delete: the conda/pypi split, channel comparison,
  ``NotImplementedError`` branches, ``create_env`` and its dependency
  side-table, the environment yml writing. Keep writing
  ``environments/<stamp>.txt`` from ``uv pip freeze`` as the audit trail.
- **Constraints.** ``--constraints`` (default on) fetches ``seamm.lock.txt``
  from the Zenodo record and passes ``-c``; ``--no-constraints`` opts out,
  and is the default when ``my.development``.
- **Self-management.** The installer is a uv tool; ``seamm-installer
  update`` upgrades it with ``uv tool upgrade seamm-installer`` first, then
  re-execs itself so the rest of the update runs on the new code. If the
  installer is found to be running from inside the SEAMM venv (developer
  setups), skip that step and say so.
- **Services and apps.** ``services.py`` (launchd / systemd) and ``apps.py``
  embed the interpreter path; point them at the venv and provide
  ``seamm-installer services reinstall`` for users moving from the conda
  environment. The datastore alembic step in ``datastore.py`` locates
  ``alembic.ini`` via ``importlib.metadata`` and needs the venv's python.
- **Code environments.** Untouched. ``Conda`` is required lazily: the first
  time a plug-in installer needs it, check for conda and print how to get
  Miniforge if missing.
- **seamm-webui.** Its dedicated environment becomes a second uv venv
  (``<root>/venv-webui``) created the same way; ``install_seamm_webui`` in
  ``install.py`` already only needs python + pip.
- **Remove** the ``defaults`` channel everywhere and ``data/seamm.yml`` /
  ``development.yml`` (replaced by the bootstrap and by
  ``seamm-installer install development`` which is a uv install of the dev
  package list).
- **Tests.** Unit tests for ``Uv`` command construction (with/without
  constraints, pins, upgrade), for the install/update planners with a mocked
  ``Uv``, and an integration test that bootstraps a venv in a temp root and
  installs one small package.
- Release to PyPI. ``uv tool install seamm-installer`` is then the only
  install path.

Phase 4 -- roll out, migrate ourselves, document
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Our machines**, one at a time, JobServer idle: this Mac (``~/SEAMM``
  and ``~/SEAMM_DEV``), ChemAI (``seamm`` account), MolSSI10. Rename the
  conda environment rather than delete it until the new one has run real
  jobs; reinstall services and apps; verify a flowchart end to end and the
  webui.
- **Developer workflow.** ``make install`` (``pip install .``) works
  unchanged inside a uv venv; document creating ``seamm-dev`` as
  ``uv venv`` + ``uv pip install -e`` or the existing Makefiles.
- **Docs.** New installation page (the three-line bootstrap); a migration
  page (create new, reinstall services, remove old conda env, what stays in
  ``~/SEAMM``); the "never ``conda update --all``" warning is no longer
  needed because there is no conda environment; conda is documented only
  under the code plug-ins. Update the main molssi-seamm.github.io docs.
- **Announcement / release notes** for users on the old record: what
  "frozen" means and how to move.
- Archive the eight feedstocks.

Decisions (Paul, 2026-09-25)
-----------------------------

1. **Tk 9: accepted.** The uv-managed standalone Python is the interpreter
   as is. Any Tk 9 rendering quirks are fixed in seamm_widgets as found.
2. **Venv location: ``<root>/venv``**, i.e. ``~/SEAMM/venv`` by default and
   ``~/SEAMM_DEV/venv`` for the dev root, so ``--root`` selects both.
3. **Old Zenodo record: frozen.** The new package list and lock go to a
   *new* record. Old installers keep working against the last conda-era
   list and simply stop seeing updates; an announcement tells people how to
   migrate.
4. **Installer: a new package, ``seamm_manager``** (PyPI ``seamm-manager``,
   CLI ``seamm-manager``), installed as a uv tool outside the venv *and*
   into the venv as an ordinary package so the plug-ins' ``*-step-installer``
   scripts keep working. It ships a thin ``seamm_installer`` compatibility
   module (re-exporting ``installer_base``) until the ten plug-ins that
   import it switch at their next release. ``seamm_installer`` on PyPI and
   conda-forge stays frozen as the conda-era tool -- no ambiguity about
   which tool a document means. New repo, not a rename.
5. **Python: 3.12 now, 3.13 once CI covers it.** Add 3.13 to the devops
   matrix first; bump the default when green across packages
   (``seamm-manager environment recreate`` makes the switch cheap).

Risks and open questions
------------------------

- **uv governance.** Astral is venture-funded and uv is at 0.x. Mitigation:
  uv only drives standard wheels into a standard venv; falling back to
  python.org Python plus pip is a documentation change, not a repackaging.
- **python-build-standalone quirks.** Non-framework build on macOS (same
  as conda today), ``libedit`` rather than ``readline``, occasional C
  extensions that object to how it is built. Nothing showed in Phase 0;
  the Tk 9 by-eye check is the remaining exposure.
- **Tk 9 appearance.** Headless OK; visual unknown. Fallback exists.
- **Linux untested** for the uv path as of this writing.
- **Users who skip the announcement** keep a frozen but working conda
  environment indefinitely. Acceptable.
- **Constraints staleness.** The lock is regenerated when the package list
  changes; add a scheduled regeneration as well so third-party security
  fixes flow.
- **HPC accounts without ``~/.local/bin`` on PATH.** The uv installer
  handles this for interactive shells; document the one-line PATH addition
  for batch scripts and for the JobServer's environment.
- **Windows.** Every wheel exists and uv supplies the interpreter, so this
  removes the last conda-only obstacle. Not in scope, but now plausible.

Outstanding (as of 2026-09-27)
------------------------------

Retire the conda-era pieces, once the venv installations are trusted:

- The conda-era dashboards still running on ChemAI and MolSSI10 (port 55055) beside
  the new webui. ChemAI is hands-off until Paul asks for a specific action.
- The old conda ``seamm`` environments and ``SEAMM-Installer.app`` on this Mac,
  paul.local, ChemAI and MolSSI10, kept as fallbacks.
- ``~/SEAMM_DEV`` on this Mac (conda-based development root with ``dev_jobserver``).
- The conda-forge feedstocks of the seven core packages: archive or leave dormant.

Communicate:

- DONE 2026-09-27: the main docs site (molssi-seamm.github.io, PR #56, live) describes
  the uv bootstrap and the SEAMM Manager, with a migration page.
- A migration announcement to users.
- Still to do on the docs site: *Managing the Dashboard* shows the old
  Dashboard's screens and the queue how-to runs ``seamm-dashboard``; both need the web
  interface's equivalents. The graphical page reuses the SEAMM Installer screenshots.

Loose ends found along the way:

- xnn_step: the ``dev`` branch carries uncommitted D4 work (another session) that must
  be rebased onto ``main`` (2026.9.27 pinned ``xnns<0.2``; move the pin forward when an
  xnns release loads the older checkpoints again).
- pyxtal-step (third party) imports ``pkg_resources`` and its installer fails on
  Python 3.12: report upstream or exclude it from the package list.
- ChemAI's jobserver unit has a hand-added ``sh -lc`` login-shell wrapper the manager's
  parser cannot show; a ``--login-shell`` option on ``services create`` would make it
  reproducible.
- MolSSI10 has a stale ``calpoly`` login session (root ``loginctl terminate-user``).
- ``update --all`` reruns every plug-in's ``conda env update`` even when the environment
  file is unchanged, which is slow; skip unchanged files.
- When Zenodo is slow or down, ``show`` (and anything else that fetches the package
  list) prints the raw exception chain from ``find_packages``. It should say that Zenodo
  is unavailable and fall back to the cached list. Seen 2026-09-27 (15 s responses).
- GitHub Pages was never enabled for seamm_manager, so its documentation 404'd; enabled
  2026-09-27 from the existing ``gh-pages`` branch.
- DONE 2026-09-27 (seamm-manager 2026.9.27.1): the Mac apps' shell-script executable made
  Apple Silicon Macs without Rosetta ask for it; replaced by a compiled universal launcher.

Later by design:

- Python 3.13 in CI and as the venv default once the stack is checked on it.
