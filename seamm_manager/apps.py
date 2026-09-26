# -*- coding: utf-8 -*-

"""Handle the apps for SEAMM."""

import importlib
from pathlib import Path
import platform

from tabulate import tabulate

from . import my

system = platform.system()
if system in ("Darwin",):
    from .mac import create_app, delete_app, get_apps, update_app

    icons = "SEAMM.icns"
elif system in ("Linux",):
    from .linux import create_app, delete_app, get_apps, update_app

    icons = "linux_icons"
else:
    raise NotImplementedError(f"SEAMM does not support apps on {system} yet.")

# known_apps = ["SEAMM", "Dashboard", "JobServer"]
known_apps = ["SEAMM", "installer"]
app_names = {
    "seamm": "SEAMM",
    "dashboard": "Dashboard",
    "jobserver": "JobServer",
    "installer": "SEAMM-Installer",
}
app_package = {
    "seamm": "seamm",
    "dashboard": "seamm-dashboard",
    "jobserver": "seamm-jobserver",
    "installer": "seamm-manager",
}


def setup(parser):
    """Define the command-line interface for handling the apps.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The main parser for the application.
    """
    apps_parser = parser.add_parser("apps")
    subparser = apps_parser.add_subparsers()

    # Create
    tmp_parser = subparser.add_parser("create")
    tmp_parser.set_defaults(func=create)
    tmp_parser.add_argument(
        "--force",
        action="store_true",
        help="Recreate the app if it already exists.",
    )
    tmp_parser.add_argument(
        "--all-users",
        action="store_true",
        help="Install the apps for all users.",
    )
    tmp_parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=55066 if my.development else 55055,
    )
    tmp_parser.add_argument(
        "apps",
        nargs="*",
        default=known_apps,
        help="The apps to create: %(default)s",
    )

    # Delete
    tmp_parser = subparser.add_parser("delete")
    tmp_parser.set_defaults(func=delete)
    tmp_parser.add_argument(
        "apps",
        nargs="*",
        default=known_apps,
        help="The apps to delete: %(default)s",
    )

    # Show
    tmp_parser = subparser.add_parser("show")
    tmp_parser.set_defaults(func=show)
    tmp_parser.add_argument(
        "apps",
        nargs="*",
        default=known_apps,
        help="The apps to show: %(default)s",
    )

    # Update
    tmp_parser = subparser.add_parser("update")
    tmp_parser.set_defaults(func=update)
    tmp_parser.add_argument(
        "apps",
        nargs="*",
        default=known_apps,
        help="The apps to update: %(default)s",
    )


def create():
    """Create the requested apps."""
    apps = get_apps()
    for app in my.options.apps:
        app_lower = app.lower()
        app = app_names[app_lower]
        app_name = f"{app}-dev" if my.development else app
        packages = my.uv.list()
        package = app_package[app_lower]
        if package in packages:
            version = str(packages[package]["version"])
        else:
            print(
                f"The package '{package}' needed by the app {app_name} is not "
                "installed."
            )
            continue
        if app_name in apps:
            if not my.options.force:
                print(
                    f"The app '{app_name}' already exists! Use --force to "
                    "recreate the app from scratch."
                )
                continue

            delete_app(app_name)

        data_path = importlib.resources.files("seamm_manager") / "data"
        icons_path = data_path / icons
        root = str(my.root)

        if app_lower == "dashboard":
            bin_path = my.uv.which("seamm-dashboard")
            create_app(
                bin_path,
                "--root",
                root,
                "--port",
                my.options.port,
                name=app_name,
                version=version,
                user_only=not my.options.all_users,
                icons=icons_path,
            )
        elif app_lower == "jobserver":
            bin_path = my.uv.which(app.lower())
            create_app(
                bin_path,
                "--root",
                root,
                name=app_name,
                version=version,
                user_only=not my.options.all_users,
                icons=icons_path,
            )
        else:
            bin_path = my.uv.which(app.lower())
            create_app(
                bin_path,
                name=app_name,
                version=version,
                user_only=not my.options.all_users,
                icons=icons_path,
            )
        if my.options.all_users:
            print(f"\nInstalled app {app_name} for all users.")
        else:
            print(f"\nInstalled app {app_name} for this user.")


def delete():
    apps = get_apps()
    for app in my.options.apps:
        app_lower = app.lower()
        app = app_names[app_lower]
        app_name = f"{app}-dev" if my.development else app
        if app_name in apps:
            delete_app(app_name, missing_ok=True)
            print(f"Deleted the app '{app_name}'.")
        else:
            print(f"App '{app_name}' was not installed.")


def show():
    apps = get_apps()

    table = []
    for app in my.options.apps:
        app_lower = app.lower()
        app = app_names[app_lower]
        app_name = f"{app}-dev" if my.development else app
        if app_name in apps:
            path = apps[app_name]
            if path.is_relative_to(Path.home()):
                path = path.relative_to(Path.home())
                table.append((app_name, "~/" + str(path)))
            else:
                table.append((app_name, str(path)))
        else:
            table.append((app_name, "not found"))
    if len(table) == 0:
        print("Found no apps.")
    else:
        print(tabulate(table, ("App", "Path"), tablefmt="fancy_grid"))


def update():
    apps = get_apps()
    packages = my.uv.list()
    for app in my.options.apps:
        app_lower = app.lower()
        app = app_names[app_lower]
        app_name = f"{app}-dev" if my.development else app
        package = app_package[app_lower]
        if app_name in apps:
            if package in packages:
                version = str(packages[package]["version"])
            else:
                print(
                    f"The package '{package}' needed by the app {app_name} is not "
                    "installed. Removed the app, since it cannot be used."
                )
                delete_app(app_name, missing_ok=True)
                continue
            update_app(app_name, version, missing_ok=True)
            print(f"Updated the app '{app_name}' to version {version}.")
        else:
            print(f"App '{app_name}' was not installed.")
