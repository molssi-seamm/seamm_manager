# -*- coding: utf-8 -*-

"""Utility methods for the SEAMM installer."""

from datetime import datetime
import json
from packaging.version import Version
from pathlib import Path
import subprocess

from platformdirs import user_data_dir
from seamm_util import Zenodo

from .conda import Conda
from . import my
from .pip import Pip

# The Zenodo concept record holding the package list and its lock file
# (seamm_packaging publishes new versions there nightly).
PACKAGE_LIST_RECORD = 22970126

# from .metadata import core_packages, molssi_plug_ins, excluded_plug_ins


class JSONEncoder(json.JSONEncoder):
    """Class for handling the package versions in JSON."""

    def default(self, obj):
        if isinstance(obj, Version):
            return {"__type__": "Version", "data": str(obj)}
        else:
            return json.JSONEncoder.default(self, obj)


class JSONDecoder(json.JSONDecoder):
    """Class for handling the package versions in JSON."""

    def __init__(self, **kwargs):
        # kwargs because simplejson passes in encoding=.... causing crash
        super().__init__(object_hook=self.dict_to_object)

    def dict_to_object(self, d):
        if "__type__" in d:
            type_ = d.pop("__type__")
            if type_ == "Version":
                return Version(d["data"])
            else:
                # Oops... better put this back together.
                d["__type__"] = type
        return d


def find_packages(progress=True, update=None, update_cache=False, cache_valid=1):
    """Fetch the package list and its lock file from Zenodo.

    The package list (``SEAMM_packages.json``, format 2) gives every package
    the manager handles with its current version and type. The lock file
    (``seamm.lock.txt``) is the universal set of pinned versions that
    resolved together; it is saved under ``<root>/environments`` and passed
    to uv as constraints so installations are reproducible.

    Returns
    -------
    dict(str, dict)
        name -> {"description", "type", "version"}
    """
    zenodo = Zenodo()
    try:
        record = zenodo.get_latest_public_record(PACKAGE_LIST_RECORD)
    except Exception as e:
        raise RuntimeError(f"Error finding the package list from Zenodo: {str(e)}")

    try:
        text = record.get_file("SEAMM_packages.json")
    except Exception as e:
        raise RuntimeError(f"Error getting the package list from Zenodo: {str(e)}")

    package_db = json.loads(text, cls=JSONDecoder)
    if package_db.get("format", 1) != 2:
        raise RuntimeError(
            "The package list from Zenodo is not in the expected format (2); "
            f"got {package_db.get('format', 1)}."
        )

    my.package_metadata = package_db["metadata"] if "metadata" in package_db else {}

    # The lock file, kept beside the environment for uv to use as constraints
    lock_name = package_db.get("lock", "seamm.lock.txt")
    try:
        lock = record.get_file(lock_name)
    except Exception as e:
        my.logger.warning(f"Could not get the lock file {lock_name} from Zenodo: {e}")
        my.lock = None
    else:
        directory = my.root / "environments"
        directory.mkdir(parents=True, exist_ok=True)
        my.lock = directory / lock_name
        my.lock.write_text(lock)

    return package_db["packages"]


def retire_installer(specs, installed):
    """Remove ``seamm-installer`` from the environment before ``seamm-manager``
    goes in.

    Both provide the ``seamm_installer`` module (the manager ships it as a
    compatibility shim for the plug-ins' installers), so they cannot coexist
    in one environment. Returns True if it was removed.
    """
    wants_manager = any(
        spec.split("==")[0].strip().lower() in ("seamm-manager", "seamm_manager")
        for spec in specs
    )
    if wants_manager and "seamm-installer" in installed:
        print("Removing seamm-installer, which seamm-manager replaces.")
        my.uv.uninstall("seamm-installer")
        return True
    return False


def constraints():
    """The lock file to pass to uv, or None if the user opted out or it is
    missing."""
    if getattr(my.options, "no_constraints", False):
        return None
    return my.lock if my.lock is not None and my.lock.exists() else None


def write_environment_snapshot(tag):
    """Record ``uv pip freeze`` under ``<root>/environments`` as the audit trail."""
    directory = my.root / "environments"
    directory.mkdir(parents=True, exist_ok=True)
    tstamp = datetime.now().isoformat(timespec="seconds")
    path = directory / f"{tstamp}_{tag}.txt"
    path.write_text(my.uv.freeze())
    return path


def get_metadata():
    """Get the metadata for this installation.

    Returns
    -------
    {str: any}
        A dictionary of the metadata.
    """
    # Get the metadata for the installation
    environment = my.environment
    user_data_path = Path(user_data_dir("seamm-manager", appauthor=False))
    path = user_data_path / (environment + ".json")

    if path.exists():
        try:
            with path.open("r") as fd:
                metadata = json.load(fd, cls=JSONDecoder)
        except Exception as e:
            my.logger.error(f"Exception reading the metadata for {environment}: {e}")
            my.logger.error(f"   File path is {path}")
            raise RuntimeError(f"Error reading metadata from {path}")
    else:
        metadata = {
            "environment": environment,
            "development": "dev" in environment,
            "gui-only": False,
        }
        user_data_path.mkdir(parents=True, exist_ok=True)
        with path.open("w") as fd:
            json.dump(metadata, fd, cls=JSONEncoder)

    return metadata


def initialize():
    """Set up the conda and pip wrappers. Conda is only needed for the external
    codes' own environments, so its absence is not an error here; the plug-in
    installers report it when they need it."""
    if my.conda is None:
        try:
            my.conda = Conda()
            my.logger.debug("Set up conda")
        except Exception as e:
            my.logger.info(f"Conda is not available: {e}")
            my.conda = None
    if my.pip is None:
        my.pip = Pip()


def package_info(package, conda_only=False):
    """Return info on a package in the SEAMM environment.

    Parameters
    ----------
    package:
        The name of the package.

    Returns
    -------
    (str, str)
        The installed version and "pypi", or (None, None) if not installed.
    """
    my.logger.info(f"Info on package '{package}'")
    packages = my.uv.list()
    key = package.lower().replace("_", "-")
    if key in packages:
        return packages[key]["version"], "pypi"
    return None, None


def run_plugin_installer(package, *args, verbose=True):
    """Run the plug-in installer with given arguments.

    Parameters
    ----------
    package
        The package name for the plug-in. Usually xxxx-step.
    args
        Command-line arguments for the plugin installer.

    Returns
    -------
    xxxx
        The result structure from subprocess.run, or None if there is no
        installer.
    """
    my.logger.info(f"run_plugin_installer {package} {args}")
    if package == "seamm":
        return None

    installer = my.uv.which(f"{package}-installer")
    if installer is None:
        my.logger.info("    no local installer, returning None")
        return None
    else:
        if verbose:
            print(f"   Running the plug-in specific installer for {package}.")
        result = subprocess.run([str(installer), *args], capture_output=True, text=True)
        my.logger.info(f"    ran the local installer: {result}")
        return result


def set_metadata(metadata):
    """Set the metadata for this installation.

    Parameters
    ----------
    {str: any}
        A dictionary of the metadata.
    """
    # Find the metadata for the installation
    environment = my.environment
    user_data_path = Path(user_data_dir("seamm-manager", appauthor=False))
    path = user_data_path / (environment + ".json")

    user_data_path.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fd:
        json.dump(metadata, fd, cls=JSONEncoder)
