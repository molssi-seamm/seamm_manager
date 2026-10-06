# -*- coding: utf-8 -*-

"""Install requested components of SEAMM."""

from pathlib import Path
import platform

from packaging.version import Version

from . import datastore
from . import environment
from .metadata import development_packages, standalone_packages
from . import my
from .naming import service_name as installation_service_name
from .util import (
    constraints,
    find_packages,
    retire_installer,
    sync_manager,
    get_metadata,
    run_plugin_installer,
    set_metadata,
    write_environment_snapshot,
)
from .uv import Uv

system = platform.system()
if system in ("Darwin",):
    from .mac import ServiceManager

    mgr = ServiceManager(prefix="org.molssi.seamm")
elif system in ("Linux",):
    from .linux import ServiceManager

    mgr = ServiceManager(prefix="org.molssi.seamm")
else:
    raise NotImplementedError(f"SEAMM does not support services on {system} yet.")


def setup(parser):
    """Define the command-line interface for installing SEAMM components.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The main parser for the application.
    """
    # Install
    subparser = parser.add_parser("install")
    subparser.set_defaults(func=install)
    subparser.add_argument(
        "--all",
        action="store_true",
        help="Install any missing packages from the MolSSI",
    )
    subparser.add_argument(
        "--third-party",
        action="store_true",
        help="Install any missing packages from 3rd parties",
    )
    subparser.add_argument(
        "--update",
        action="store_true",
        help="Update any out-of-date packages",
    )
    subparser.add_argument(
        "--gui-only",
        action="store_true",
        help="Install only packages necessary for the GUI",
    )
    subparser.add_argument(
        "--no-constraints",
        action="store_true",
        help=(
            "Do not constrain versions to the published lock file; take the "
            "newest releases pip can resolve."
        ),
    )
    subparser.add_argument(
        "--python",
        default=None,
        help="Python version if the environment has to be created (default 3.12)",
    )
    subparser.add_argument(
        "--code-environments",
        choices=("own", "shared", "prefixed"),
        default=None,
        help=(
            "How this installation gets the external codes' conda environments: "
            "'shared' uses the default installation's (the default for any root "
            "but ~/SEAMM), 'own' creates and updates them, 'prefixed' makes its "
            "own copies named seamm-<name>-<code>."
        ),
    )
    subparser.add_argument(
        "--rerun-installers",
        action="store_true",
        help=(
            "Run the per-package steps (datastore update, the plug-ins' own "
            "installers for their codes) for every requested package, not just "
            "those installed now. Use after an interrupted install."
        ),
    )
    subparser.add_argument(
        "--in-place",
        action="store_true",
        help=(
            "Change the current environment directly rather than building a new "
            "version beside it and switching. Not safe while jobs run."
        ),
    )
    subparser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Switch to the new environment even if processes started through "
            "<root>/venv (jobs begun before the environment was versioned) exist."
        ),
    )
    subparser.add_argument(
        "modules",
        nargs="*",
        default=None,
        help="Specific modules and plug-ins to install.",
    )


def install():
    """Install the requested SEAMM components and plug-ins.

    Parameters
    ----------
    options : argparse.Namespace
        The options from the command-line parser.
    """
    if my.options.gui_only:
        metadata = get_metadata()
        if not metadata["gui-only"]:
            metadata["gui-only"] = True
            set_metadata(metadata)

    # The installation's code-environment policy, recorded before any plug-in's
    # installer runs, since they honour it.
    from .policy import (
        POLICY_FILE,
        code_environment_policy,
        is_default_root,
        set_code_environment_policy,
    )

    choice = getattr(my.options, "code_environments", None)
    try:
        if choice is not None:
            set_code_environment_policy(my.root, choice)
        elif not is_default_root(my.root) and not (my.root / POLICY_FILE).exists():
            set_code_environment_policy(my.root, "shared")
    except ValueError as e:
        print(e)
        return 1
    policy = code_environment_policy(my.root)
    if policy == "shared":
        print(
            "This installation shares the default installation's codes: plug-ins "
            "will not create or update conda environments here."
        )
    elif policy == "prefixed":
        print("This installation has its own copies of the codes' environments.")

    environment.ensure(python_version=my.options.python)
    write_taskserver_ini(my.root)

    if my.options.all:
        install_packages(
            "all",
            third_party=my.options.third_party,
            update=my.options.update,
            gui_only=my.options.gui_only,
        )
    else:
        # standalone_packages (currently just seamm-webui) aren't in the
        # Zenodo-hosted package registry install_packages() reads from --
        # not installed into the shared main environment, so they can't go
        # through that generic per-package flow. Handle them directly here,
        # then hand off anything else requested to install_packages() as
        # usual.
        modules = list(my.options.modules)
        for package in standalone_packages:
            if package in modules:
                modules.remove(package)
                install_seamm_webui(update=my.options.update)

        if modules:
            install_packages(
                modules, update=my.options.update, gui_only=my.options.gui_only
            )

    if my.development:
        install_development_environment()

    from . import versions as _versions

    # Non-zero if a change was built but not switched to, so scripts notice
    return 1 if _versions.refused else 0


def write_taskserver_ini(root):
    """Write ``<root>/taskserver.ini``, the TaskServer's capacity, if missing.

    The TaskServer (``seamm_scheduler.taskserver``) is the queue that a machine's
    SEAMM jobs and their calculations can share, used by a queue section with
    ``scheduler = seamm``. Its capacity is written out explicitly -- this
    machine's physical cores and half its memory -- rather than left as a
    silent default, so it can be seen and changed.

    Returns
    -------
    pathlib.Path or None
        The file, if it was written.
    """
    import psutil

    path = Path(root).expanduser() / "taskserver.ini"
    if path.exists():
        return None
    cores = psutil.cpu_count(logical=False) or psutil.cpu_count() or 1
    memory = psutil.virtual_memory().total // 2
    gigabytes = max(1, int(memory // 1024**3))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[taskserver]\n"
        "# The TaskServer: the queue for this machine's cores and memory that\n"
        "# SEAMM jobs and their calculations can share, used by a queue section\n"
        '# with "scheduler = seamm" (see seamm_scheduler.taskserver). Written by\n'
        "# seamm-manager on install: this machine's physical cores and half its\n"
        "# memory, leaving the rest for the desktop and everything else. Change\n"
        "# them as you like.\n"
        f"cores = {cores}\n"
        f"memory = {gigabytes} GB\n"
    )
    print(f"Wrote {path}: the TaskServer may use {cores} cores and {gigabytes} GB.")
    return path


def install_seamm_webui(update=False):
    """Create/update the dedicated ``venv-webui`` environment under the root and
    install (or upgrade) seamm_webui into it from PyPI.

    seamm_webui is not in the package list and, being a daemon rather than a
    plug-in, lives in its own environment rather than the main one. Its own
    runtime dependencies (fastapi, uvicorn, ...) are declared in its PyPI
    package and resolved by uv here, not duplicated.
    """
    webui = Uv(my.root, name="venv-webui", python_version=my.uv.python_version)
    if not webui.exists:
        print(f"Creating the dedicated environment {webui.path}")
        webui.create()
    verb = "Updating" if update else "Installing"
    print(f"{verb} seamm-webui in {webui.path}.")
    webui.install("seamm-webui", upgrade=update)


def install_packages(
    to_install,
    update=False,
    third_party=False,
    gui_only=False,
    progress=None,
    update_text=None,
):
    """Install SEAMM components and plug-ins."""
    metadata = get_metadata()

    if progress is not None:
        progress()

    # Find all the packages
    packages = find_packages(progress=True)

    if progress is not None:
        progress()

    if to_install == "all":
        if third_party:
            to_install = [*packages.keys()]
        else:
            to_install = [
                p for p, d in packages.items() if "3rd-party" not in d["type"]
            ]

    # What is installed now
    info = my.uv.list()

    if progress is not None:
        progress()

    specs = []
    for package in to_install:
        if package == "development":
            continue
        if package not in packages:
            print(f"'{package}' is not a SEAMM package; skipping it.")
            continue
        available = Version(packages[package]["version"])
        installed_version = (
            Version(info[package]["version"]) if package in info else None
        )
        ptype = packages[package]["type"]

        pinned = "pinned" in packages[package] and packages[package]["pinned"]
        spec = f"{package}=={available}" if pinned else package

        if package not in info:
            print(f"Installing {ptype.lower()} {package} version {available}.")
            specs.append(spec)
        elif update and installed_version < available:
            print(
                f"Updating {ptype.lower()} {package} from version {installed_version} "
                f"to {available}"
            )
            specs.append(spec)

    if progress is not None:
        progress()

    applied = True
    if len(specs) > 0:
        retire_installer(specs, info)
        lock = constraints()
        if lock is None:
            print("Installing with uv (no constraints).")
        else:
            print(f"Installing with uv, constrained to the published lock {lock.name}.")
        from .versions import apply_change

        applied = apply_change(specs, constraints=lock, upgrade=update)
        if applied:
            path = write_environment_snapshot("install")
            print(f"done; the environment is recorded in {path.name}")
        else:
            print("The change was not applied to the current environment (see above).")
    else:
        print("Nothing to install.")

    # Whether or not anything else changed: the environment must hold this
    # manager's release (the package list lags a release by up to a day). A
    # build of a new version has already done this in the new environment.
    from . import versions as _versions

    if not _versions.synced_manager and sync_manager() is not None:
        path = write_environment_snapshot("install-manager")
        print(f"the environment is recorded in {path.name}")

    # Restart services and run the plug-ins' own installers. Normally only for
    # the packages this run installed or updated; --rerun-installers does it
    # for every requested package, which is how to recover if an earlier run
    # was interrupted part way through this loop (re-running 'install' alone
    # finds nothing to install and would otherwise skip all of this).
    # Nothing changed if the new environment was not switched to.
    changed = {spec.split("==")[0] for spec in specs} if applied else set()
    rerun = getattr(my.options, "rerun_installers", False)
    for package in to_install:
        if progress is not None:
            progress()
        if package == "development":
            continue
        if package not in changed and not rerun:
            continue

        if package == "seamm-datastore":
            datastore.update()
        elif package == "seamm-jobserver":
            # (The service is "jobserver", not the package's name, which this
            # used to restart -- a service that never exists.)
            from .services import restart_if_running

            restart_if_running(installation_service_name("jobserver"), mgr)

        # See if the package has an installer
        if not metadata["gui-only"] and not gui_only:
            if progress is not None:
                progress()
            if update_text is not None:
                print(f"Installing background codes for {package}")
                update_text(f"Installing background codes for {package}")
            run_plugin_installer(package, "install")


def install_development_environment():
    """Install packages needed for development, from the package list's
    'development packages' (falling back to a built-in list)."""
    packages = list(
        my.package_metadata.get("development packages", development_packages)
    )
    installed = my.uv.list()
    missing = [p for p in packages if p.lower().replace("_", "-") not in installed]
    if not missing:
        print("The development packages are installed.")
        return
    print(f"Installing development packages {' '.join(missing)}")
    from .versions import apply_change

    apply_change(missing)
