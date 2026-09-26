# -*- coding: utf-8 -*-

"""Install requested components of SEAMM."""

import platform

from packaging.version import Version

from . import datastore
from . import environment
from .metadata import development_packages, standalone_packages
from . import my
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
        "--rerun-installers",
        action="store_true",
        help=(
            "Run the per-package steps (datastore update, the plug-ins' own "
            "installers for their codes) for every requested package, not just "
            "those installed now. Use after an interrupted install."
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

    environment.ensure(python_version=my.options.python)

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

    if len(specs) > 0:
        retire_installer(specs, info)
        lock = constraints()
        if lock is None:
            print("Installing with uv (no constraints).")
        else:
            print(f"Installing with uv, constrained to the published lock {lock.name}.")
        my.uv.install(specs, constraints=lock, upgrade=update)
        sync_manager()
        path = write_environment_snapshot("install")
        print(f"done; the environment is recorded in {path.name}")
    else:
        print("Nothing to install.")

    # Restart services and run the plug-ins' own installers. Normally only for
    # the packages this run installed or updated; --rerun-installers does it
    # for every requested package, which is how to recover if an earlier run
    # was interrupted part way through this loop (re-running 'install' alone
    # finds nothing to install and would otherwise skip all of this).
    changed = {spec.split("==")[0] for spec in specs}
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
            service = f"dev_{package}" if my.development else package
            mgr.restart(service, ignore_errors=True)

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
    packages = my.package_metadata.get("development packages", development_packages)
    print(f"Installing development packages {' '.join(packages)}")
    my.uv.install(list(packages))
