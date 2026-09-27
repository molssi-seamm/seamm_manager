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
            "$SEAMM_ROOT if set, else ~/SEAMM."
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
    root = my.options.root
    if root is None:
        if my.development:
            root = "~/SEAMM_DEV"
        else:
            root = os.environ.get("SEAMM_ROOT", "").strip() or "~/SEAMM"
    my.root = Path(root).expanduser()
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
