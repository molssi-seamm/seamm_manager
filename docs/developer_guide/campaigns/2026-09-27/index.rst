2026-09-27 -- Several SEAMM installations side by side
======================================================

Status (2026-09-27): **phase 1 released** (seamm_util 2026.9.27, seamm_jobserver
2026.9.27, seamm_manager 2026.9.27.4; all on this Mac and paul.local). **Phase 2 released** (2026-09-27): seamm_util 2026.9.27.1 (``current_root``,
``installation_path``), seamm_exec 2026.9.27 (D8), seamm 2026.9.27 (data path,
dashboards.ini, Open dialog), vasp_step 2026.9.27, forcefield_step 2026.9.27,
xnn_step 2026.9.27.1 and seamm_thermochemistry 2026.9.27. Phases 3 and 4 need the
answers to the open questions below.

**Phase 2 decision:** reference data follows the rule *the installation's own copy
under its root if it has one, else the default installation's in ~/SEAMM*
(``seamm_util.installation_path``), so a second installation works without copying
the VASP potentials, forcefields, models or the thermochemistry database, and can
still override any of them. Left as they are, after checking: dftbplus_step (its
``~/SEAMM`` path is only a maintainer script's default; the Slater-Koster files ship
in the package); atomic_charges_step (the directory is used only if it holds the
DDEC6 densities, else the chargemol conda environment's copy); comments and messages
in lammps_step and orca_step; seamm_webui's own ``--root`` default (its services always
pass ``--root``). Found beyond the plan: seamm's ``Flowchart.data_path`` and
``dashboards.ini`` lookup, spelled ``Path.home() / "SEAMM"`` rather than ``~/SEAMM``.
Loose end: seamm_thermochemistry's installer ``update`` re-downloads the Zenodo
database over the configured file without checking for local changes (it overwrote
the Mac's curated copy on 2026-09-27; Paul chose to keep the Zenodo version). The decisions under *Open
questions* are Paul's and are needed before phase 3.

**Caution for the release of seamm_jobserver#23:** a JobServer whose root has no code
``.ini`` files will make its jobs fail once it passes ``--root``. On the Mac that is
``dev_jobserver`` (``--root ~/SEAMM_DEV``, conda ``seamm-dev``), which must not get the
new JobServer until ``~/SEAMM_DEV`` holds the code ``.ini`` files (phase 5). The
single-root installations (``~/SEAMM`` everywhere, ChemAI, MolSSI10) are unaffected.

Goal
----

Any number of SEAMM installations can live on one machine for one user -- production
in ``~/SEAMM``, development in ``~/SEAMM_DEV``, a trial of a new release in
``~/SEAMM_NEW`` -- each using its own configuration, data and jobs, with its own
services and desktop apps, and none able to change another's software by accident.
Converting ``~/SEAMM_DEV`` to a uv environment is the first use.

What happens today
------------------

Checked in the code on 2026-09-27.

**The root is effectively hardwired.** The shared argument parser
(``seamm_util/argument_parser.py``) defaults ``--root`` to ``~/SEAMM``; the only other
source is ``[SEAMM] root`` in ``~/.seamm.d/seamm.ini``, which is per user and so cannot
differ between installations (it is commented out on Paul's machines). Only
``xnn_step`` reads a ``SEAMM_ROOT`` variable.

**Jobs never see their JobServer's root.** ``dev_jobserver`` runs with ``--root
~/SEAMM_DEV`` and uses it for its own queue file and the Jobs database, but it starts
each job as ``run_from_jobserver <id> <dir> <db>`` with no ``--root``
(``seamm_jobserver/jobserver.py``, ``_build_cmd``). The job therefore reads
``~/SEAMM/mopac.ini``, ``lammps.ini`` and so on: every step takes its code's ini from
``seamm_options["root"]``. ``~/SEAMM_DEV`` accordingly holds Jobs, logs and the
JobServer's queue file, and no code ini files. The GUI started from the development
environment also defaults to ``~/SEAMM``.

**The plug-ins' installers write to ~/SEAMM.** ``InstallerBase.root`` (shipped in
seamm_manager) takes the root from the shared ``seamm.ini`` or falls back to
``~/SEAMM``, and ``run_plugin_installer`` does not pass the manager's root. So
``seamm-manager --root X install`` puts the Python packages in ``X/venv`` but the code
ini files in ``~/SEAMM``.

**Some steps hardwire ~/SEAMM directly**, ignoring the root option:

- ``vasp_step``: ``~/SEAMM/Parameters/VASP`` (``vasp.py``, ``tk_energy.py``);
- ``dftbplus_step``: ``~/SEAMM/Parameters/slako`` (``slako.py``) and the installer's
  message;
- ``atomic_charges_step``: default ``~/SEAMM/atomic_charges/atomic_densities``;
- ``forcefield_step`` and ``xnn_step``: the ``local:`` data directory
  ``~/SEAMM/data/Forcefields``;
- ``seamm``: the GUI's default flowcharts folder ``~/SEAMM/flowcharts``
  (``tk_open.py``);
- ``seamm_thermochemistry``: the thermochemistry database path in its docs and
  installer.

**Credentials are chosen by the word "dev".** ``seamm_exec``'s ``open_datastore``
uses the ``[Dashboard: dev]`` section of ``seammrc`` when the root contains "dev".

**The manager knows two installations, not N.** Service names are ``jobserver`` or
``dev_jobserver``, apps ``SEAMM`` or ``SEAMM-dev``, service bundles
``SEAMM-JobServer`` or ``SEAMM-JobServer-dev``, all keyed on ``--development`` rather
than the root. ``--root ~/SEAMM_NEW services create --force jobserver`` would replace
production's JobServer, and ``apps create`` would overwrite production's SEAMM.app.
The web interface's default port is 55055, or 55155 with ``--development``.

**Every installation shares the codes' conda environments.** ``seamm-lammps``,
``seamm-mopac`` and the others have fixed names. A second installation's ``install``
or ``update`` runs the plug-ins' installers against those same environments -- which
is how production's torch and xnns were changed on 2026-09-27 (see
``../2026-09-25/NOTES_phase4.rst``).

**Finding commands.** The JobServer finds ``run_from_jobserver`` beside its own
interpreter; services and apps use absolute paths; external codes come from the ini
files. These are already correct per installation once the root is. The user's shell
is different: ``seamm``, ``run_flowchart`` and the ``#!/usr/bin/env run_flowchart``
line of flowcharts resolve through ``PATH``, so whichever venv is first wins.

Design
------

**D1. The root comes from the installation.** The default for ``--root`` becomes, in
order: the command-line option; ``SEAMM_ROOT`` if set; the directory holding the
running venv when it looks like a SEAMM root (``sys.prefix`` is ``<X>/venv`` and ``X``
holds ``Jobs`` or ``*.ini``); otherwise ``~/SEAMM``. So anything run from
``~/SEAMM_DEV/venv`` -- GUI, ``run_flowchart``, JobServer, jobs, installers --
defaults to ``~/SEAMM_DEV`` with no configuration. ``[SEAMM] root`` in the per-user
``seamm.ini`` is no longer honoured (one value cannot serve several installations); a
warning says so if it is set. ``~/.seamm.d`` stays shared on purpose: credentials,
personal data (``personal:`` forcefields and models) and user preferences.

**D2. The JobServer passes its root to every job**, adding ``--root`` to the
``run_from_jobserver`` command, so a job can never disagree with the JobServer that
started it, whatever D1 infers.

**D3. The manager tells the plug-ins' installers its root**, through ``SEAMM_ROOT`` in
their environment, and ``InstallerBase.root`` uses it. The code ini files then land in
the installation being worked on.

**D4. No hardwired ~/SEAMM in the steps.** Each place listed above takes the root
option instead (the ``local:`` data source becomes ``<root>/data``, and so on).

**D5. Names follow the installation.** The installation's *tag* is empty for
``~/SEAMM`` and otherwise the root's directory name, case kept (``SEAMM_DEV``,
``SEAMM_NEW``), overridable with ``--name``. Services become ``jobserver`` /
``jobserver-SEAMM_NEW``, apps ``SEAMM`` / ``SEAMM (SEAMM_NEW)``, bundles
``SEAMM-JobServer`` / ``SEAMM-JobServer-SEAMM_NEW``, and the manager's window title
shows the tag. ``--development`` stays, as shorthand for ``--root ~/SEAMM_DEV`` plus
the development tools; ``~/SEAMM_DEV`` gets the same naming as any other root (no
legacy ``dev_jobserver`` / ``SEAMM-dev`` names -- nothing outside the manager uses
them). Instead, creating a service stops and replaces any existing SEAMM service
started with the same ``--root``, whatever its name, so an old ``dev_jobserver`` (or
a hand-made one) can never run beside the new one on the same datastore.
``services status --all`` lists every installation's services.

**D6. A code-environment policy per installation**, recorded in
``<root>/seamm.ini`` (``[SEAMM] code-environments``):

- ``own`` -- the plug-ins create and update the codes' environments as now. The
  default for ``~/SEAMM``.
- ``shared`` -- the installers never create or update a conda environment; they write
  ini files pointing at the existing ones (copying ``~/SEAMM``'s ini as the template)
  and report a code that is missing. The default for any other new root, so a trial
  installation cannot change production's codes.
- ``prefixed`` -- own copies named ``seamm-<tag>-lammps`` and so on, for testing new
  versions of the codes themselves.

``InstallerBase`` enforces it, in one place for every plug-in.

**D7. Ports per installation.** ``services create webui`` picks the first free port
from 55055 upwards unless ``--port`` is given, and records it in the service
definition as now.

**D8. Credentials by installation.** ``open_datastore`` looks for ``[Dashboard:
<tag>]`` (then ``localhost`` and the host name as now) instead of testing for "dev".

**D9. Shells.** The documentation recommends putting no SEAMM venv on ``PATH``
permanently, and using ``source <root>/venv/bin/activate`` for a terminal that should
use a particular installation; the apps and services never depend on ``PATH``.
The manager's ``environment show`` prints the activation command.

Phases
------

1. **Root** (seamm_util, seamm_jobserver, seamm_manager): D1, D2, D3. Tests for the
   precedence order, including a venv that is not in a SEAMM root. Release the three;
   production behaviour is unchanged because ``~/SEAMM/venv`` infers ``~/SEAMM``.
2. **Steps** (vasp_step, dftbplus_step, atomic_charges_step, forcefield_step,
   xnn_step, seamm, seamm_thermochemistry, seamm_exec): D4 and D8. Each a small
   release; each plug-in considered on its own (its data layout and installer), not a
   blanket search-and-replace.
3. **Manager naming and ports** (seamm_manager): D5, D7, including the GUI's Shortcuts
   and Services tabs. Tests that two roots produce distinct service, app and bundle
   names, and that ``~/SEAMM_DEV`` keeps its legacy names.
4. **Code-environment policy** (seamm_manager's ``InstallerBase``): D6, with tests
   that a ``shared`` installation's install and update never call conda to create or
   update an environment.
5. **Convert ~/SEAMM_DEV** on the Mac: ``seamm-manager --development install --all
   development``; copy the code ini files from ``~/SEAMM`` (policy ``shared``, the
   same conda environments); ``make install`` the working checkouts into
   ``~/SEAMM_DEV/venv``; recreate ``dev_jobserver`` and ``dev_webui`` through the
   manager; run a job through the development JobServer and check it reads
   ``~/SEAMM_DEV``'s ini files. Retire the conda ``seamm-dev`` environment when
   satisfied.
6. **Trial installation**: create ``~/SEAMM_NEW`` on paul.local, run jobs against
   production's codes, remove it (``environment remove``, ``services delete``, ``apps
   delete``) and check production is untouched throughout. Then document the pattern
   in the user guide ("Trying a new release beside production").

Phases 1 and 2 fix the root cause and are useful on their own; 3 and 4 are what make a
third installation safe. Phase 5 needs 1 and 3 (and 2 for VASP, DFTB+ and the atomic
densities); phase 6 needs everything.

Risks
-----

- **Inference picks the wrong root.** A venv outside any SEAMM root (a developer's
  test venv) must fall back to ``~/SEAMM``, not guess; D2 makes jobs immune regardless.
  The marker test (``Jobs`` or ``*.ini`` beside ``venv``) is deliberately strict.
- **Users relying on ``[SEAMM] root``** in ``seamm.ini``. Keep honouring it for one
  release with a deprecation warning, then drop it; ``SEAMM_ROOT`` replaces it.
- **Older plug-ins** still hardwiring ``~/SEAMM`` after phase 1 behave as today (they
  read production's data), which is no worse; phase 2 fixes them.
- **ChemAI** runs its production as the ``seamm`` user with a single root and shared
  code environments that other work also uses. Nothing here changes a single-root
  installation, and it stays hands-off until Paul asks.

Decisions (Paul, 2026-09-27)
----------------------------

1. New non-default roots default to the ``shared`` code-environment policy.
2. Tags keep the directory's case (``SEAMM_NEW``) in service, app and bundle names.
3. ``--development`` stays.
4. ``update --all`` in a ``shared`` installation runs the plug-ins' installers in a
   report-only mode: it reports missing codes and never creates or updates a conda
   environment.
5. No legacy ``dev_`` names; replace any service with the same ``--root`` instead
   (D5).

Also for phase 3's manager release: ``update --latest`` asked PyPI's JSON API, which
on 2026-09-27 returned a stale CDN copy to Python's ``requests`` (``X-Cache: MISS,
HIT, HIT``) while curl and the simple index saw the new release. Use the simple
(PEP 691) index that uv installs from instead, with ``Cache-Control: no-cache``.
