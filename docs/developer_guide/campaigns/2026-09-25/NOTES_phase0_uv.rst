Phase 0b notes -- the same checks on a uv-managed Python (2026-09-25)
======================================================================

Motivation
----------

After Phase 0 (conda clone, see ``NOTES_phase0.rst``) two questions were
raised: could the in-place migration be dropped in favour of "create a new
environment", and could the main environment avoid conda entirely, keeping
conda only for the per-code environments (Psi4, MOPAC, DFTB+, LAMMPS, ...).
``uv`` was proposed as the base because it supplies the interpreter itself,
which is the one thing pip cannot do. This is the test.

Setup
-----

::

    curl -LsSf https://astral.sh/uv/install.sh | sh        # uv 0.12.19 -> ~/.local/bin
    uv python install 3.12                                 # 23 s
    uv venv --python 3.12 uvenv
    uv pip install --python uvenv/bin/python \
        molsystem seamm seamm-datastore seamm-ff-util seamm-installer \
        seamm-util seamm-widgets reference-handler openbabel rdkit psutil \
        pillow seamm-exec seamm-jobserver

Resolved 84 packages in 20 s, prepared in 18 s, installed in under 1 s;
42 s wall clock for the whole install.

The interpreter is ``cpython-3.12.14-macos-aarch64-none`` from
python-build-standalone. Note that ``uv python install`` also placed a
``python3.12`` symlink in ``~/.local/bin``.

Results
-------

The Phase 0 check script passes unchanged (0 failures):

- openbabel 3.2.1, rdkit 2026.3.6, psutil, Pillow 12.3.0, spglib, pycifrw
  all from wheels
- molsystem SMILES -> OBMol -> RDKMol -> SDF
- seamm_datastore connect, initialize, admin login
- ``PIL.ImageTk`` PhotoImage
- sqlite3 module reports SQLite 3.53.1 (bundled with the interpreter)

**The bundled Tk is 9.0.4, not 8.6.** SEAMM has only ever run on Tk 8.6,
so a second, GUI-specific headless test was run under it:

======================================================== ==========
Check under Tk 9.0.4                                     Result
======================================================== ==========
ttk themes present (aqua, clam, alt, default, classic)   OK
Pmw 2.1.1: initialise, EntryField, Balloon, NoteBook     OK
seamm_widgets: LabeledEntry, LabeledCombobox, UnitEntry  OK
(set/get "1.0 Å"), PeriodicTable, ScrolledFrame
seamm.TkFlowchart construction, canvas laid out          OK
ImageTk on the real SEAMM_notext.png (1853x865)          OK
======================================================== ==========

All headless. Nothing here judges *appearance*: Tk 9 changed default
scaling, some option handling and the aqua theme details, so the flowchart
editor and a few step dialogs should be opened by eye once before this is
adopted. Step plug-ins were not installed in this venv, so no step dialog
was exercised.

A durable Tk 9 test environment was then built at
``~/Work/SEAMM/Testing/uvenv`` (core + all MolSSI plug-ins except the
torch-based ones; 164 packages, 57 s, 1.1 GB). Launch the GUI with
``~/Work/SEAMM/Testing/uvenv/bin/seamm``. A headless loop over every
plug-in's ``create_node`` + ``create_tk_node`` gave 30 of 45 succeeding
under Tk 9; the 15 that did not are the subflowchart-type steps (MOPAC,
ORCA, Psi4, Gaussian, DFTB+, FHI-aims, VASP, xTB, Structure,
Thermochemistry, Thermomechanical, Reaction Path, Diffusivity, Thermal
Conductivity, Subflowchart), all with the same ``None.winfo_toplevel``
error. **The identical script under Tk 8.6** (the ``seamm-dev`` conda
environment) fails the same set plus four dev-version plug-ins, so this is
a limitation of the headless harness (no real canvas for the nested
flowchart), not a Tk 9 regression: Tk 9 introduced zero new failures.

Size: the venv is **521 MB** against 2.4 GB for the production conda
environment (which also carries compilers and duplicate libraries).

Lockfile
--------

``uv pip compile --universal --python-version 3.12`` on the ten core
packages produced an 85-line pinned requirements file in 1.1 s, with
platform markers where needed (``pywin32 ; sys_platform == 'win32'``,
``tzdata`` likewise). This is the "constraints file" of the plan, but
cross-platform and produced by the resolver rather than exported from an
installed environment. It is what ``seamm_packaging`` should publish
nightly.

The compiled lock **does not contain ``openbabel``**, because
``molsystem``'s ``install_requires`` does not declare it (only its conda
recipe does). ``import openbabel`` only worked in this venv because it was
requested explicitly. This is the Phase 3 ``install_requires`` audit,
demonstrated: on a pure-pip base an undeclared dependency is simply absent.

Findings
--------

1. **A conda-free main environment works.** Every check that passed on the
   conda clone passes on the uv-managed Python, on macOS arm64. Linux
   (ChemAI) not yet run; the script is the same.
2. **Tk 9 is the new compatibility surface.** It works headlessly for Pmw,
   seamm_widgets and the flowchart editor. Visual check still owed. If Tk 9
   turns out to be a problem, the python.org 3.12 installer (Tk 8.6) is
   the fallback interpreter, and uv can be pointed at it with
   ``uv venv --python /Library/Frameworks/Python.framework/...``; uv found
   that interpreter (3.12.7) on this Mac already.
3. **Undeclared dependencies surface immediately** (openbabel above). Good:
   it is the failure mode you want, early and loud.
4. **Speed changes the migration story.** A full core install in 42 s and a
   universal lock in 1 s make "delete and recreate the environment" cheap
   enough to be the default remedy, which is what makes dropping the
   in-place migration reasonable.
5. **uv is not the installer's dependency for the codes.** Conda remains
   for the per-code environments through the plug-in installers; nothing
   in this test touched those.

6. **Two shipping bugs were found by using the clean venv, and fixed the
   same day.** (a) Right-click did nothing in the flowchart editor: Tk 9
   numbers the right mouse button 3 on macOS where Tk 8.6 used 2; fixed in
   seamm 2026.9.25 by binding both. (b) ORCA's Energy/Optimization/
   Frequencies/BSSE dialogs failed with ``no attribute 'LabeledText'``:
   orca_step 2026.9.25 had been released using a widget that existed only
   as an untracked file in the seamm_widgets checkout. Fixed by releasing
   seamm_widgets 2026.9.25 and orca_step 2026.9.25.1 (which now pins
   ``seamm-widgets>=2026.9.25``). Verified from PyPI alone in the uv env.
   Lesson: a PyPI-only environment is the right place to test a release;
   the conda dev environment hides unreleased shared-library symbols.
7. **``lammps_step`` does not import on Python 3.12 without setuptools.**
   ``lammps_step/lammps.py`` imports ``GPUtil`` (unmaintained since 2019),
   whose ``GPUtil.py`` does ``from distutils import spawn``. ``distutils``
   left the standard library in 3.12; conda environments still have it
   because conda installs ``setuptools`` (which provides a shim) into every
   environment, while a uv venv does not. So the LAMMPS step silently fails
   to load ("Could not load 'LAMMPS': No module named 'distutils'") on any
   clean 3.12+ venv. Fix in lammps_step: drop GPUtil and detect GPUs with
   ``shutil.which("nvidia-smi")`` plus a subprocess call, or at least catch
   the ImportError.

   **Systematic check, same day.** Every installed SEAMM package and
   plug-in in the uv venv (56) was imported, submodule by submodule, with
   ``pkg_resources``/``distutils`` absent. Exactly two fail: ``lammps_step``
   (GPUtil, above) and ``energy_scan_step`` (a direct ``import
   pkg_resources``). A source grep of the workspace found the same two plus
   nothing else in released packages (the remaining hits are ``old/``,
   ``*_sv`` and experimental copies). Cross-checking git tags against PyPI
   for the March-2026 "pkg_resources -> importlib" batch showed the cause:
   ``energy_scan_step``'s 2026.3.1 GitHub Release exists but its publish run
   failed at the CI step, so PyPI stayed at 2025.8.20; ``torchani_step``'s
   fix sat in an open dev->main PR (#9) since March and was never tagged.
   Fixes: lammps_step PR #111 (nvidia-smi query replaces GPUtil, dependency
   dropped, unit tests), energy_scan_step PR #8 (re-release as 2026.9.25),
   torchani_step PR #9 (retitled, HISTORY re-dated to 2026.9.25). A scan of
   open PRs across all molssi-seamm repos found no other stale fixes.

   Follow-ups the same day: **torchani-step was shelved** (Paul's decision --
   it needs substantial work; its docs build fails in CI on a
   pydata_sphinx_theme error). PR #9 closed with a note, the fix left on its
   dev branch, and the plug-in moved to ``excluded plug-ins`` in
   seamm_packaging (pushed to main; the nightly job drops it from the
   package list) and out of seamm_installer's ``molssi_plug_ins``.
   **energy_scan_step's CI docs build then failed on a missing openbabel:**
   moving ``seamm`` from the conda section to the pip sublist of
   ``test_env.yaml`` meant nothing pulled openbabel in, because molsystem's
   ``install_requires`` does not declare it (finding 3 again, this time
   biting CI). Fixed by listing ``openbabel`` under the conda dependencies.
   Every package that converts its CI env to the pip-sublist convention
   needs the same until molsystem declares openbabel (Phase 1).

Recommendation
--------------

Rewrite the plan around: uv-managed Python + venv for the main
environment, ``uv tool install seamm-installer`` for the installer itself
(outside the environment it manages), a nightly universal lock from
``seamm_packaging``, conda kept only for code environments, and "create a
new environment" as the migration path with the old conda environment
left frozen. Before committing to Tk 9: open the editor and two or three
step dialogs by eye; run the check script on ChemAI.

Artifacts left in place
-----------------------

``~/.local/bin/uv``, ``~/.local/bin/uvx``, the ``~/.local/bin/python3.12``
symlink, the uv-managed interpreter under ``~/.local/share/uv/python``, and
the venv in the session scratchpad (``uvenv``), which will disappear with
the session. ``seamm-pip-test`` from Phase 0 is also still present.
