# -*- coding: utf-8 -*-

"""Update requested components of SEAMM."""

import os
import platform
import sys

from packaging.version import Version

from .datastore import update as update_datastore
from .metadata import development_packages
from . import my
from .naming import service_name as installation_service_name
from .util import (
    constraints,
    find_packages,
    retire_installer,
    sync_manager,
    get_metadata,
    package_info,
    pypi_latest,
    run_plugin_installer,
    write_environment_snapshot,
)

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
    """Define the command-line interface for updating SEAMM components.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The main parser for the application.
    """
    subparser = parser.add_parser("update")
    subparser.set_defaults(func=update)

    subparser.add_argument(
        "--all",
        action="store_true",
        help="Fully update the SEAMM installation",
    )
    subparser.add_argument(
        "--gui-only",
        action="store_true",
        help="Update only packages necessary for the GUI",
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
        "--refresh-codes",
        action="store_true",
        help=(
            "Apply the plug-ins' environment files to the codes' conda environments "
            "even if unchanged, to pick up new builds of the codes now. Otherwise an "
            "unchanged file is applied again only after 7 days."
        ),
    )
    subparser.add_argument(
        "--latest",
        action="store_true",
        help=(
            "Ask PyPI for the newest release of each package rather than trusting "
            "the nightly package list, so a release made today is picked up. "
            "Implies --no-constraints, since the lock file pins yesterday's "
            "versions."
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
        help="Specific modules and plug-ins to update.",
    )


def update():
    """Update the requested SEAMM components and plug-ins."""
    if not my.uv.exists:
        print(f"There is no SEAMM environment at {my.uv.path}; nothing to update.")
        print("Install SEAMM first with 'seamm-manager install --all'.")
        return 1

    # The manager itself, if installed as a uv tool: keep it current first. Only
    # when there is a newer release: reinstalling the running tool replaces its own
    # files, which on a network filesystem can leave it half removed.
    if (
        my.options.all
        and not os.environ.get("SEAMM_MANAGER_UPGRADED")
        and _newer_manager_release()
    ):
        if my.uv.tool_upgrade("seamm-manager"):
            os.environ["SEAMM_MANAGER_UPGRADED"] = "1"
            print("Re-running with the updated manager.")
            os.execv(sys.executable, [sys.executable, *sys.argv])

    # Need to track packages that require services to be restarted.
    service_packages = ("seamm-datastore", "seamm-jobserver")
    initial_version = {p: package_info(p)[0] for p in service_packages}

    latest = getattr(my.options, "latest", False)
    # In a development installation the development tools are upgraded in the
    # same new environment as the packages, never in place (see versions.py).
    extra = _development_specs() if my.development else None
    if my.options.all:
        update_packages("all", gui_only=my.options.gui_only, latest=latest, extra=extra)
        update_webui()
    else:
        # seamm-webui lives in its own environment, not the package list
        modules = [m for m in my.options.modules if m != "seamm-webui"]
        if len(modules) < len(my.options.modules):
            update_webui()
        if modules:
            update_packages(
                modules, gui_only=my.options.gui_only, latest=latest, extra=extra
            )

    if my.development and getattr(my.options, "in_place", False):
        update_development_environment()

    # Keep the desktop apps current (version, and the macOS launcher)
    try:
        from .apps import refresh_apps

        refresh_apps()
    except Exception as e:
        print(f"Could not refresh the desktop apps: {e}")

    # And the macOS service bundles (their interpreter, and old-style services)
    try:
        from .services import refresh_service_bundles

        refresh_service_bundles()
    except Exception as e:
        print(f"Could not refresh the service bundles: {e}")

    final_version = {p: package_info(p)[0] for p in service_packages}
    # And restart any services that need it
    service_name = installation_service_name("jobserver")
    if (
        initial_version["seamm-datastore"] is not None
        and final_version["seamm-datastore"] is not None
        and Version(final_version["seamm-datastore"])
        > Version(initial_version["seamm-datastore"])
    ):
        if mgr.is_installed(service_name):
            from .services import is_running

            running = is_running(service_name, mgr)
            mgr.stop(service_name)
            update_datastore()
            if running:
                mgr.start(service_name)
                print(
                    f"Restarted the {service_name} because the datastore was updated."
                )
            else:
                print(f"The {service_name} was stopped; it was left stopped.")
    elif (
        initial_version["seamm-jobserver"] is not None
        and final_version["seamm-jobserver"] is not None
        and Version(final_version["seamm-jobserver"])
        > Version(initial_version["seamm-jobserver"])
    ):
        from . import versions as _versions

        # A switch to a new environment version already restarted the services
        if mgr.is_installed(service_name) and not _versions.switched:
            from .services import restart_if_running

            if restart_if_running(service_name, mgr):
                print(f"Restarted the {service_name} because it was updated.")

    # Point at the flowchart upgrade if old job flowcharts remain (report only)
    from .flowcharts import notice

    notice()
    return 0


def update_webui():
    """Update the web interface's own environment (venv-webui), if this installation
    has one, and restart its service if anything in it changed.

    seamm-webui is not in the package list and lives in its own environment, so
    updating the main environment never touched it: an installation kept its old web
    interface, and the datastore inside it, until it was updated by hand.
    """
    from .install import install_seamm_webui
    from .uv import Uv

    webui = Uv(my.root, name="venv-webui", python_version=my.uv.python_version)
    if not webui.exists:
        return
    before = {k: v["version"] for k, v in webui.list().items()}
    install_seamm_webui(update=True)
    after = {k: v["version"] for k, v in webui.list().items()}
    changed = {
        name: (before.get(name), version)
        for name, version in after.items()
        if before.get(name) != version
    }
    if not changed:
        print("   The web interface is up to date.")
        return
    for name in ("seamm-webui", "seamm-datastore"):
        if name in changed:
            old, new = changed[name]
            print(f"   {name}: {old} -> {new}")
    service = installation_service_name("webui")
    if mgr.is_installed(service):
        from .services import restart_if_running

        if restart_if_running(service, mgr):
            print(f"Restarted the {service} because the web interface was updated.")


def update_packages(
    to_update,
    gui_only=False,
    progress=None,
    update_text=None,
    latest=False,
    extra=None,
):
    """Update SEAMM components and plug-ins.

    `extra` names further packages (the development tools) to upgrade along
    with any SEAMM package that changes; they do not by themselves cause a
    rebuild.

    The version to update to normally comes from the nightly package list, and
    the install is constrained to the matching lock file. With ``latest`` each
    package's newest release on PyPI is used when it is newer than the list's,
    pinned exactly, and the lock is not applied (it would pin the older
    version); PyPI being unreachable falls back to the list for that package.
    """
    metadata = get_metadata()

    if progress is not None:
        progress()

    # Find all the packages
    packages = find_packages(progress=True)

    if progress is not None:
        progress()

    if to_update == "all":
        to_update = [*packages.keys()]

    # What is installed now
    info = my.uv.list()

    if progress is not None:
        progress()

    specs = []
    for package in to_update:
        if package not in packages:
            print(f"'{package}' is not a SEAMM package; skipping it.")
            continue
        available = Version(packages[package]["version"])

        # Skip packages that aren't installed.
        if package not in info:
            continue

        installed_version = Version(info[package]["version"])
        pinned = "pinned" in packages[package] and packages[package]["pinned"]
        if latest:
            on_pypi = pypi_latest(package)
            if on_pypi is None:
                print(f"Could not reach PyPI for {package}; using the package list.")
            elif Version(on_pypi) > available:
                available = Version(on_pypi)
                pinned = True
        spec = f"{package}=={available}" if pinned else package

        ptype = packages[package]["type"]
        if installed_version < available:
            print(
                f"Updating {ptype.lower()} {package} from version {installed_version} "
                f"to {available}"
            )
            specs.append(spec)

    if progress is not None:
        progress()

    if len(specs) > 0:
        retire_installer(specs, info)
        lock = None if latest else constraints()
        if latest:
            print("Updating with uv, unconstrained (--latest).")
        elif lock is None:
            print("Updating with uv (no constraints).")
        else:
            print(f"Updating with uv, constrained to the published lock {lock.name}.")
        from .versions import apply_change

        if extra:
            print(f"Also updating the development packages {' '.join(extra)}")
        applied = apply_change([*specs, *(extra or [])], constraints=lock, upgrade=True)
        if applied:
            path = write_environment_snapshot("update")
            print(f"done; the environment is recorded in {path.name}")
        else:
            print("The change was not applied to the current environment (see above).")
    else:
        print("Everything is up to date.")

    # Whether or not anything else changed: the environment must hold this
    # manager's release (the package list lags a release by up to a day). A
    # build of a new version has already done this in the new environment.
    from . import versions as _versions

    if not _versions.synced_manager and sync_manager() is not None:
        path = write_environment_snapshot("update-manager")
        print(f"the environment is recorded in {path.name}")

    # See if any packages have an installer
    if not metadata["gui-only"] and not gui_only:
        for package in to_update:
            # Skip packages that aren't installed, and those refused above as
            # not SEAMM packages (seamm_manager#29).
            if package in info and package in packages:
                if progress is not None:
                    progress()
                if update_text is not None:
                    print(f"Updating background codes for {package}")
                    update_text(f"Updating background codes for {package}")
                run_plugin_installer(package, "update")


def _development_specs():
    """The development tools, from the package metadata."""
    return list(my.package_metadata.get("development packages", development_packages))


def update_development_environment():
    """Update packages needed for development, in place (``--in-place`` only;
    otherwise they are upgraded in the new environment with the packages)."""
    packages = _development_specs()
    print(f"Updating development packages {' '.join(packages)}")
    my.uv.install(packages, upgrade=True)


def _newer_manager_release():
    """Whether PyPI has a newer seamm-manager than the one running.

    If PyPI cannot be reached, assume there is (the upgrade itself will say).
    """
    from . import __version__
    from .util import pypi_latest

    latest = pypi_latest("seamm-manager")
    if latest is None:
        return True
    try:
        return Version(latest) > Version(__version__.split("+")[0])
    except Exception:
        return True
