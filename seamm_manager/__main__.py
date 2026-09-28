# -*- coding: utf-8 -*-

"""The main module for running the SEAMM manager."""

import argparse
from pathlib import Path
import logging
import os
import sys

import seamm_manager
from . import cli
from . import my
from .naming import compute_tag
from . import util
from .uv import Uv

my.logger = logging.getLogger(__name__)


def _same_path(a, b):
    try:
        return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()
    except OSError:
        return False


def own_installation_root(prefix=None):
    """The SEAMM root this manager runs from, if it is an installation's own copy.

    The copy in ``<root>/venv`` (which the desktop app "SEAMM-Manager (<name>)" and
    ``<root>/venv/bin/seamm-manager`` run) works on that installation. None for the
    manager installed as a uv tool, or any environment not inside a SEAMM root.
    """
    prefix = Path(sys.prefix if prefix is None else prefix)
    if not prefix.name.startswith("venv"):
        return None
    root = prefix.parent
    try:
        if (root / "Jobs").is_dir() or any(root.glob("*.ini")):
            return root
    except OSError:
        pass
    return None


def choose_root(option=None, development=False, prefix=None):
    """The root to work on: --root, --development, $SEAMM_ROOT, the installation
    this manager runs from, then ~/SEAMM."""
    if option:
        return option
    if development:
        return "~/SEAMM_DEV"
    value = os.environ.get("SEAMM_ROOT", "").strip()
    if value:
        return value
    own = own_installation_root(prefix)
    if own is not None:
        return str(own)
    return "~/SEAMM"


def run():
    """Run the manager.

    The manager uses nested parsers to handle commands and options on the
    command line. Each subparser has a default command which is how the code
    calls the requested method.
    """
    parser = argparse.ArgumentParser(
        epilog="If no positional argument is given, the GUI will appear."
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"SEAMM Manager version {seamm_manager.__version__}",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        type=str.upper,
        choices=["NOTSET", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=("The level of informational output, defaults to " "'%(default)s'"),
    )
    parser.add_argument(
        "--development",
        action="store_true",
        help="Work with the development installation (~/SEAMM_DEV), not ~/SEAMM.",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=None,
        help=(
            "The SEAMM root directory, holding the environment, jobs and "
            "configuration. Default ~/SEAMM_DEV with --development, else "
            "$SEAMM_ROOT if set, else the installation this manager runs from "
            "(<root>/venv), else ~/SEAMM."
        ),
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help=(
            "The installation's name in its services and apps. Default: none for "
            "~/SEAMM, else the root's directory name (e.g. SEAMM_DEV)."
        ),
    )

    # Parse the first options
    if "-h" not in sys.argv and "--help" not in sys.argv:
        options, _ = parser.parse_known_args()
        level = options.log_level
        logging.basicConfig(level=level)
        my.development = options.development

    cli.setup(parser)

    # Parse the command-line arguments and call the requested function or the GUI
    my.options = parser.parse_args()
    my.development = my.options.development
    my.environment = "seamm-dev" if my.development else "seamm"
    my.root = Path(choose_root(my.options.root, my.development)).expanduser()
    # A manager running from ~/SEAMM_DEV's environment works on the development
    # installation, development tools included, as with --development.
    if not my.development and _same_path(my.root, "~/SEAMM_DEV"):
        my.development = True
    my.root.mkdir(parents=True, exist_ok=True)
    # The installation's tag, used in its services', apps' and bundles' names
    my.tag = compute_tag(my.root, my.options.name)

    # The uv-managed environment, and conda for the codes' own environments
    my.uv = Uv(my.root)
    util.initialize()
    print(f"Working with the SEAMM installation in {my.root}")

    if "func" in my.options:
        try:
            sys.exit(my.options.func())
        except util.PackageListUnavailable as e:
            print(e)
            sys.exit(1)
        except AttributeError:
            print(f"Missing arguments to seamm-manager {' '.join(sys.argv[1:])}")
            # Append help so help will be printed
            sys.argv.append("--help")
            # re-run
            run()
    else:
        from .gui import GUI

        gui = GUI(logger=my.logger)

        # enter the event loop
        gui.event_loop()


if __name__ == "__main__":
    run()
