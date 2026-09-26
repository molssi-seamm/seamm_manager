# -*- coding: utf-8 -*-

"""Handle the cache for SEAMM components."""

from .util import find_packages


def setup(parser):
    """Define the command-line interface for installing SEAMM components.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The main parser for the application.
    """
    # Install
    subparser = parser.add_parser("refresh-cache")
    subparser.set_defaults(func=refresh)


def refresh():
    find_packages(progress=True, update_cache=True)
    print("Refreshed the cache of SEAMM components and plug-ins.")
