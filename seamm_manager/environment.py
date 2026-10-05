# -*- coding: utf-8 -*-

"""The 'environment' command: create, show, recreate or remove the uv-managed
Python environment that holds SEAMM."""

from . import my
from .uv import DEFAULT_PYTHON


def setup(parser):
    """Define the command-line interface for the environment.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The main parser for the application.
    """
    subparser = parser.add_parser(
        "environment",
        help="Create, show, recreate or remove the Python environment for SEAMM.",
    )
    subsubparser = subparser.add_subparsers()

    tmp = subsubparser.add_parser("show", help="Show the environment.")
    tmp.set_defaults(func=show)

    tmp = subsubparser.add_parser(
        "create", help="Create the environment if it does not exist."
    )
    tmp.set_defaults(func=create)
    tmp.add_argument(
        "--python",
        default=DEFAULT_PYTHON,
        help="The Python version to install, default %(default)s",
    )

    tmp = subsubparser.add_parser(
        "recreate",
        help=(
            "Build a fresh environment from scratch with the SEAMM packages that are "
            "in the current one, then switch to it; the old one stays until pruned. "
            "The cure for most environment problems."
        ),
    )
    tmp.set_defaults(func=recreate)
    tmp.add_argument(
        "--python",
        default=DEFAULT_PYTHON,
        help="The Python version to install, default %(default)s",
    )
    tmp.add_argument(
        "--force",
        action="store_true",
        help="Switch even if processes started through <root>/venv exist.",
    )
    tmp.add_argument(
        "--latest",
        action="store_true",
        help=(
            "Each package's newest release on PyPI, not the published package "
            "list's, which lags a release by up to a day (as update --latest)."
        ),
    )

    tmp = subsubparser.add_parser("remove", help="Delete the environment.")
    tmp.set_defaults(func=remove)

    tmp = subsubparser.add_parser(
        "versions", help="List the versioned environments and what uses them."
    )
    tmp.set_defaults(func=versions)

    tmp = subsubparser.add_parser(
        "migrate",
        help=(
            "Make the environment versioned: move <root>/venv to <root>/venvs/<stamp>, "
            "link venv to it, and point the services and apps at the real path. "
            "Safe while jobs run. Updates do this themselves."
        ),
    )
    tmp.set_defaults(func=migrate)

    tmp = subsubparser.add_parser(
        "switch",
        help=(
            "Switch to a version built earlier (e.g. by an update that could not "
            "switch because jobs started through venv/ were still running)."
        ),
    )
    tmp.set_defaults(func=switch)
    tmp.add_argument("version", nargs="?", help="The version; default the newest.")
    tmp.add_argument(
        "--force",
        action="store_true",
        help="Switch even if processes started through <root>/venv exist.",
    )

    tmp = subsubparser.add_parser(
        "rollback", help="Switch back to an earlier version of the environment."
    )
    tmp.set_defaults(func=rollback)
    tmp.add_argument(
        "version", nargs="?", help="The version; default the one before the current."
    )
    tmp.add_argument(
        "--force",
        action="store_true",
        help="Switch even if processes started through <root>/venv exist.",
    )

    tmp = subsubparser.add_parser(
        "prune",
        help=(
            "Remove old versions that no process uses, keeping the newest ones "
            "for rollback."
        ),
    )
    tmp.set_defaults(func=prune)
    tmp.add_argument(
        "--keep", type=int, default=2, help="Versions to keep, default %(default)s."
    )
    tmp.add_argument(
        "--min-age",
        type=float,
        default=1.0,
        help="Never remove a version younger than this many days, default %(default)s.",
    )
    tmp.add_argument(
        "--dry-run", action="store_true", help="Only report what would be removed."
    )


def ensure(python_version=None):
    """Create the environment if it does not exist. Returns True if created."""
    if my.uv.exists:
        return False
    create(python_version=python_version)
    return True


def create(python_version=None):
    if my.uv.exists:
        print(f"The environment {my.uv.path} already exists.")
        return 0
    if python_version is None:
        python_version = getattr(my.options, "python", None)
    my.uv.create(python_version=python_version)
    print(f"Created {my.uv}.")
    return 0


def show():
    if not my.uv.exists:
        print(f"There is no environment at {my.uv.path}.")
        print("Create one with 'seamm-manager environment create' or by installing.")
        return 0
    print(f"Environment: {my.uv.path}")
    if my.uv.is_versioned:
        n = len(my.uv.versions())
        print(f"Version:     {my.uv.current_version} ({n} kept)")
    else:
        print("Version:     not versioned yet (the next update will do that)")
    print(f"Python:      {my.uv.python} ({my.uv.python_version_installed()})")
    packages = my.uv.list()
    seamm = {k: v for k, v in packages.items() if "seamm" in k or k == "molsystem"}
    print(f"Packages:    {len(packages)} installed, {len(seamm)} SEAMM")
    from .policy import code_environment_policy

    print(f"Codes:       {code_environment_policy(my.root)} conda environments")
    return 0


def recreate():
    from . import versions as _versions
    from .util import constraints, find_packages, write_environment_snapshot

    if not my.uv.exists:
        create(python_version=getattr(my.options, "python", None))
        return 0
    packages = find_packages(progress=False)
    installed = [p for p in my.uv.list() if p in packages]
    python_version = getattr(my.options, "python", None)
    if python_version:
        my.uv.python_version = python_version
    _versions.ensure_versioned()
    print(f"Building a fresh environment with {len(installed)} SEAMM packages.")
    specs, lock = installed, constraints()
    if getattr(my.options, "latest", False):
        # Each package's newest release, unconstrained (seamm_manager#27)
        from .util import pypi_latest

        specs, lock = [], None
        for package in installed:
            version = pypi_latest(package)
            if version is None:
                print(f"Could not reach PyPI for {package}; its newest release used.")
                specs.append(package)
            else:
                specs.append(f"{package}=={version}")
        print("Using each package's newest release on PyPI (--latest).")
    new = _versions.build_version(specs, constraints=lock, from_freeze=False)
    saved, my.uv = my.uv, new
    try:
        path = write_environment_snapshot("recreate")
    finally:
        my.uv = saved
    print(f"built; the environment is recorded in {path.name}")
    if _versions.switch(new, force=getattr(my.options, "force", False)):
        from .install import install_packages

        # The plug-ins' own installers, for the codes, run against the new environment
        install_packages(installed, update=True)
    return 0


def versions():
    from . import versions as _versions

    if not my.uv.is_versioned:
        print("The environment is not versioned yet; the next update will do that,")
        print("or run 'seamm-manager environment migrate'.")
        return 0
    current = my.uv.real_path
    for name, path in my.uv.versions():
        marker = "*" if path == current else " "
        users = _versions.processes_using(path)
        use = f"{len(users)} process(es)" if users else "idle"
        print(f" {marker} {name}  {_versions._size(path):>9}  {use}")
    print(" * = current")
    unsafe = _versions.unsafe_processes()
    if unsafe:
        _versions._print_processes(
            unsafe, f"Started through {my.uv.path} (a switch would affect them):"
        )
    return 0


def migrate():
    from . import versions as _versions

    if my.uv.is_versioned:
        print(f"The environment is already versioned ({my.uv.current_version}).")
    elif not _versions.ensure_versioned():
        print(f"There is no environment at {my.uv.path} to migrate.")
    return 0


def switch():
    from . import versions as _versions

    if not my.uv.is_versioned:
        print("The environment is not versioned; run 'environment migrate' first.")
        return 1
    known = my.uv.versions()
    name = getattr(my.options, "version", None) or known[-1][0]
    if name not in [n for n, _ in known]:
        print(
            f"There is no version '{name}'. Versions: {', '.join(n for n, _ in known)}"
        )
        return 1
    if my.uv.current_version == name:
        print(f"{name} is already the current version.")
        return 0
    return 0 if _versions.switch(my.uv.version(name), force=my.options.force) else 1


def rollback():
    from . import versions as _versions

    return 0 if _versions.rollback(my.options.version, force=my.options.force) else 1


def prune():
    from . import versions as _versions

    _versions.prune(
        keep=my.options.keep,
        min_age_days=my.options.min_age,
        dry_run=my.options.dry_run,
    )
    return 0


def remove():
    if not my.uv.exists:
        print(f"There is no environment at {my.uv.path}.")
        return 0
    print(f"Removing {my.uv.path}")
    my.uv.remove()
    return 0
