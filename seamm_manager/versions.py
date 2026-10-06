# -*- coding: utf-8 -*-

"""Versioned environments: build a new one beside the current, switch, prune.

The rule this module enforces: **a running job never sees a half-updated
environment**. SEAMM imports lazily in places, so updating ``<root>/venv`` in
place while a job runs can mix two versions inside one process. Instead an
update builds ``<root>/venvs/<stamp>`` from the current environment, applies
the change there, and switches the ``venv`` link. Processes started from the
old environment keep it until ``prune`` finds nothing using it.

Processes that were started *through the link* (``<root>/venv/bin/...``) are
the exception: CPython does not resolve the link when locating a venv, so
they would follow it to the new environment. `unsafe_processes` finds them
and `switch` refuses while any exist, unless forced. After the first
migration every launcher embeds the real path, so this only matters for jobs
that were already running then.
"""

from datetime import datetime, timedelta
import logging
from pathlib import Path
import shutil
import tempfile

from . import my
from .uv import UvError

logger = logging.getLogger(__name__)

# Set when this run switched environments, so update() need not restart the
# services a second time.
switched = False
# Set when a build put the manager's own release into the new environment, so the
# callers' sync_manager() must not touch the current environment afterwards.
synced_manager = False
# Set when a change was built but not switched to (a regression, or processes
# started through the link), so install and update exit non-zero.
refused = False


# ---- processes --------------------------------------------------------------


def processes_using(prefix):
    """The processes whose executable or command line names a path under `prefix`.

    Parameters
    ----------
    prefix : str or pathlib.Path
        A directory; matched as ``str(prefix) + "/"``.

    Returns
    -------
    [(pid, str)]
        The pid and a short description (name plus the matching argument).
    """
    import psutil

    prefix = str(prefix).rstrip("/") + "/"
    result = []
    for process in psutil.process_iter(attrs=["pid", "name", "cmdline", "exe"]):
        info = process.info
        candidates = list(info.get("cmdline") or [])
        if info.get("exe"):
            candidates.append(info["exe"])
        matches = [t for t in candidates if t and t.startswith(prefix)]
        if matches:
            # The last match is the most telling: the script, not the interpreter
            result.append((info["pid"], f"{info.get('name') or '?'}: {matches[-1]}"))
    return result


def unsafe_processes():
    """Processes started through the ``venv`` link rather than a real path."""
    if not my.uv.path.is_symlink():
        return []
    return processes_using(my.uv.path)


def _print_processes(processes, heading):
    print(heading)
    for pid, text in processes:
        print(f"    {pid:>7}  {text}")


# ---- migration ----------------------------------------------------------------


def ensure_versioned(relink=True):
    """Make the installation versioned if it is not yet. Returns True if migrated.

    Renaming the directory is safe while jobs run (the inodes do not change). The
    launchers are then rewritten to the real path and running services
    restarted, so that from here on nothing new is started through the link.
    """
    if my.uv.is_versioned or not my.uv.exists:
        return False
    name = my.uv.migrate_to_versioned()
    if name is None:
        return False
    print(f"Moved the environment to {my.uv.versions_dir / name};")
    print(f"{my.uv.path} links to it.")
    if relink:
        relink_launchers()
    return True


def relink_launchers():
    """Point this installation's services and apps at the environment's real path.

    Running services are restarted so they run from it; stopped ones stay stopped.
    """
    from .services import relink_services
    from .apps import relink_apps

    try:
        restarted = relink_services()
    except Exception as e:  # services may be absent, or the platform unsupported
        logger.info(f"Could not relink the services: {e}")
        restarted = []
    try:
        relinked = relink_apps()
    except Exception as e:
        logger.info(f"Could not relink the apps: {e}")
        relinked = []
    if restarted:
        print(f"Restarted {', '.join(restarted)} from {my.uv.real_path}.")
    if relinked:
        print(f"Updated the apps {', '.join(relinked)} to run from {my.uv.real_path}.")


# ---- building and switching --------------------------------------------------


def _free_version_name(current, moment):
    """The first version name from `moment` on that is not taken.

    A fresh installation moves its environment into ``venvs/<now>`` and builds
    the next version within the same second, which would otherwise collide.
    Names stay times, which pruning reads.
    """
    name = current.new_version_name(moment)
    while current.version(name).path.exists():
        moment += timedelta(seconds=1)
        name = current.new_version_name(moment)
    return name


def build_version(specs, constraints=None, upgrade=False, from_freeze=True, name=None):
    """Build a new versioned environment and return its ``Uv``.

    Parameters
    ----------
    specs : [str]
        Requirement specifiers to install or upgrade, as `Uv.install` takes.
    constraints : pathlib.Path = None
        The lock file, if any.
    upgrade : bool = False
        Whether `specs` may move versions (an update) or only fill gaps.
    from_freeze : bool = True
        Start from an exact copy of the current environment (``uv pip freeze``,
        which keeps editable and local installs), then apply `specs`; the result
        is what an in-place update would have produced. False builds from
        scratch with only `specs` -- the clean rebuild ``recreate`` wants.
    name : str = None
        The version's name; default from the time.
    """
    current = my.uv
    if name is None:
        name = _free_version_name(current, datetime.now())
    new = current.version(name)
    if new.path.exists():
        raise UvError(f"{new.path} already exists.")
    print(f"Building the new environment {new.path}")
    new.create(python_version=current.python_version)

    if from_freeze and current.exists:
        # The packages being changed are left out of the copy, so that their new
        # versions replace the old pins (seamm_manager#34)
        from .uv import _requirement_names, freeze_without

        freeze = freeze_without(current.freeze(), _requirement_names(specs or []))
        if freeze.strip():
            with tempfile.NamedTemporaryFile(
                "w", suffix="-freeze.txt", delete=False
            ) as fd:
                fd.write(freeze)
                frozen = Path(fd.name)
            try:
                print("   copying the current environment's packages")
                new.run("pip", "install", "--python", new.python, "-r", frozen)
            finally:
                frozen.unlink(missing_ok=True)

    if specs:
        print(f"   applying {len(specs)} change(s)")
        new.install(specs, constraints=constraints, upgrade=upgrade)
    return new


def switch(new, force=False):
    """Make `new` the current environment and relink the launchers.

    Refuses if processes started through the link exist (see the module
    docstring), unless `force`. Returns True if switched.
    """
    global switched

    unsafe = unsafe_processes()
    if unsafe and not force:
        _print_processes(
            unsafe,
            f"These processes were started through {my.uv.path} and would see the "
            "new environment if it were switched now:",
        )
        print(
            f"The new environment is ready at {new.path}. Wait for them to finish, "
            "then run 'seamm-manager environment switch', or use --force."
        )
        return False
    my.uv.switch_to(new.real_path)
    switched = True
    print(f"{my.uv.path} now links to {new.path.name}")
    relink_launchers()
    return True


def apply_change(specs, constraints=None, upgrade=False, in_place=None):
    """Install or update `specs` in the installation's environment, safely.

    With an existing environment (and not `in_place`), builds a new version from
    the current one, applies the change there and switches. Otherwise, or for a
    fresh install, installs into the environment directly.

    Returns True if the change is now in the current environment (installed in
    place, or built and switched), False if it was built but the switch was
    refused (see `switch`). The caller records the snapshot afterwards.
    """
    if in_place is None:
        in_place = bool(getattr(my.options, "in_place", False))
    if not my.uv.exists or in_place:
        my.uv.install(specs, constraints=constraints, upgrade=upgrade)
        return True

    global synced_manager

    ensure_versioned()
    new = build_version(specs, constraints=constraints, upgrade=upgrade)
    # The manager's own release goes into the new environment as part of the
    # build, never into the current one (which may be in use)
    from .util import sync_manager

    saved, my.uv = my.uv, new
    try:
        sync_manager()
    finally:
        my.uv = saved
    synced_manager = True
    global refused

    problems = regressions(my.uv, new, specs)
    if problems:
        print(
            f"The new environment {new.path.name} was built but NOT switched to:\n"
            + "\n".join(f"    {line}" for line in problems)
            + "\nNothing has changed in the current environment. To take the newest "
            "releases instead, use 'seamm-manager update --latest <packages>' (or "
            "'--no-constraints'); to use the new environment anyway, 'seamm-manager "
            f"environment switch {new.path.name}'."
        )
        refused = True
        return False
    if not switch(new, force=bool(getattr(my.options, "force", False))):
        refused = True
        return False
    return True


def regressions(current, new, specs=(), removing=()):
    """What the new environment version would break, compared to the current one.

    A package moved to an older version that was not asked for, a package removed
    that was not in `removing`, or an installed package's requirements newly unmet
    (seamm_manager#34). An explicit pin in `specs` (``name==version``) to an older
    version is allowed.

    Returns
    -------
    [str]
        One line per problem; empty if the new version is safe to switch to.
    """
    from packaging.utils import canonicalize_name
    from packaging.version import InvalidVersion, Version

    from .uv import Requirement

    requested = set()
    for spec in specs or ():
        try:
            requirement = Requirement(str(spec))
        except Exception:
            continue
        if any(s.operator in ("==", "===") for s in requirement.specifier):
            requested.add(canonicalize_name(requirement.name))

    before = {canonicalize_name(k): v["version"] for k, v in current.list().items()}
    after = {canonicalize_name(k): v["version"] for k, v in new.list().items()}
    problems = []
    removing = {canonicalize_name(name) for name in removing}
    for name in sorted(before.keys() - after.keys() - removing):
        problems.append(f"{name} {before[name]} would be removed")
    for name in sorted(before.keys() & after.keys()):
        if name in requested:
            continue
        try:
            older = Version(after[name]) < Version(before[name])
        except InvalidVersion:
            continue
        if older:
            problems.append(
                f"{name} would go back from {before[name]} to {after[name]}"
            )
    old_conflicts = set(current.report_conflicts(quiet=True).splitlines())
    for line in new.report_conflicts(quiet=True).splitlines():
        if line not in old_conflicts:
            problems.append(f"newly unmet: {line.strip()}")
    return problems


# ---- prune and rollback ------------------------------------------------------


def _created(path):
    try:
        return datetime.strptime(path.name, "%Y-%m-%dT%H-%M-%S")
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime)


def prune(keep=2, min_age_days=1.0, dry_run=False):
    """Remove old versions that nothing uses.

    Keeps the current version and the newest `keep` versions in all (for
    rollback), anything younger than `min_age_days`, and anything a running
    process uses. Returns the paths removed (or that would be, with `dry_run`).
    """
    if not my.uv.is_versioned:
        print("The environment is not versioned; nothing to prune.")
        return []
    current = my.uv.real_path
    versions = [path for _, path in my.uv.versions()]
    newest = set(versions[-keep:]) if keep > 0 else set()
    cutoff = datetime.now() - timedelta(days=min_age_days)
    removed = []
    for path in versions:
        if path == current or path in newest:
            continue
        if _created(path) > cutoff:
            print(f"Keeping {path.name}: younger than {min_age_days} day(s).")
            continue
        users = processes_using(path)
        if users:
            _print_processes(users, f"Keeping {path.name}: in use by")
            continue
        size = _size(path)
        if dry_run:
            print(f"Would remove {path.name} ({size}).")
        else:
            print(f"Removing {path.name} ({size}).")
            shutil.rmtree(path)
        removed.append(path)
    if not removed:
        print("Nothing to prune.")
    return removed


def rollback(name=None, force=False):
    """Switch back to the version `name`, by default the one before the current."""
    if not my.uv.is_versioned:
        print("The environment is not versioned; there is nothing to roll back to.")
        return False
    versions = [path for _, path in my.uv.versions()]
    current = my.uv.real_path
    if name is None:
        older = [p for p in versions if p.name < current.name]
        if not older:
            print("There is no older version to roll back to.")
            return False
        target = older[-1]
    else:
        target = my.uv.versions_dir / name
        if target not in versions:
            names = ", ".join(p.name for p in versions)
            print(f"There is no version '{name}'. Versions: {names}")
            return False
    if target == current:
        print(f"{target.name} is already the current version.")
        return False
    return switch(my.uv.version(target.name), force=force)


def _size(path):
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            pass
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if total < 1000:
            return f"{total:.0f} {unit}" if unit == "B" else f"{total:.1f} {unit}"
        total /= 1000
    return f"{total:.1f} PB"
