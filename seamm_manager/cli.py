# -*- coding: utf-8 -*-

"""Define the command-line interface for the SEAMM installer."""

from . import apps
from . import cache
from . import datastore
from . import environment
from . import install
from . import services
from . import show
from . import uninstall
from . import update


def setup(parser):
    """Setup the command-line interface for the SEAMM manager.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The main parser for the application.

    logger : logging.Logger
        The logger for output.

    environment : str
        The Conda environment name
    """
    subparser = parser.add_subparsers()

    cache.setup(subparser)
    datastore.setup(subparser)
    environment.setup(subparser)
    install.setup(subparser)
    show.setup(subparser)
    uninstall.setup(subparser)
    update.setup(subparser)
    apps.setup(subparser)
    services.setup(subparser)
