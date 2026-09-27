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
            "Delete and recreate the environment from scratch, then reinstall the "
            "packages that were in it. The cure for most environment problems."
        ),
    )
    tmp.set_defaults(func=recreate)
    tmp.add_argument(
        "--python",
        default=DEFAULT_PYTHON,
        help="The Python version to install, default %(default)s",
    )

    tmp = subsubparser.add_parser("remove", help="Delete the environment.")
    tmp.set_defaults(func=remove)


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
    print(f"Python:      {my.uv.python} ({my.uv.python_version_installed()})")
    packages = my.uv.list()
    seamm = {k: v for k, v in packages.items() if "seamm" in k or k == "molsystem"}
    print(f"Packages:    {len(packages)} installed, {len(seamm)} SEAMM")
    from .policy import code_environment_policy

    print(f"Codes:       {code_environment_policy(my.root)} conda environments")
    return 0


def recreate():
    from .install import install_packages

    installed = []
    if my.uv.exists:
        from .util import find_packages

        packages = find_packages(progress=False)
        installed = [p for p in my.uv.list() if p in packages]
        print(f"Removing {my.uv.path}")
        my.uv.remove()
    create(python_version=getattr(my.options, "python", None))
    if installed:
        print(f"Reinstalling {len(installed)} SEAMM packages.")
        install_packages(installed)
    return 0


def remove():
    if not my.uv.exists:
        print(f"There is no environment at {my.uv.path}.")
        return 0
    print(f"Removing {my.uv.path}")
    my.uv.remove()
    return 0
