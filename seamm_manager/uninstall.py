# -*- coding: utf-8 -*-

"""Uninstall requested components of SEAMM."""

from . import my
from .util import (
    find_packages,
    get_metadata,
    run_plugin_installer,
    write_environment_snapshot,
)


def setup(parser):
    """Define the command-line interface for removing SEAMM components.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The main parser for the application.
    """
    subparser = parser.add_parser("uninstall")
    subparser.set_defaults(func=uninstall)

    subparser.add_argument(
        "--all",
        action="store_true",
        help="Fully uninstall the SEAMM installation",
    )
    subparser.add_argument(
        "--third-party",
        action="store_true",
        help="Uninstall all packages from 3rd parties",
    )
    subparser.add_argument(
        "--gui-only",
        action="store_true",
        help="Uninstall only the GUI part of packages, leaving the background part.",
    )
    subparser.add_argument(
        "modules",
        nargs="*",
        default=None,
        help="Specific modules and plug-ins to uninstall.",
    )


def uninstall():
    """Uninstall the requested SEAMM components and plug-ins.

    With --all the whole environment is removed after the plug-ins' own
    uninstallers (for the external codes) have run.
    """
    if not my.uv.exists:
        print(f"There is no SEAMM environment at {my.uv.path}; nothing to uninstall.")
        return 0
    if my.options.all:
        uninstall_packages("all", gui_only=my.options.gui_only)
        print(f"Removing the environment {my.uv.path}")
        my.uv.remove()
    else:
        uninstall_packages(my.options.modules, gui_only=my.options.gui_only)
    return 0


def uninstall_packages(to_uninstall, gui_only=False):
    """Uninstall SEAMM components and plug-ins."""
    metadata = get_metadata()

    # Find all the packages
    packages = find_packages(progress=True)

    # Get the info about the installed packages
    info = my.uv.list()

    if to_uninstall == "all":
        to_uninstall = [*packages.keys()]

    # First uninstall any plug-in installation
    if not metadata["gui-only"] and not gui_only:
        print(
            "Checking for plug-ins that have their own installations, and "
            "uninstalling them."
        )

    to_remove = []
    for package in to_uninstall:
        if package in info:
            to_remove.append(package)
            # See if the package has an installer
            if not metadata["gui-only"] and not gui_only:
                run_plugin_installer(package, "uninstall")

    if len(to_remove) > 0:
        print(f"Uninstalling {', '.join(to_remove)}")
        my.uv.uninstall(to_remove)
        path = write_environment_snapshot("uninstall")
        print(f"done; the environment is recorded in {path.name}")
    else:
        print("None of the requested packages is installed.")
