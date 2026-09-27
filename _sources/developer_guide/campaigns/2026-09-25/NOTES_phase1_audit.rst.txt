Phase 1 notes -- the ``install_requires`` audit (2026-09-25)
=============================================================

Method
------

Two passes, which agreed.

1. **Static.** For every package checkout in the workspace, parse all
   ``import`` statements (``ast``), map each top-level module to its
   distribution, and compare against the declared requirements
   (``requirements.txt`` / ``setup.cfg`` / ``setup.py`` / ``pyproject``).
   Then discount anything in the *transitive closure* of the declared
   requirements (computed from installed metadata), and label each
   remaining import as unconditional, function-local, or try-guarded.
   Scripts: ``audit_requires.py`` and ``audit_refine.py`` (session
   scratchpad; ~120 lines, easy to recreate from this description).
2. **Empirical.** For each core package, ``uv venv`` + ``uv pip install
   <package>`` alone, then import every submodule (``pkgutil.walk_packages``).

Core packages
-------------

Empirical result (clean venv, package alone):

================== =====================================================
Package            Result
================== =====================================================
molsystem          **import fails: No module named 'openbabel'**
seamm              fails the same way (via molsystem)
seamm-exec         fails the same way (via molsystem)
seamm-util         OK
seamm-widgets      OK (basis_set_exchange is a lazy import; see below)
seamm-datastore    OK at import; alembic needed for migrations (see below)
seamm-ff-util      OK
reference-handler  OK
seamm-jobserver    OK
seamm-installer    OK
================== =====================================================

Fixes applied (one PR each):

- **molsystem**: declare ``openbabel>=3.1.1``; replace the stale comment
  saying openbabel has no wheels. This single change closes the gap for
  everything downstream.
- **seamm-datastore**: declare ``alembic`` -- ``database/alembic/env.py``
  and the migration scripts import it, and ``seamm-installer`` runs them.
- **seamm-widgets**: declare ``basis_set_exchange`` -- imported inside the
  BSE picker (lazy, so import-time is unaffected, but the dependency is
  real). Added to the CI env's pip sublist too.
- **seamm**: drop ``seamm-datastore`` -- nothing under ``seamm/`` imports it
  (``seamm_dashboard_client`` and ``reference_handler`` are imported and
  stay).
- **seamm-ff-util**: declare ``rdkit``, which ``ff_assigner.py`` and
  ``forcefield.py`` import directly (it arrived transitively via molsystem).

Plug-ins: genuine gaps, deferred to each plug-in's next release
---------------------------------------------------------------

Real direct imports with no declaration and not in the transitive closure.
All are masked today because the installer installs every package; they
only bite on a standalone ``pip install <plug-in>``.

===================== =========================================================
Missing requirement   Plug-ins
===================== =========================================================
openbabel             gaussian, psi4, quickmin, read_structure (moot once
                      molsystem declares it, but a direct import is a direct
                      dependency)
seamm-exec            mopac, psi4
tabulate              fhi_aims, thermomechanical, xtb
seamm-thermochemistry gaussian (function-local import in ``substep.py``)
model-chemistry-step  lammps (function-local; needed for QM-MD over MDI)
===================== =========================================================

``seamm-installer`` is imported by the ``installer.py`` of nine plug-ins
(atomic_charges, dftbplus, lammps, mopac, orca, packmol, psi4, xtb,
seamm-thermochemistry). That is not a requirements fix but a **Phase 3
design constraint**: those modules run *inside* the SEAMM venv as the
``<pkg>-step-installer`` console scripts, so ``seamm-installer`` must stay
installed in the venv even when the CLI also lives in a ``uv tool``
environment (or ``installer_base`` moves to a small shared library).

Discounted as false positives
-----------------------------

- try-guarded optional paths: ``openeye`` (molsystem), ``mdi`` /
  ``mopactools`` / ``mpi4py`` / ``tblite`` (the MDI engines, which run in
  their own conda environments), ``xmltodict`` (dftbplus), ``openpyxl``
  (seamm-thermochemistry importers), ``seamm_dashboard`` (datastore).
- Python 2 fallbacks in ``seamm_util/printing.py`` (``ConfigParser``,
  ``thread``); harmless, could be deleted.
- ``seamm_util/seamm_json.py`` imports ``seamm`` inside a function: a
  deliberate inversion to avoid a cycle; ``seamm`` is always present.
- ``seamm_webui`` declares everything; the static parser misread its
  ``pyproject.toml``.
- Unreleased / experimental checkouts (conformer_search, data_sources,
  pyscf, training_set_analysis, trajectory_analysis, ``*_sv``, ``old/``)
  were scanned but are out of scope.

Also found on the way
---------------------

- ``seamm_installer/conda/meta.yaml`` lists ``openbabel`` and ``rdkit`` as
  run dependencies the installer never imports (they were there to seed the
  bootstrap environment). Goes away with the feedstock.
- ``seamm_util``'s ``kaleido`` dependency is declared in the packaging
  metadata's side-table only; ``seamm_util`` itself does not import kaleido
  (plotly calls it for static image export), so it belongs in
  ``seamm_util``'s requirements as a runtime-optional companion of plotly
  rather than in the side-table. Left for the seamm_util release that
  removes the side-table (Phase 2).

Phase 1b -- CI on uv: pilot results (2026-09-25)
------------------------------------------------

devops branch ``uv-ci`` (two commits) adds the uv path to ``CI``,
``BranchCI``, ``Docs`` and ``Release``, chosen per step by
``hashFiles('devtools/conda-envs/test_env.yaml')``. Pilot branches
``ci-uv`` on seamm_widgets and molsystem delete the env file and carry a
temporary ``PilotCI.yaml`` that runs the full matrix from the devops branch.

- **First attempt failed on tkinter.** ``astral-sh/setup-uv`` with a
  ``python-version`` input resolved to the runner's system
  ``/usr/bin/python3.12``, which has no tkinter, so seamm_widgets' docs build
  died importing the package. Fix: the interpreter now comes from
  ``actions/setup-python`` (toolcache builds include tkinter on ubuntu and
  macOS) and uv is only the installer, ``uv venv --seed --python
  "$(which python)"``.
- **seamm_widgets: green across the matrix** (ubuntu + macOS, 3.11 + 3.12).
  Lint & docs 18 s; each test job 20-35 s wall clock including environment
  creation. The conda path's jobs on the same package take several minutes.
- **molsystem: lint, docs and the wheels are fine**; one test job failed on
  five PubChem lookups (``No 3-D structure available for ammonia`` and the
  like) that the conda-path CI on the same code passed minutes earlier and
  that a previous uv-path run also passed. PubChem throttling, not the
  workflow; re-run pending. Those tests should probably carry a network
  marker with a retry, independent of this campaign.
- ``uv`` silently accepts extras a package does not define, so the
  workflow's ``'.[test,docs]'`` is safe everywhere.
- References to ``test_env.yaml`` that need updating after the devops merge:
  the plug-in cookiecutter template (``devtools/conda-envs/test_env.yaml``
  and ``devtools/README.md``), the ``release-seamm-plugin`` skill
  (``SKILL.md`` and ``check_deps.py``), and seamm_dashboard's Makefile
  (retiring anyway).

Outcome (later on 2026-09-25): devops PR #1 merged; the two ``ci-uv`` pilot
branches deleted; the plug-in cookiecutter template lost its ``devtools``
directory (all conda-CI boilerplate); the ``release-seamm-plugin`` skill now
tells a release to ``git rm`` the env file, and ``check_deps.py`` exits
quietly without it. The five core packages with open PRs were converted by
deleting ``test_env.yaml``: molsystem, seamm_widgets and seamm_datastore went
green at once; **seamm and seamm_ff_util fail their docs build on
``No module named 'openbabel'``** because they resolve ``molsystem`` from
PyPI, where 2026.9.20 still does not declare it. That is the audit's core
finding biting for real, and it fixes the merge order: molsystem #119 first,
release, then re-run the other two. It also shows what the uv CI now
guarantees -- a dependency gap anywhere in the chain fails the build the
same day.
