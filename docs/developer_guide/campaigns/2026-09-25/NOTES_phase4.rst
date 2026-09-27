Phase 4 notes -- rolling out seamm-manager (started 2026-09-26)
================================================================

Machine 1: this Mac, production ``~/SEAMM``
-------------------------------------------

Starting state: conda env ``seamm`` (2.4 GB, Python 3.12.13, Tk 8.6);
launchd services ``jobserver`` and ``dashboard`` (port 55055) pointing at
``~/miniconda3/envs/seamm/bin``; apps ``SEAMM.app`` and
``SEAMM-Installer.app`` launching through ``conda run -p``; datastore with
322 jobs, none active. The dev installation (``~/SEAMM_DEV``: dev_jobserver,
dev_dashboard, dev_webui) was left alone.

Steps, in order, all with ``seamm-manager`` from the ``seamm-dev`` checkout
(2026.9.26 plus the fixes below):

1. ``seamm-manager install --all --third-party`` -- created
   ``~/SEAMM/venv`` (Python 3.12.14, Tk 9.0.4), installed the 57 packages
   under the published lock: 177 packages, 46 plug-ins load with no
   warnings. 119 s to the end of the uv install.
2. ``seamm-manager services create --force jobserver`` -- the launchd entry
   now runs ``~/SEAMM/venv/bin/seamm-jobserver``; running.
3. ``seamm-manager apps create --force SEAMM manager`` -- ``SEAMM.app`` now
   runs ``~/SEAMM/venv/bin/seamm`` directly (no ``conda run``);
   ``SEAMM-Manager.app`` added. The old ``SEAMM-Installer.app`` is left in
   place (it still points at the conda env) until the conda env is removed.
4. Datastore checked: at head, no migration needed.
5. ``~/Work/SEAMM/Testing/test.flow`` run headlessly through
   ``~/SEAMM/venv/bin/run_flowchart``: steps 0-3 ran; step 4 (ORCA
   optimization) failed with ORCA's "duplicated keyword TIGHTSCF" -- the
   known, separate orca_step bug. The identical flowchart through the conda
   env fails identically (orca_step 2026.8.7.1 there), so the new
   environment executes flowcharts exactly as the old one, ORCA is found
   through ``orca.ini`` as before, and the failure is orca_step's, not the
   migration's.

6. **Dashboard replaced by the webui** (Paul's go-ahead):
   ``seamm-manager install seamm-webui`` created ``~/SEAMM/venv-webui``
   (seamm-webui 2026.8.13.1); ``services delete dashboard`` stopped and
   removed the conda-era dashboard; ``services create webui --webui-host
   127.0.0.1`` started the web interface on the dashboard's old port 55055,
   so the ``[localhost]`` entry in ``dashboards.ini`` keeps working. It
   answers ``/api/status`` (322 jobs) and ``/api/jobs``.
7. **PATH**: appended ``export PATH="$PATH:$HOME/SEAMM/venv/bin"`` to
   ``~/.zshrc`` -- *appended*, not prepended, so an activated conda dev
   environment's tools still win in a development shell while
   ``run_flowchart``/``seamm`` are found otherwise. Note ``.zshrc`` is read
   by interactive shells only; batch scripts need the explicit path.

The **conda env** ``seamm`` is untouched as the fallback. The old
``SEAMM-Installer.app`` still points at it.

Bugs found and fixed in seamm_manager on the way (dev, unreleased)
------------------------------------------------------------------

- ``my.options.root`` was used by services.py and datastore.py, but the new
  entry point leaves ``--root`` as None when the default applies; the first
  production install crashed in the post-install datastore step. All uses
  now go through ``my.root``.
- The manager's own desktop app was still named ``SEAMM-Installer`` and
  looked for a ``seamm-installer`` executable; now ``SEAMM-Manager`` running
  ``seamm-manager``.
- ``Configuration.to_string`` raised IndexError on an empty configuration,
  which is what a plug-in installer holds when its ``<code>.ini`` does not
  exist yet (``xnn-step-installer`` on a root without ``xnn.ini``).
  Pre-existing in seamm_installer; fixed with a test.

- **Conda not found from the Dock.** ``SEAMM-Manager.app`` listed the
  packages but every plug-in installer's "show" failed, with the traceback
  landing in the Description column: an app (or a service) has a minimal
  PATH, and every conda command was a bare ``conda ...`` string, plus four
  ``shutil.which("conda")`` in installer_base. Now ``find_conda()`` tries
  ``$CONDA_EXE``, the PATH, then the usual install directories
  (miniforge3, miniconda3, anaconda3, ... in ``~``, ``/opt``,
  ``/usr/local``), adds the directory to the PATH for sub-processes, and is
  used everywhere. Also ``conda info``'s ``active_prefix`` is null with no
  environment active; the root now comes from ``root_prefix``. Verified by
  running the plug-in installers and ``seamm-manager show`` with
  ``PATH=/usr/bin:/bin``.

All released as **seamm-manager 2026.9.26.1** (2026-09-26), together with
``install --rerun-installers`` (below). This Mac then got the documented
tool copy (``uv tool install seamm-manager``) and the venv's copy updated to
the release. Two things seen doing that: ``uv tool install`` on a machine
with an existing uv cache resolved the *previous* release (stale index;
``uv tool upgrade`` refreshed and got the new one -- a fresh machine has no
cache, so the bootstrap is unaffected), and ``seamm-manager update`` could
not update the venv's own copy until the nightly package list caught up,
since the list and lock still named 2026.9.26; it was pinned by hand.

Observations for the docs / the other machines
----------------------------------------------

- A crash in the post-install loop is not recoverable by re-running
  ``install``: it reports "Nothing to install" and skips the per-package
  steps (datastore update, plug-in installers) for already-installed
  packages. The three plug-in installers the crash skipped had to be run by
  hand. A ``seamm-manager install --rerun-installers`` (or making the loop
  run for installed packages too) would be worth adding.
- ``~/SEAMM/environments`` contained a stray ``f{tstamp}_environment.yml``
  from an old f-string bug in seamm_installer; harmless, left for now.
- The plug-in installers for the codes behave exactly as before: they read
  ``~/SEAMM/<code>.ini`` and use the existing conda environments
  (``seamm-mopac``, ``seamm-lammps``, ...). Some report "Installing Conda
  environment ... Done!" even when it exists; that is their normal update
  check.
- ``run_flowchart`` and ``seamm`` are no longer on ``PATH`` by default (the
  conda env used to be activated). Flowcharts with the
  ``#!/usr/bin/env run_flowchart`` shebang need ``~/SEAMM/venv/bin`` on the
  PATH, or an explicit ``~/SEAMM/venv/bin/run_flowchart``. The installation
  docs should say so; the manager could offer to add the line to the shell
  profile.

Machine 2: paul.local, a brand-new Mac (2026-09-26)
----------------------------------------------------

macOS 26.7, arm64, system Python 3.9.6 only, Miniforge installed by Paul
at ``~/miniforge3`` but deliberately **not** on the PATH (an ``init-conda``
shell function instead). Done over ssh, exactly as a user would type it.

1. ``curl -LsSf https://astral.sh/uv/install.sh | sh`` -- uv 0.12.19, adds
   ``. "$HOME/.local/bin/env"`` to ``.zshrc`` (interactive shells only).
2. ``uv tool install seamm-manager`` -- **built the tool on the system
   Python 3.9** (LibreSSL warning and all), because the package declared no
   minimum Python. Fixed on dev: ``python_requires='>=3.12'`` so uv
   installs 3.12 itself; for this machine ``uv tool install --force
   --python 3.12 seamm-manager``.
3. ``seamm-manager install --all`` -- environment created, 175 packages under
   the lock, **86 s**. But no code environments appeared: the venv got
   seamm-manager 2026.9.26 from the package list (the nightly had not yet
   picked up 2026.9.26.1), whose installer base looks for conda only on the
   PATH; every plug-in installer crashed with ``FileNotFoundError: 'conda'``
   and the manager **swallowed the output** (it only logged it). Fixed on
   dev: a failing plug-in installer's output tail is now printed with the
   ``--rerun-installers`` hint. For this machine: pinned the venv's manager
   to 2026.9.26.1 by hand and ran ``install --all --rerun-installers``.

4. ``install --all --rerun-installers`` (with the venv's manager at
   2026.9.26.1) -- **165 s** to create every code environment with conda
   found at ``~/miniforge3`` *off* the PATH: seamm-mopac, -lammps, -psi4,
   -dftbplus, -xtb, -packmol, -chargemol, -xnn; each installer reports its
   code (MOPAC 23.2.5, LAMMPS 29 Aug 2024, Psi4 1.11, xTB 6.4.1, Packmol
   21.2.1).
5. ``services create jobserver``, ``install seamm-webui``, ``services
   create webui --webui-host 127.0.0.1``, ``apps create``, the PATH line.
   **Ordering trap:** the JobServer, created first, crash-looped on the
   missing ``Jobs/seamm.db`` until the web interface's first start created
   it (launchd's KeepAlive then brought it up). Fixed on dev: the manager
   now creates the datastore itself at install time and before starting any
   service (``datastore.ensure()``, admin/admin), verified on a scratch
   root.
6. First flowchart, built with ``Flowchart.create_node`` (from SMILES "O"
   -> MOPAC Energy) and run with ``~/SEAMM/venv/bin/run_flowchart``: ran to
   completion in standalone mode with **no** ``~/.seamm.d/seammrc`` needed;
   enthalpy of formation -53.42 kcal/mol. So the credentials file is only
   for submitting to a dashboard, not for local runs.

Total for a brand-new Mac, from nothing to a working full installation with
all codes: about ten minutes of wall clock, most of it conda building the
code environments.

Lessons for the installation page: a new Terminal (interactive shell) is
needed after installing uv; the manager's own copy inside the venv follows
the package list, so a manager release is only fully in effect the day after;
install Miniforge *before* ``install --all`` if the codes are wanted in one
pass (or use ``--rerun-installers`` afterwards). Small oddity seen: the
from-SMILES plug-in's entry-point name is ``FromSMILESStep`` while every
other plug-in uses its display name; harmless, but inconsistent.

A slip of mine while testing the datastore fix on this Mac: a scratch-root
``--development services create jobserver`` refused (a real ``dev_jobserver``
existed) and the ``services delete`` that followed removed the real dev
JobServer. Restored immediately with identical launch arguments; running
since. Lesson: test service commands with a throwaway *name*, not just a
throwaway root.

Machine 3: ChemAI, ``seamm`` account (2026-09-26)
--------------------------------------------------

Ubuntu 22.04, x86_64, 128 cores, 2 x A100; conda at ``~/miniconda3``
(initialized in ``.bashrc`` only); systemd user services ``jobserver``,
``dashboard`` (55055) and ``webui`` (55155, https, external); 2473 jobs,
none running locally; the ``tinkercliffs`` SLURM queue configured via ssh.

1. uv + ``uv tool install --python 3.12 seamm-manager`` (2026.9.26.2).
2. ``install --all --third-party``: 177 packages, 50 s. Two findings:
   the third-party **pyxtal-step installer imports ``pkg_resources``** and
   fails (reported cleanly by the new message; its own bug, not ours), and
   the **datastore version check crashed**: ``latest_version`` /
   ``db_version`` ran a bare ``alembic`` from the PATH, which the tool
   environment lacks. Fixed on dev (the venv's alembic, like the migration
   itself); the manager was reinstalled on ChemAI from the dev branch
   (``uv tool install --force --from git+...@dev``). The database was
   untouched (head ``d7d6859198e9``).
3. ``services create --force jobserver`` **deleted the old unit and then
   crashed** (``TypeError``: the executable path is a ``Path`` since
   ``Uv.which``; linux.py concatenated strings) -- ChemAI had no JobServer
   for a few minutes. Restored by hand from the unit's ``~`` backup with the
   venv path, then fixed on dev and the tool reinstalled. The hand-added
   ``/bin/sh -lc '...'`` login-shell wrapper on the JobServer unit (not
   something the manager writes; presumably for the ssh transport's
   environment) was preserved. ``services status`` shows no root for it
   because the manager's unit parser does not understand the wrapper --
   cosmetic; a ``--login-shell`` option for Linux services would make this
   explicit.
4. ``install seamm-webui`` + ``services create --force webui --port 55155
   --webui-host 0.0.0.0`` (unit backed up first): recreated cleanly; answers
   ``/api/status`` over https (anonymous status shows no jobs on this
   multi-user server, unlike the single-user Macs).
5. PATH line in ``.bashrc``; 46 plug-ins load in the venv; water/MOPAC
   standalone run OK.
6. **End to end:** job 5158 submitted to the new web interface from the
   ``seamm`` account (queue ``ChemAI``), run by the JobServer from the venv,
   finished, -53.42 kcal/mol.

Left as they were: the conda ``seamm`` env (fallback), the ``dashboard``
service (still from the conda env; retire when Paul says), the LAMMPS/xnn
code environments (explicit conda paths in their ini files).

Machine 4: MolSSI10, ``psaxe`` account (2026-09-26)
----------------------------------------------------

Debian 11, x86_64, 6 cores; conda at ``~/miniconda3`` (``.bashrc`` init);
systemd user services ``jobserver``, ``dashboard`` (55055) and ``webui``
(55060, https, external), plain unit files; eight code environments with
explicit conda paths in their ini files; no active jobs. **Stale
``calpoly`` session:** the account deleted in August still has a 51-day-old
systemd user session running a copy of *psaxe's* seamm-jobserver; needs
``loginctl terminate-user calpoly`` as root -- flagged, not touched.

1. uv + ``uv tool install --refresh --python 3.12 seamm-manager`` ->
   2026.9.26.3 (the release cut for ChemAI's findings).
2. ``install --all --third-party``: 177 packages, 60 s, datastore at head.
   The plug-in installers failed again because the venv received
   seamm-manager 2026.9.26 from the package list (nightly not yet run), whose
   conda wrapper builds a path from the null ``active_prefix``. Pinned the
   venv's copy to 2026.9.26.3 by hand and re-ran the installers -- the third
   machine in a row to need this. Fixed on dev: after an install or update
   the manager installs *its own* release into the environment when the list
   names an older one (``sync_manager``), outside the lock for that one
   package.
3. The re-run built the code environments (218 s; MOPAC 23.1.2, LAMMPS
   7 Feb 2024, Psi4 1.11, xTB 6.4.1). One more plug-in finding: the
   **orca-step installer** failed on this root, which has no ``orca.ini``,
   with ``AttributeError: 'Installer' object has no attribute
   'environment_file'`` -- ``installer_base.install`` assumed every code has
   a conda environment file, but ORCA/Gaussian/VASP are manual installs.
   Fixed on dev: such an installer now says the code must be installed by
   hand and where to record it.
4. ``services create --force jobserver`` -- worked first time with
   2026.9.26.3 (the Linux crash fix); unit on the venv, running.
   ``install seamm-webui`` + ``services create --force webui --port 55060
   --webui-host 0.0.0.0`` -- running, answers ``/api/status`` over https
   (67 jobs).
5. PATH line in ``.bashrc``; 46 plug-ins load; water/MOPAC standalone OK.
6. **End to end:** job 681 submitted to the new web interface (queue
   ``molssi10``), run by the JobServer from the venv, finished,
   -53.42 kcal/mol.

Left as they were: the conda ``seamm`` env, the ``dashboard`` service
(55055), the stale ``calpoly`` session.

Where Phase 4 stands (2026-09-26, end of day)
---------------------------------------------

All four machines run SEAMM from a uv-managed environment with the JobServer
and web interface on it, and each has run a job through the whole chain:

================ ======================= =====================================
Machine          Manager                 Notes
================ ======================= =====================================
Mac ``~/SEAMM``  2026.9.26.3 (tool)      dashboard replaced by webui (55055)
paul.local       2026.9.26.3 (tool)      brand-new machine, user-path test
ChemAI (seamm)   2026.9.26.3 (tool)      JobServer unit keeps ``sh -lc``
MolSSI10 (psaxe) 2026.9.26.3 (tool)      calpoly session to terminate
================ ======================= =====================================

Every venv still carries whatever seamm-manager the package list named at
install time (pinned to a release by hand on three of them); ``sync_manager``
on dev removes that step for good. Unreleased on dev, for 2026.9.26.4:
``sync_manager``, the manual-code installer message. Still to do: release
it; retire the three conda-era dashboards and the conda ``seamm`` envs when
Paul is satisfied; ``~/SEAMM_DEV`` on the Mac; the main docs site and the
migration announcement; archive the feedstocks; report pyxtal-step's
``pkg_resources`` import upstream.

Incident: ``update --all`` broke ChemAI's GPU stack (2026-09-27)
----------------------------------------------------------------

Running ``seamm-manager update --all`` on ChemAI (to exercise the 2026.9.26.5
self-sync) ran every plug-in's own installer with ``update``. ``xnn.ini``
there deliberately points at ``seamm-lammps`` so the MLFF engine runs beside
LAMMPS; the xnn installer therefore applied ``seamm-xnn.yml`` to that shared
environment, and because conda's ``env update`` runs the file's pip section
with ``-U``, the unpinned ``torch`` went from 2.13.0+cu126 to 2.14.0 with the
CUDA 13 runtime, which the 535 driver (CUDA 12.2) cannot run. Every GPU torch
job, including the LAMMPS MLFF engine, broke. Conda's history shows nothing
because no conda transaction occurred. The same environment was broken the
same way on 2026-09-19 by the old installer; that repair moved torch to the
pip section on the assumption pip would leave a satisfying torch alone.

Repair (with Paul's go-ahead): reinstall ``torch==2.13.0+cu126`` from the
PyTorch index, remove the CUDA-13 packages, then force-reinstall every
``nvidia-*-cu12`` / ``cuda-*`` / ``triton`` package, because uninstalling
the CUDA-13 packages deleted shared library files (``libcudnn.so.9`` ...)
the cu12 packages also own. Verified: CUDA available on the A100,
vesin_torch with GPU neighbour lists, mace, pymdi, ``pip check`` clean,
``lammps-mdi check`` green.

Prevention, on seamm_manager dev (unreleased). A first attempt, a guard
that skipped any environment not the plug-in's own, was wrong and was
removed: xnn-step is *meant* to add the MLFF engine (xnns, e3nn, torch) into
LAMMPS's environment through xnn.ini. The defect is only that conda applies
a file's pip section with ``-U``. ``Conda.update_environment`` now applies
the conda part with conda and the pip part itself: a bare name such as
``torch`` is installed only if missing, a requirement with a specifier such
as ``xnns>=0.3.0`` is upgraded within it. Proven on a throwaway
environment. Until that is released, do not run ``update --all`` on a
machine whose code ``.ini`` files share an environment.
