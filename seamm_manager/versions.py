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
and `switch` refuses while any exist, unless forced or the user agrees when
asked (`confirm_switch`). After the first migration every launcher embeds the
real path, so this only matters for jobs that were already running then -- and
for servers that are always running, such as the flowchart MCP servers
(``seamm-flowchart mcp``) of Claude sessions. Those import everything when they
start and only pick up a new environment when restarted, so they do not block a
switch.
"""

from datetime import datetime, timedelta
import getpass
import json
import logging
import os
from pathlib import Path
import shutil
import sys
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
# Asked whether to go ahead although a switch was refused:
# ``confirm_switch(question, details) -> bool``, `details` being lines to show. The
# GUI sets a dialog; without one a terminal user is asked, and anything else (a
# script, a service) refuses, as before -- scripts use --force.
confirm_switch = None
#: Servers started through the link that do not block a switch: (program, argument).
SWITCH_SAFE = (("seamm-flowchart", "mcp"),)
#: The SEAMM GUI (the flowchart editor), so the user can be told to close it.
GUI_PROGRAMS = ("seamm", "SEAMM")


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
    # Never this process or what started it (the manager itself, run as
    # <root>/venv/bin/seamm-manager, would otherwise block its own switch)
    me = {os.getpid()}
    try:
        me.update(parent.pid for parent in psutil.Process().parents())
    except Exception:
        pass
    result = []
    for process in psutil.process_iter(attrs=["pid", "name", "cmdline", "exe"]):
        info = process.info
        if info.get("pid") in me:
            continue
        candidates = list(info.get("cmdline") or [])
        if info.get("exe"):
            candidates.append(info["exe"])
        matches = [t for t in candidates if t and t.startswith(prefix)]
        if matches:
            # The last match is the most telling: the script, not the interpreter,
            # with its arguments (e.g. "seamm-flowchart mcp")
            text = matches[-1]
            cmdline = list(info.get("cmdline") or [])
            if text in cmdline:
                rest = cmdline[cmdline.index(text) + 1 :]
                text = " ".join([text] + rest)[:200]
            result.append((info["pid"], f"{info.get('name') or '?'}: {text}"))
    return result


def is_switch_safe(description):
    """Whether a process (as `processes_using` describes it) may run on while
    the link is switched: a long-lived server that imported everything when it
    started, e.g. the flowchart MCP server of a Claude session."""
    words = description.split(": ", 1)[-1].split()
    for i, word in enumerate(words):
        for program, argument in SWITCH_SAFE:
            if Path(word).name == program and argument in words[i + 1 :]:
                return True
    return False


def is_gui(description):
    """Whether a process (as `processes_using` describes it) is the SEAMM GUI."""
    words = description.split(": ", 1)[-1].split()
    return bool(words) and Path(words[0]).name in GUI_PROGRAMS


def linked_processes():
    """Processes started through the ``venv`` link rather than a real path."""
    path = getattr(my.uv, "path", None)
    if path is None or not Path(path).is_symlink():
        return []
    return processes_using(path)


def unsafe_processes():
    """Processes started through the ``venv`` link that a switch would disturb:
    all of them except the switch-safe servers (`is_switch_safe`)."""
    return [p for p in linked_processes() if not is_switch_safe(p[1])]


def ask(question, details=()):
    """Ask whether to go ahead: through `confirm_switch` if set (the GUI), else
    on a terminal; False when there is no one to ask."""
    if confirm_switch is not None:
        return bool(confirm_switch(question, list(details)))
    try:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        interactive = False
    if not interactive:
        return False
    try:
        answer = input(f"{question} [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


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


def build_version(
    specs,
    constraints=None,
    upgrade=False,
    from_freeze=True,
    name=None,
    current=None,
    new=None,
):
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
    current : Uv = None
        The environment to start from; default the installation's.
    new : Uv = None
        Where to build, created relocatable (archive storage builds on local disk);
        default ``<root>/venvs/<name>``.
    """
    if current is None:
        current = my.uv
    if new is None:
        if name is None:
            name = _free_version_name(current, datetime.now())
        new = current.version(name)
        relocatable = False
    else:
        relocatable = True
    if new.path.exists():
        raise UvError(f"{new.path} already exists.")
    print(f"Building the new environment {new.path}")
    if relocatable:
        new.create(python_version=current.python_version, relocatable=True)
    else:
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


def blocking_question(unsafe, action="update"):
    """The heading, the question and the lines to show for processes that hold
    back a switch, naming the SEAMM GUI when it is one of them."""
    heading = (
        f"These programs were started through {my.uv.path} and would see the new "
        "environment if it were switched now:"
    )
    details = [heading] + [f"{pid}  {text}" for pid, text in unsafe]
    if any(is_gui(text) for _, text in unsafe):
        question = (
            f"SEAMM is open (started from a terminal through {my.uv.path}). Close "
            f"SEAMM and {action} again, or {action} anyway? Going ahead is usually "
            "safe: running programs keep the code they have already loaded, and pick "
            "up the new version when restarted."
        )
    else:
        question = (
            f"{action.capitalize()} anyway? It is usually safe: running programs keep "
            "the code they have already loaded, and pick up the new version when "
            "restarted."
        )
    return heading, question, details


def check_switch(force=False, already=(), action="update"):
    """Whether the link may be switched now: no program started through it
    would see the change, or the user agrees (`ask`), or `force`.

    Returns (ok, agreed): `agreed` are the pids already accepted, so a second
    check (at the switch, after a build) asks only about new ones.
    """
    agreed = set(already)
    unsafe = [p for p in unsafe_processes() if p[0] not in agreed]
    if not unsafe or force:
        return True, agreed | {pid for pid, _ in unsafe}
    heading, question, details = blocking_question(unsafe, action)
    _print_processes(unsafe, heading)
    if ask(question, details):
        print("Going ahead anyway, as asked.")
        return True, agreed | {pid for pid, _ in unsafe}
    return False, agreed


def switch(new, force=False, agreed=()):
    """Make `new` the current environment and relink the launchers.

    Refuses if processes started through the link exist (see the module
    docstring), unless `force` or the user agrees when asked; `agreed` are pids
    already accepted. Returns True if switched.
    """
    global switched

    ok, _ = check_switch(force, already=agreed, action="switch")
    if not ok:
        print(
            f"The new environment is ready at {new.path}. Close or wait for those "
            "programs, then run 'seamm-manager environment switch', or use --force."
        )
        return False
    old = my.uv.real_path
    servers = safe_servers()
    my.uv.switch_to(new.real_path)
    switched = True
    print(f"{my.uv.path} now links to {new.path.name}")
    if servers:
        print(
            f"{len(servers)} flowchart MCP server(s) keep the previous environment "
            "until they are restarted (in Claude Code: /mcp to reconnect)."
        )
    guis = [p for p in processes_using(old) if is_gui(p[1])]
    if guis:
        print(
            "SEAMM is open and keeps the previous version until it is closed and "
            "opened again."
        )
    # With archive storage the jobs' archive follows (rollback, switch by hand)
    from . import venv_archives

    if venv_archives.enabled():
        venv_archives.follow(new.real_path.name)
    relink_launchers()
    return True


def safe_servers():
    """The switch-safe servers started through the ``venv`` link."""
    return [p for p in linked_processes() if is_switch_safe(p[1])]


def discard(new):
    """Remove a version that was built but will not be used, so nothing unused
    is left behind."""
    try:
        path = Path(new.path)
        if path.resolve() == Path(my.uv.real_path).resolve():
            return
        if path.parent.resolve() != Path(my.uv.versions_dir).resolve():
            return
    except (AttributeError, TypeError):
        return  # not a real environment version
    shutil.rmtree(path, ignore_errors=True)
    print(f"Removed the unused new environment {path.name}.")


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
    from . import venv_archives

    if my.uv.exists and venv_archives.enabled():
        if in_place:
            print(
                "The SEAMM environment is stored as an archive here, so changes are "
                "never made in place; building a new version instead."
            )
        return venv_archives.apply_change(
            specs, constraints=constraints, upgrade=upgrade
        )
    if not my.uv.exists or in_place:
        my.uv.install(specs, constraints=constraints, upgrade=upgrade)
        return True

    global synced_manager
    global refused

    # Before building anything: would the switch be held back? If the user does
    # not want to go ahead, nothing is built and nothing changes.
    force = bool(getattr(my.options, "force", False))
    ok, agreed = check_switch(force)
    if not ok:
        print(
            "Nothing was changed. Close those programs or wait for them to finish, "
            "then run the command again (or use --force)."
        )
        refused = True
        return False

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

    problems = regressions(my.uv, new, specs)
    if problems:
        print(
            "The new environment would make these changes, which look like going "
            "backwards:\n" + "\n".join(f"    {line}" for line in problems)
        )
        if not ask("Use the new environment anyway?", problems):
            discard(new)
            print(
                "Nothing has changed. To take the newest releases instead, use "
                "'seamm-manager update --latest <packages>' (or '--no-constraints')."
            )
            refused = True
            return False
        print("Using the new environment anyway, as asked.")
    if not switch(new, force=force, agreed=agreed):
        discard(new)
        print("Nothing has changed.")
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


#: The file that pins a version: prune never removes it while the file exists
PIN_FILE = ".seamm-pin"


def pin(path, reason=""):
    """Pin a version so that prune keeps it, e.g. for jobs that name it directly.

    Parameters
    ----------
    path : pathlib.Path
        The version's directory.
    reason : str
        Why it is pinned, shown by ``environment versions`` and prune.
    """
    data = {
        "reason": reason,
        "since": datetime.now().isoformat(timespec="seconds"),
        "by": getpass.getuser(),
    }
    (Path(path) / PIN_FILE).write_text(json.dumps(data, indent=1) + "\n")
    return data


def unpin(path):
    """Remove a version's pin; returns whether it was pinned."""
    pin_path = Path(path) / PIN_FILE
    if pin_path.exists():
        pin_path.unlink()
        return True
    return False


def pin_info(path):
    """The pin of a version ({"reason", "since", "by"}), or None if it is not pinned."""
    pin_path = Path(path) / PIN_FILE
    if not pin_path.exists():
        return None
    try:
        return json.loads(pin_path.read_text())
    except Exception:
        return {"reason": "(unreadable pin file)", "since": "", "by": ""}


def _created(path):
    try:
        return datetime.strptime(path.name, "%Y-%m-%dT%H-%M-%S")
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime)


def prune(keep=2, min_age_days=1.0, dry_run=False):
    """Remove old versions that nothing uses.

    Keeps the current version and the newest `keep` versions in all (for
    rollback), anything younger than `min_age_days`, anything pinned (see
    :func:`pin`), and anything a running process on this machine uses. A job on
    another node of a cluster is not seen here, so a version that such jobs
    name directly must be pinned. Returns the paths removed (or that would be,
    with `dry_run`).
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
        pinned = pin_info(path)
        if pinned is not None:
            why = f": {pinned['reason']}" if pinned.get("reason") else ""
            print(f"Keeping {path.name}: pinned{why}.")
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
