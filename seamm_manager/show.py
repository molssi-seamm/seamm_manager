# -*- coding: utf-8 -*-

"""Show the status of the SEAMM installation."""

from packaging.version import Version
import textwrap

from tabulate import tabulate

from . import my
from .util import find_packages, run_plugin_installer


def setup(parser):
    """Define the command-line interface for installing SEAMM components.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The main parser for the application.
    """
    # Install
    subparser = parser.add_parser("show")
    subparser.set_defaults(func=show)


def show():
    my.logger.debug("Entering show part of the SEAMM manager")

    if not my.uv.exists:
        print(f"There is no SEAMM environment at {my.uv.path}, so none of SEAMM is.")
        print("Install it with 'seamm-manager install --all'.")
        return

    packages = find_packages(progress=True)

    print("")
    print("Showing the modules in SEAMM:")

    # Get the info about the installed packages
    info = my.uv.list()

    data = []
    am_current = True
    state = {}
    count = 0
    for package in packages:
        count += 1
        if count > 50:
            count = 0
            print("\n.", end="", flush=True)
        else:
            print(".", end="", flush=True)

        if package in packages and "description" in packages[package]:
            description = packages[package]["description"].strip()
            description = textwrap.fill(description, width=50)
        else:
            description = "description unavailable"

        if package not in info:
            available = packages[package]["version"]
            data.append(["*" + package, "--", available, description])
            am_current = False
            state[package] = "not installed"
        else:
            version = Version(info[package]["version"])
            available = Version(packages[package]["version"])
            if version < available:
                am_current = False
                state[package] = "not up-to-date"
            else:
                state[package] = "up-to-date"

                # See if the package has an installer
                result = run_plugin_installer(package, "show", verbose=False)
                if result is not None:
                    if result.returncode == 0:
                        for line in result.stdout.splitlines():
                            description += f"\n{line}"
                    else:
                        description += (
                            f"\nThe installer for {package} "
                            f"returned code {result.returncode}"
                        )
                        for line in result.stderr.splitlines():
                            description += f"\n    {line}"
            if version < available:
                data.append(["*" + package, version, available, description])
            else:
                data.append([package, version, available, description])

    # Sort by the plug-in names
    for ptype in ("Core package", "MolSSI plug-in", "3rd-party plug-in"):
        group = []
        count = 1
        for m, i, a, d in data:
            if packages[m.lstrip("*")]["type"] == ptype:
                group.append([m, i, a, d])

        group.sort(key=lambda x: x[0])

        # And number
        for i, line in enumerate(group, start=1):
            line.insert(0, i)

        print("")
        if ptype == "Core package":
            print("Core modules of SEAMM")
            headers = ["Number", "Component", "Installed", "Available", "Description"]
        else:
            print(f"{ptype}s")
            headers = ["Number", "Plug-in", "Installed", "Available", "Description"]
        print(tabulate(group, headers, tablefmt="fancy_grid"))

    if am_current:
        print("SEAMM is up-to-date.")
    else:
        print("* indicates the component is not up-to-date.")
    print("")
