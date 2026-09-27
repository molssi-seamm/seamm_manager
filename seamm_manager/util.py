# -*- coding: utf-8 -*-

"""Utility methods for the SEAMM installer."""

from datetime import datetime
import json
import os
from packaging.version import Version
import requests
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


def sync_manager():
    """Put the running manager's own release into the environment.

    The package list (and lock) on Zenodo names the manager version current
    when the nightly job last ran, so for up to a day after a release the
    environment would get the previous manager -- and the plug-ins' installers
    run with that copy. If this manager is a clean release newer than what
    the environment holds, install exactly this version there, outside the
    lock's constraints (only this package). Returns the version installed, or
    None if nothing was done.
    """
    import seamm_manager

    version = seamm_manager.__version__
    if "+" in version or "untagged" in version or version.startswith("0"):
        return None  # a development build; leave the environment alone
    installed = my.uv.list().get("seamm-manager", {}).get("version")
    if installed is None:
        return None  # not installed there at all (not in the list yet)
    if Version(installed) >= Version(version):
        return None
    print(f"Updating seamm-manager in the environment to this release, {version}.")
    my.uv.install(f"seamm-manager=={version}")
    return version


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


def pypi_latest(package, timeout=10):
    """The newest release of ``package`` on PyPI, or None if it cannot be found.

    Asks PyPI's simple index (the JSON form of PEP 691) -- the index uv installs
    from -- so a release made after the nightly package list is visible at once and
    is certainly installable. (PyPI's JSON API was used before, but its CDN served a
    stale copy to Python's requests while the simple index already had the release.)
    Pre-releases and yanked files are ignored. Network problems, an unknown project
    or an odd response give None: the caller falls back to the package list.
    """
    url = f"https://pypi.org/simple/{package}/"
    headers = {
        "Accept": "application/vnd.pypi.simple.v1+json",
        "Cache-Control": "no-cache",
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code != 200:
            return None
        data = response.json()
        yanked = {}
        for item in data.get("files", []):
            filename = item.get("filename", "")
            for version in data.get("versions", []):
                if f"-{version}-" in filename or f"-{version}.tar" in filename:
                    yanked.setdefault(version, []).append(bool(item.get("yanked")))
        candidates = []
        for version in data.get("versions", []):
            parsed = Version(version)
            if parsed.is_prerelease:
                continue
            if version in yanked and all(yanked[version]):
                continue
            candidates.append(parsed)
        return str(max(candidates)) if candidates else None
    except Exception:
        return None


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


def _installers_honour_policy():
    """Whether the plug-ins' installers will respect this installation's policy.

    The installers use the seamm-manager in the installation's own environment, not
    this one. In an installation that does not own its codes (policy ``shared`` or
    ``prefixed``), an older copy there would create or update the shared conda
    environments. True for the default installation, or when that copy has the
    policy code (checked by importing it, not by comparing versions).
    """
    from .policy import code_environment_policy

    if code_environment_policy(my.root) == "own":
        return True
    python = my.uv.which("python")
    if python is None:
        return False
    result = subprocess.run(
        [str(python), "-c", "import seamm_manager.policy"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


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
    elif (
        args
        and args[0] in ("install", "update", "uninstall")
        and not (_installers_honour_policy())
    ):
        print(
            f"   Skipped the installer for {package}: this installation does not "
            "manage its own codes, but its environment has a seamm-manager too old "
            "to know that. Run 'seamm-manager update seamm-manager' for it first."
        )
        return None
    else:
        if verbose:
            print(f"   Running the plug-in specific installer for {package}.")
        # Tell the installer which installation it is working on, so the code's
        # .ini file goes into this root rather than ~/SEAMM.
        env = {**os.environ, "SEAMM_ROOT": str(my.root)}
        result = subprocess.run(
            [str(installer), *args], capture_output=True, text=True, env=env
        )
        my.logger.info(f"    ran the local installer: {result}")
        # An installer that failed used to fail silently: its output was only
        # logged, so e.g. "conda not found" left the code uninstalled with no
        # word to the user. Show the tail of what it said.
        if result.returncode != 0:
            text = (result.stderr or result.stdout or "").strip().splitlines()
            tail = "\n".join("      " + line for line in text[-6:])
            print(
                f"   The installer for {package} failed (exit {result.returncode}):"
                f"\n{tail}\n   Fix the cause and run "
                f"'seamm-manager install --rerun-installers {package}'."
            )
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
