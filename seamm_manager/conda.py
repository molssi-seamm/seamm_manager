# -*- coding: utf-8 -*-
import json
import shutil
import logging
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import sys
import warnings

import yaml

logger = logging.getLogger(__name__)


# Where conda is usually installed when it is not on the PATH, e.g. for an
# app launched from the Dock or a service, whose PATH is minimal.
_CONDA_LOCATIONS = (
    "~/miniforge3",
    "~/mambaforge",
    "~/miniconda3",
    "~/anaconda3",
    "~/opt/miniconda3",
    "~/opt/anaconda3",
    "/opt/homebrew/Caskroom/miniforge/base",
    "/opt/miniforge3",
    "/opt/miniconda3",
    "/opt/anaconda3",
    "/opt/conda",
    "/usr/local/miniforge3",
    "/usr/local/miniconda3",
    "/usr/local/anaconda3",
)


def find_conda():
    """The path to the conda executable, or None.

    Tries, in order: ``$CONDA_EXE`` (set by an activated conda shell), the
    PATH, then the usual installation directories. When found somewhere
    other than the PATH, its directory is added to the PATH so that
    sub-processes (``conda run``, the plug-in installers) find it too.
    """
    conda = os.environ.get("CONDA_EXE")
    if conda and Path(conda).exists():
        return conda
    conda = shutil.which("conda")
    if conda is not None:
        return conda
    for location in _CONDA_LOCATIONS:
        base = Path(location).expanduser()
        for sub in ("condabin", "bin"):
            candidate = base / sub / "conda"
            if candidate.exists():
                os.environ["PATH"] = f"{candidate.parent}{os.pathsep}" + os.environ.get(
                    "PATH", ""
                )
                return str(candidate)
    return None


def split_environment_file(environment_file):
    """Split a conda environment file into its conda part and its pip part.

    Returns
    -------
    (str, [str], [str])
        The YAML text of the file without its ``pip:`` entry; the pip
        requirements that are bare names (``torch``); and those carrying a
        version specifier or other qualification (``xnns>=0.3.0``,
        ``e3nn==0.4.4``, a URL, ``pkg[extra]``).
    """
    text = Path(environment_file).read_text()
    data = yaml.safe_load(text) or {}
    deps = data.get("dependencies") or []
    conda_deps, bare, specified = [], [], []
    for item in deps:
        if isinstance(item, dict) and "pip" in item:
            for req in item["pip"] or []:
                req = str(req).strip()
                if req == "" or req.startswith("-"):
                    continue  # options such as --index-url are not requirements
                if re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", req):
                    bare.append(req)
                else:
                    specified.append(req)
        else:
            conda_deps.append(item)
    data["dependencies"] = conda_deps
    return yaml.safe_dump(data, sort_keys=False), bare, specified


class Conda(object):
    """
    Class for handling conda

    Attributes
    ----------

    """

    def __init__(self, logger=logger):
        logger.debug(f"Creating Conda {str(type(self))}")

        self._is_installed = False
        self._data = None
        self.logger = logger
        self.channels = ["local", "conda-forge"]
        self.root_path = None

        self._initialize()

    def __str__(self):
        """Print the conda information in a nice format."""
        if self.is_installed:
            return json.dumps(self._data, indent=4, sort_keys=True)
        else:
            return "Conda does not appear to be installed!"

    @property
    def active_environment(self):
        """The currently active Conda environment."""
        if self.is_installed:
            return os.environ["CONDA_DEFAULT_ENV"]
        else:
            return None

    @property
    def environments(self):
        """The available conda environments."""
        self.logger.debug("Getting list of environment")
        self.logger.debug(f"   root path = {self.root_path}")
        if self.is_installed:
            result = []
            for env in self._data["envs"]:
                path = Path(env)
                self.logger.debug(f"   environment {env}")
                if path == self.prefix:
                    result.append("base")
                    self.logger.debug("    --> base")
                else:
                    if path.name == "miniconda":
                        # Windows is different.
                        result.append("base")
                        self.logger.debug("    --> base")
                    else:
                        result.append(path.name)
                        self.logger.debug(f"    --> {path.name}")
            return result
        else:
            return None

    @property
    def is_installed(self):
        """Whether we have access to conda."""
        return self._is_installed

    @property
    def prefix(self):
        """The path for the conda root."""
        if self.is_installed:
            return self._data["conda_prefix"]
        else:
            return None

    @property
    def root_prefix(self):
        """The root prefix of the conda installation."""
        if self.is_installed:
            return self._data["root_prefix"]
        else:
            return None

    def activate(self, environment):
        """Activate the requested environment."""
        if not self.is_installed:
            raise RuntimeError("Conda is not installed.")
        if not self.exists(environment):
            raise ValueError(f"Conda environment '{environment}' does not exist.")

        # Set the various environment variables that 'conda activate' does
        if "CONDA_SHLVL" in os.environ:
            level = int(os.environ["CONDA_SHLVL"])
            os.environ[f"CONDA_PREFIX_{level}"] = os.environ["CONDA_PREFIX"]
            level += 1
            os.environ["CONDA_SHLVL"] = str(level)
        os.environ["CONDA_PROMPT_MODIFIER"] = f"({environment})"

        path = os.environ["PATH"].split(os.pathsep)
        if level == 1:
            path.insert(0, str(self.path(environment) / "bin"))
        elif level >= 2:
            path[0] = str(self.path(environment) / "bin")
        os.environ["PATH"] = os.pathsep.join(path)

        os.environ["CONDA_PREFIX"] = str(self.path(environment))
        os.environ["CONDA_DEFAULT_ENV"] = environment

    def _initialize(self):
        """Get the information about the current Conda installation."""
        self.conda_exe = find_conda()
        if self.conda_exe is None:
            self.logger.info("Cannot find conda: not on the PATH nor in a usual place")
            self._is_installed = False
            self._data = None
            return
        command = f"'{self.conda_exe}' info --json"
        args = shlex.split(command)
        try:
            result = subprocess.check_output(
                args, shell=False, text=True, stderr=subprocess.STDOUT
            )
        except subprocess.CalledProcessError as e:
            self.logger.debug(f"Calling conda, returncode = {e.returncode}")
            self.logger.debug(f"Output:\n\n{e.output}\n\n")

            self._is_installed = False
            self._data = None
            return

        # Fixing error on condaforge
        if result is None:
            self._is_installed = False
            self._data = None
            return

        self._is_installed = True
        self.logger.debug(f"\nconda info --json\n\n{result}\n\n")
        try:
            self._data = json.loads(result)
        except Exception:
            self._is_installed = False
            self._data = None
            return

        # Find the root path for the environment
        # Typically the base environment is e.g. ~/opt/miniconda3 and all other
        # environments are in ~/opt/miniconda3/envs/ (~/opt/anaconda3).
        # We want the path for the base environment.
        #
        # In some installations there are more than one base environment! So
        # pick the one that looks like 'anacondaX' or 'minicondaX'.
        # As a last resort, just pick one.
        # self.logger.debug("Finding the conda root path")
        # roots = set()
        # for env in self._data["envs"]:
        #     path = Path(env)
        #     self.logger.debug(f"    environment path {path}")
        #     if path.parent.name == "envs":
        #         roots.add(path.parent.parent)
        #     else:
        #         roots.add(path)
        # for root in roots:
        #     name = root.name
        #     if "miniconda" in name or "anaconda" in name:
        #         break

        # self.root_path = root
        # root_prefix is the base installation whether or not an environment is
        # active (active_prefix is null when nothing is activated, e.g. for an
        # app launched from the Dock or a service).
        root = self._data.get("root_prefix") or self._data.get("conda_prefix")
        if root:
            self.root_path = Path(root)
        else:
            self.root_path = Path(self._data["active_prefix"]).parent
            if self.root_path.name == "envs":
                self.root_path = self.root_path.parent

        tmp = "\n\t".join(self.environments)
        self.logger.info(f"environments:\n\t{tmp}")

    def create_environment(self, environment_file, name=None, force=False):
        """Create a Conda environment.

        Parameters
        ----------
        environment_file : str or pathlib.Path
            The name or path to the environment file.
        name : str = None
            The name of the environment. Defaults to that given in the
            environment file.
        force : bool = False
            Whether to overwrite an existing environment.
        """
        if isinstance(environment_file, Path):
            path = str(environment_file)
        else:
            path = environment_file

        command = f"'{self.conda_exe}' env create --file '{path}'"
        if force:
            command += " --force"
        if name is not None:
            # Using the name leads to odd paths, so be explicit.
            path = self._resolve_environment_path(name)
            command += f" --prefix '{str(path)}'"
        self.logger.debug(f"command = {command}")
        try:
            self._execute(command)
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Calling conda, returncode = {e.returncode}")
            self.logger.warning(f"Output:\n\n{e.output}\n\n")
            self._initialize()
            raise
        self._initialize()

    def delete_environment(self, name):
        """Delete a Conda environment.

        Parameters
        ----------
        name : str
            The name of the environment.
        """
        # Using the name leads to odd paths, so be explicit.
        path = self._resolve_environment_path(name)

        command = f"'{self.conda_exe}' env remove --yes  --prefix '{str(path)}'"

        self.logger.debug(f"command = {command}")
        try:
            self._execute(command)
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Calling conda, returncode = {e.returncode}")
            self.logger.warning(f"Output:\n\n{e.output}\n\n")
            self._initialize()
            raise
        self._initialize()

    def exists(self, environment):
        """Whether an environment exists.

        Parameters
        ----------
        environment : str
           The name of the environment.

        Returns
        -------
        bool
            True if the environment exists, False otherwise.
        """
        return environment in self.environments

    def export_environment(self, environment, path=None):
        """Export the definition of an environment.

        Parameters
        ----------
        environment : str
            The name of the environment to export
        path : str or pathlib.Path = None
            An optional filename to export to
        """
        environment_path = self._resolve_environment_path(environment)
        command = f"'{self.conda_exe}' env export --prefix '{environment_path}'"
        if path is not None:
            command += f" --file '{path}'"
        try:
            result, stdout, stderr = self._execute(command)
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Calling conda, returncode = {e.returncode}")
            self.logger.warning(f"Output:\n\n{e.output}\n\n")
            raise

    def install(
        self,
        package,
        environment=None,
        channels=None,
        override_channels=True,
        progress=True,
        newline=True,
        update=None,
    ):
        """Install a package in an environment..

        Parameters
        ----------
        package: strip
            The package to install.
        environment : str
            The name of the environment to list, defaults to the current.
        channels: [str] = None
            A list of channels to search. defaults to the list in self.channels.
        override_channels: bool = True
            Ignore channels configured in .condarc and the default channel.
        progress : bool = True
            Whether to show progress dots.
        newline : bool = True
            Whether to print a newline at the end if showing progress
        update : None or method
            Method to call to e.g. update a progress bar
        """
        command = f"'{self.conda_exe}' install --yes "
        if environment is not None:
            # Using the name leads to odd paths, so be explicit.
            # command += f" --name '{environment}'"
            path = self._resolve_environment_path(environment)
            command += f" --prefix '{str(path)}'"
        if override_channels:
            command += " --override-channels"
        if channels is None:
            for channel in self.channels:
                command += f" -c {channel}"
        else:
            for channel in channels:
                command += f" -c {channel}"

        if isinstance(package, list):
            packages = " ".join(package)
            command += f" {packages}"
        else:
            command += f" {package}"

        self._execute(command, progress=progress, newline=newline, update=update)

    def list(
        self,
        environment=None,
        query=None,
        fullname=False,
        update=None,
        explicit=False,
    ):
        """The contents of an environment.

        Parameters
        ----------
        environment : str
            The name of the environment to list, defaults to the current.
        query: str
            Regexp for package names, default to all packages
        fullname : bool = False
            For a query, match only the full name
        update : None or method
            Method to call to e.g. update a progress bar
        explicit : bool = False
            If true, get an explicit list, suitable for "conda create --file"

        Returns
        -------
        dict
            A dictionary keyed by the package names.
        """
        if explicit:
            command = f"'{self.conda_exe}' list --explicit"
        else:
            command = f"'{self.conda_exe}' list --json"
        if environment is not None:
            path = self._resolve_environment_path(environment)
            command += f" --prefix '{path}'"
        if fullname:
            command += " --full-name"
        if query is not None:
            command += f" '{query}'"

        self.logger.debug(f"command = {command}")

        try:
            result, stdout, stderr = self._execute(
                command, progress=False, update=update
            )
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Calling conda, returncode = {e.returncode}")
            self.logger.warning(f"Output:\n\n{e.output}\n\n")
            raise

        if stdout is None or stdout == "":
            return None

        if explicit:
            return stdout

        result = {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for x in json.loads(stdout):
                if "version" in x:
                    result[x["name"]] = x
        return result

    def path(self, environment):
        """The path for an environment.

        Parameters
        ----------
        environment : str
            The name of the environment to remove.

        Returns
        -------
        pathlib.Path
            The path to the environment.
        """
        if environment == "base":
            return Path(self.prefix)
        else:
            for env in self._data["envs"]:
                if env != self.prefix:
                    path = Path(env)
                    if environment == path.name:
                        return path
        raise ValueError(f"Environment '{environment}' not found.")

    def remove_environment(self, environment):
        """Remove an existing environment.

        Parameters
        ----------
        environment : str
            The name of the environment to remove.
        """
        path = self._resolve_environment_path(environment)
        command = f"'{self.conda_exe}' env remove --prefix '{path}' --yes --json"
        try:
            self._execute(command)
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Calling conda, returncode = {e.returncode}")
            self.logger.warning(f"Output:\n\n{e.output}\n\n")

            self._initialize()
            raise
        self._initialize()

    def search(
        self,
        query=None,
        channels=None,
        override_channels=True,
        progress=True,
        newline=True,
        update=None,
    ):
        """Run conda search, returning a dictionary of packages.

        Parameters
        ----------
        query: str = None
            The pattern to search, Defaults to None, meaning all packages.
        channels: [str] = None
            A list of channels to search. defaults to the list in self.channels.
        override_channels: bool = True
            Ignore channels configured in .condarc and the default channel.
        progress : bool = True
            Whether to show progress dots.
        newline : bool = True
            Whether to print a newline at the end if showing progress
        update : None or method
            Method to call to e.g. update a progress bar

        Returns
        -------
        dict
            A dictionary of packages, with versions for each.
        """
        command = f"'{self.conda_exe}' search --json"
        if override_channels:
            command += " --override-channels"
        if channels is None:
            for channel in self.channels:
                command += f" -c {channel}"
        else:
            for channel in channels:
                command += f" -c {channel}"
        if query is not None:
            command += f" {query}"

        _, stdout, _ = self._execute(
            command, progress=progress, newline=newline, update=update
        )
        try:
            output = json.loads(stdout)
        except Exception as e:
            self.logger.warning(
                f"expected output from {command}, got {stdout}", exc_info=e
            )
            return None

        if "error" in output:
            return None

        result = {}
        for package, data in output.items():
            result[package] = {
                "channel": data[-1]["channel"],
                "version": data[-1]["version"],
                "description": "not available",
            }

        return result

    def show(self, package):
        """Show the information for a single package.

        Parameters
        ----------
        package : str
            The name of the package.
        """
        # Should be able to use fullname=True, but conda has a bug! Use regexp.
        result = self.list(query="^" + package + "$")
        if result is None:
            return None
        if package not in result:
            return None
        return result[package]

    def update(
        self,
        package=None,
        environment=None,
        channels=None,
        override_channels=True,
        progress=True,
        newline=True,
        all=False,
        update=None,
    ):
        """Update a package in an environment..

        Parameters
        ----------
        package: strip
            The package to update.
        environment : str
            The name of the environment to list, defaults to the current.
        channels: [str] = None
            A list of channels to search. defaults to the list in self.channels.
        override_channels: bool = True
            Ignore channels configured in .condarc and the default channel.
        progress : bool = True
            Whether to show progress dots.
        newline : bool = True
            Whether to print a newline at the end if showing progress
        all : bool = False
            Fully update the environment.
        update : None or method
            Method to call to e.g. update a progress bar
        """
        command = f"'{self.conda_exe}' update --yes "
        if environment is not None:
            # Using the name leads to odd paths, so be explicit.
            # command += f" --name '{environment}'"
            path = self._resolve_environment_path(environment)
            command += f" --prefix '{str(path)}'"
        if override_channels:
            command += " --override-channels"
        if channels is None:
            for channel in self.channels:
                command += f" -c {channel}"
        else:
            for channel in channels:
                command += f" -c {channel}"

        if all:
            command += " --all"
        else:
            if package is None:
                raise RuntimeError("Conda update requires either '--all' of a package")
            if isinstance(package, list):
                packages = " ".join(package)
                command += f" {packages}"
            else:
                command += f" {package}"

        self._execute(command, progress=progress, newline=newline, update=update)

    def uninstall(
        self,
        package,
        environment=None,
        channels=None,
        override_channels=True,
        progress=True,
        newline=True,
        update=None,
    ):
        """Uninstall a package from an environment..

        Parameters
        ----------
        package: str or [str]
            The package to uninstall install.
        environment : str
            The name of the environment to list, defaults to the current.
        channels: [str] = None
            A list of channels to search. defaults to the list in self.channels.
        override_channels: bool = True
            Ignore channels configured in .condarc and the default channel.
        progress : bool = True
            Whether to show progress dots.
        newline : bool = True
            Whether to print a newline at the end if showing progress
        update : None or method
            Method to call to e.g. update a progress bar
        """
        command = f"'{self.conda_exe}' uninstall --yes "
        if environment is not None:
            path = self._resolve_environment_path(environment)
            command += f" --prefix '{path}'"
        if override_channels:
            command += " --override-channels"
        if channels is None:
            for channel in self.channels:
                command += f" -c {channel}"
        else:
            for channel in channels:
                command += f" -c {channel}"

        if isinstance(package, str):
            command += f" {package}"
        else:
            command += " "
            command += " ".join(package)

        self._execute(command, progress=progress, update=update)

    def update_environment(
        self, environment_file, name=None, update=None, pip_policy="conservative"
    ):
        """Update a Conda environment from an environment file.

        Parameters
        ----------
        environment_file : str or pathlib.Path
            The name or path to the environment file.
        name : str = None
            The name of the environment. Defaults to the current environment.
        pip_policy : str = "conservative"
            How the file's ``pip:`` section is applied. ``"conda"`` lets conda
            do it, which runs ``pip install -U`` and so upgrades every pip
            package, including a bare ``torch`` that a machine may hold at a
            driver-matched build. ``"conservative"`` (the default) applies the
            conda part with conda, then bare pip names without upgrading (they
            must merely be present) and requirements with a version specifier
            with ``-U`` (kept current within their spec).
        """
        if isinstance(environment_file, Path):
            path = str(environment_file)
        else:
            path = environment_file
        prefix = None
        if name is not None:
            # Using the name leads to odd paths, so be explicit.
            prefix = self._resolve_environment_path(name)

        bare, specified = [], []
        tmp = None
        if pip_policy == "conservative":
            conda_text, bare, specified = split_environment_file(path)
            tmp = tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False)
            tmp.write(conda_text)
            tmp.close()
            path = tmp.name

        command = f"'{self.conda_exe}' env update --file '{path}'"
        if prefix is not None:
            command += f" --prefix '{str(prefix)}'"
        self.logger.debug(f"command = {command}")
        try:
            self._execute(command, update=update)
            if bare:
                self._pip_in_environment(prefix, bare, upgrade=False, update=update)
            if specified:
                self._pip_in_environment(prefix, specified, upgrade=True, update=update)
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Calling conda, returncode = {e.returncode}")
            self.logger.warning(f"Output:\n\n{e.output}\n\n")
            raise
        finally:
            if tmp is not None:
                Path(tmp.name).unlink(missing_ok=True)

    def _pip_in_environment(self, prefix, requirements, upgrade=False, update=None):
        """Run pip in the environment for the given requirements."""
        target = "" if prefix is None else f" -p '{str(prefix)}'"
        flag = " --upgrade" if upgrade else ""
        reqs = " ".join(f"'{r}'" for r in requirements)
        command = f"'{self.conda_exe}' run{target} pip install{flag} {reqs}"
        self.logger.debug(f"command = {command}")
        self._execute(command, update=update)

    def _execute(
        self, command, poll_interval=2, progress=True, newline=True, update=None
    ):
        """Execute the command as a subprocess.

        Parameters
        ----------
        command : str
            The command, with any arguments, to execute.
        poll_interval : int
            Time interval in seconds for checking for output.
        progress : bool = True
            Whether to show progress dots.
        newline : bool = True
            Whether to print a newline at the end if showing progress
        update : None or method
            Method to call to e.g. update a progress bar
        """
        self.logger.info(f"running '{command}'")
        args = shlex.split(command)
        process = subprocess.Popen(
            args,
            bufsize=1,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        n = 0
        stdout = ""
        stderr = ""
        while True:
            self.logger.debug("    checking if finished")
            result = process.poll()
            if result is not None:
                self.logger.info(f"    finished! result = {result}")
                break
            try:
                self.logger.debug("    calling communicate")
                output, errors = process.communicate(timeout=poll_interval)
            except subprocess.TimeoutExpired:
                self.logger.debug("    timed out")
                if progress:
                    if update is None:
                        print(".", end="")
                        n += 1
                        if n >= 50:
                            print("")
                            n = 0
                        sys.stdout.flush()
                    else:
                        print("Conda execute calling update")
                        update()
            else:
                if output != "":
                    stdout += output
                    self.logger.debug(output)
                if errors != "":
                    stderr += errors
                    self.logger.debug(f"stderr: '{errors}'")
        if progress and newline and n > 0:
            if update is None:
                print("")
        return result, stdout, stderr

    def _resolve_environment_path(self, pathname):
        """Get the path given either a name or path for an environment.

        A name is looked up among conda's environments, wherever they are. A new
        environment goes in the first writable directory of conda's
        ``envs_dirs`` (set e.g. in ~/.condarc), as ``conda create -n`` would put
        it. On a shared machine whose conda is provided centrally, the base
        installation's own ``envs`` directory is usually read-only.
        """
        if Path(pathname).is_absolute():
            return Path(pathname)
        data = self._data or {}
        for env in data.get("envs", []):
            path = Path(env)
            if path.name == pathname and path != self.root_path:
                return path
        for directory in data.get("envs_dirs", []):
            if _writable_directory(Path(directory)):
                return Path(directory) / pathname
        return self.root_path / "envs" / pathname


def _writable_directory(path):
    """Whether environments can be created in this directory (made if needed)."""
    while not path.exists():
        if path.parent == path:
            return False
        path = path.parent
    return path.is_dir() and os.access(path, os.W_OK | os.X_OK)
