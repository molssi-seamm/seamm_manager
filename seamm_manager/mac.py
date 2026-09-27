# -*- coding: utf-8 -*-
"""Mac OS specific routines handling unique operations.

* Creating the 'app'
* Installing Launch Agents to handle the Dashboard and JobServer
"""

import datetime
import getpass
import importlib.resources
import logging
import os
from pathlib import Path
import plistlib
import shutil
import subprocess

logger = logging.getLogger(__name__)

# First four bytes of a Mach-O file: thin 64-bit (either byte order) or universal.
_MACHO_MAGIC = (
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
)


def is_macho(path):
    """Whether the file is a compiled Mach-O program (not a script)."""
    try:
        with open(path, "rb") as fd:
            return fd.read(4) in _MACHO_MAGIC
    except OSError:
        return False


def _exec_script(text):
    """Make an old launcher script ``exec`` its command and pass arguments on.

    The old scripts ran the command as a child of bash, so the app's process was
    a bash waiting on SEAMM. With ``exec`` the app's process is SEAMM itself.
    """
    lines = text.rstrip("\n").split("\n")
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if line == "" or line.startswith("#"):
            continue
        if not line.startswith("exec "):
            lines[i] = f'exec {line} "$@"'
        break
    return "\n".join(lines) + "\n"


def install_launcher(contents_path, name, script):
    """Put the compiled launcher and the script it runs into an app bundle.

    macOS needs a bundle's executable to be a compiled program. A shell script
    carries no architecture, so on Apple Silicon without Rosetta the system
    asks the user to install Rosetta before launching it. The universal
    launcher shipped in ``data/macos_launcher`` (source beside it) runs
    ``Contents/Resources/<name>.sh`` with bash instead.

    Parameters
    ----------
    contents_path : pathlib.Path
        The bundle's ``Contents`` directory.
    name : str
        The app's name, which is also the executable's (``CFBundleExecutable``).
    script : str
        The text of the shell script to run.
    """
    macos_path = contents_path / "MacOS"
    macos_path.mkdir(mode=0o755, parents=True, exist_ok=True)
    resources_path = contents_path / "Resources"
    resources_path.mkdir(mode=0o755, parents=True, exist_ok=True)

    script_path = resources_path / f"{name}.sh"
    script_path.write_text(script)
    script_path.chmod(0o755)

    launcher = importlib.resources.files("seamm_manager") / "data" / "macos_launcher"
    exe_path = macos_path / name
    exe_path.unlink(missing_ok=True)
    with importlib.resources.as_file(launcher) as source:
        shutil.copyfile(source, exe_path)
    exe_path.chmod(0o755)


def _link_interpreter(python, exe_path):
    """Hard-link (or, across file systems, copy) the real interpreter to exe_path.

    Returns True if the file was (re)made, False if it was already current.
    """
    real = Path(python).resolve()
    if exe_path.exists():
        if exe_path.stat().st_ino == real.stat().st_ino:
            return False
        exe_path.unlink()
    try:
        os.link(real, exe_path)
    except OSError:
        shutil.copy2(real, exe_path)
    exe_path.chmod(0o755)
    return True


def create_service_bundle(directory, name, python, icons):
    """Make an app bundle whose executable is the Python interpreter itself.

    A service run as ``<venv>/bin/seamm-jobserver`` shows up everywhere on macOS
    as ``python3.12``, because the process is named after the program file that
    runs, the interpreter. With the interpreter inside ``<name>.app`` the process
    is called ``<name>`` and Activity Monitor shows the bundle's icon. uv's
    Python is a single statically linked file, so a hard link is enough.

    The service must set ``__PYVENV_LAUNCHER__`` to the venv's ``bin/python`` so
    that the interpreter uses the venv (CPython reads it at startup on macOS,
    as the python.org launcher does, and removes it from the environment).

    Parameters
    ----------
    directory : pathlib.Path
        Where to put the bundle, e.g. ``<root>/services``.
    name : str
        The bundle's name, which is also the process name, e.g. SEAMM-JobServer.
    python : pathlib.Path or str
        The venv's ``bin/python``; the interpreter it resolves to is linked.
    icons : pathlib.Path or str
        The icns file for the bundle.

    Returns
    -------
    pathlib.Path
        The bundle's executable, to run in place of ``python``.
    """
    contents_path = Path(directory) / f"{name}.app" / "Contents"
    macos_path = contents_path / "MacOS"
    resources_path = contents_path / "Resources"
    macos_path.mkdir(mode=0o755, parents=True, exist_ok=True)
    resources_path.mkdir(mode=0o755, parents=True, exist_ok=True)

    exe_path = macos_path / name
    _link_interpreter(python, exe_path)
    shutil.copyfile(Path(icons).expanduser(), resources_path / "SEAMM.icns")

    data = {
        "CFBundleIdentifier": f"org.molssi.seamm.{name}",
        "CFBundleName": name,
        "CFBundleExecutable": name,
        "CFBundleIconFile": "SEAMM.icns",
        "CFBundlePackageType": "APPL",
        "CFBundleDevelopmentRegion": "en",
        # A background agent: never in the Dock or the app switcher
        "LSUIElement": True,
        # Which environment this interpreter serves, for refresh_service_bundle
        "SEAMMPython": str(python),
    }
    with (contents_path / "Info.plist").open(mode="wb") as fd:
        plistlib.dump(data, fd)
    return exe_path


def refresh_service_bundle(bundle_path):
    """Re-link a service bundle's interpreter if its environment's has changed.

    Returns True if the link was remade (the service picks it up when it next
    restarts), False if it was current or the bundle is not a service bundle.
    """
    contents_path = Path(bundle_path) / "Contents"
    try:
        with (contents_path / "Info.plist").open(mode="rb") as fd:
            data = plistlib.load(fd)
    except (OSError, plistlib.InvalidFileException):
        return False
    python = data.get("SEAMMPython")
    name = data.get("CFBundleExecutable")
    if python is None or name is None or not Path(python).exists():
        return False
    return _link_interpreter(python, contents_path / "MacOS" / name)


def create_app(
    exe_path,
    *args,
    identifier=None,
    name="SEAMM",
    version="0.1.0",
    user_only=False,
    icons=None,
    copyright=None,
):
    """Create an application bundle for a Mac app.

    Parameters
    ----------
    exe_path : pathlib.Path or str
        The path to the executable (required). Either a path-like object or string
    identifier : str
        The bundle identifier. If None, is set to 'org.molssi.seamm.<name>'.
    name : str
        The name of the app
    version : str = "0.1.0"
        The version of the app.
    user_only : bool = False
        Whether to install for just the current user. Defaults to all users.
    icons : pathlib.Path or string
        Optional path to the icns file to use.
    copyright : str
        The human-readable copyright. Defaults to "Copyright 2017-xxxx MolSSI"
    """
    if identifier is None:
        identifier = "org.molssi.seamm." + name

    if copyright is None:
        year = datetime.date.today().year
        copyright = f"Copyright 2017-{year} MolSSI"

    if user_only:
        applications_path = Path("~/Applications").expanduser()
    else:
        applications_path = Path("/Applications")

    contents_path = applications_path / (name + ".app") / "Contents"
    contents_path.mkdir(mode=0o755, parents=True, exist_ok=True)

    # The compiled launcher, and the script it runs to start the executable
    path = Path(exe_path).expanduser().resolve()
    cmd = '"' + str(path) + '"'
    for arg in args:
        cmd += f" {arg}"
    install_launcher(contents_path, name, f'#!/bin/bash\nexec {cmd} "$@"\n')

    # And put the icons in place
    resources_path = contents_path / "Resources"
    icons_path = resources_path / (name + ".icns")
    path = Path(icons).expanduser().resolve()
    shutil.copyfile(path, icons_path)

    # write the PList file describing the app.
    data = {
        "CFBundleIdentifier": identifier,
        "CFBundleName": name,
        "CFBundleShortVersionString": version,
        "CFBundleExecutable": name,
        "CFBundleIconFile": icons_path.name,
        "CFBundleDevelopmentRegion": "en",
        "CFBundlePackageType": "APPL",
        "LSApplicationCategoryType": "public.app-category.education",
        "NSHumanReadableCopyright": copyright,
    }
    plist_path = contents_path / "Info.plist"
    with plist_path.open(mode="wb") as fd:
        plistlib.dump(data, fd)


def delete_app(name, missing_ok=False):
    """Delete the app given.

    Parameters
    ----------
    name : str
        The name of the app.
    missing_ok : bool = False
        Don't throw an error if the app does not exist.
    """
    apps = get_apps()
    if name in apps:
        shutil.rmtree(apps[name])
    elif not missing_ok:
        raise FileNotFoundError(f"App '{name}' does not exist.")


def get_apps():
    paths = (
        Path("~/Applications").expanduser(),
        Path("/Applications"),
    )
    apps = {}
    for path in paths:
        for file_path in path.glob("*.app"):
            name = file_path.stem
            apps[name] = file_path
    return apps


def update_app(name, version, missing_ok=False):
    """Update the version for a Mac app.

    Parameters
    ----------
    name : str
        The name of the app
    version : str
        The version of the app.
    missing_ok : bool = False
        Don't throw an error if the app does not exist.
    """
    apps = get_apps()
    if name in apps:
        app_path = Path(apps[name])
        contents_path = app_path / "Contents"
        plist_path = contents_path / "Info.plist"
        with plist_path.open(mode="rb") as fd:
            data = plistlib.load(fd)
        data["CFBundleShortVersionString"] = version

        # Bundles made by older versions have a shell script as the executable,
        # which asks for Rosetta on Apple Silicon. Move the script to Resources
        # and put the compiled launcher in its place.
        exe_name = data.get("CFBundleExecutable", name)
        exe_path = contents_path / "MacOS" / exe_name
        if exe_path.exists() and not is_macho(exe_path):
            install_launcher(
                contents_path, exe_name, _exec_script(exe_path.read_text())
            )
            logger.info(
                f"Replaced the script launcher of {name} with the compiled one."
            )
        with plist_path.open(mode="wb") as fd:
            plistlib.dump(data, fd)
    elif not missing_ok:
        raise FileNotFoundError(f"App '{name}' does not exist.")


class ServiceManager:
    def __init__(self, prefix=""):
        """A manager for handling services (agents) on MacOS.

        Parameters
        ----------
        prefix : str
            The prefix for all services, limiting searches, etc.
        """
        self.prefix = prefix
        self._data = None  # Dictionary of existing services
        self._uid = os.getuid()
        self._paths = (
            (Path("~/Library/LaunchAgents").expanduser(), f"gui/{self.uid}"),
            (Path("/Library/LaunchAgents"), f"gui/{self.uid}"),
            (Path("/Library/LaunchDaemons"), "system"),
        )

    @property
    def data(self):
        if self._data is None:
            self._data = {}
            pattern = self.prefix + ".*"
            for path, domain in self.paths:
                for file_path in path.glob(pattern):
                    name = file_path.stem
                    target = f"{domain}/{name}"
                    short_name = file_path.suffixes[-2][1:]
                    self._data[short_name] = (domain, target, file_path)
        return self._data

    @property
    def paths(self):
        return self._paths

    @property
    def uid(self):
        return self._uid

    def create(
        self,
        name,
        exe_path,
        *args,
        user_agent=True,
        user_only=True,
        stderr_path=None,
        stdout_path=None,
        exist_ok=False,
        environment=None,
    ):
        """Create a service on MacOS.

        The Mac supports three types of services. This function uses `user_agent` and
        `user_only` to control which is selected.

            1. A user Launch Agent for a single user, which runs while that user is
               logged in. (True, True)

            2. A Launch Agent installed by the admin that is available for all users,
               and runs when any user is logged in. (True, False)

            3. A system-wide service that runs when the machine is booted. (False, not
               used)

        Parameters
        ----------
        name : str
            The name of the agent
        exe_path : pathlib.Path or str
            The path to the executable (required). Either a path-like object or string
        args : []
            List of arguments for the program.
        user_agent : bool = True
            Whether to create a per-user agent (True) or system-wide daemon (False)
        user_only : bool = True
            Whether to install for just the current user (True) or all users (False).
            Only affects user agents, not daemons which are always system-wide.
        stderr_path : pathlib.Path or str = None
            The file to direct stderr. Defaults to "~/SEAMM/logs/<name>.out"
        stdout_path : pathlib.Path or str = None
            The file to direct stdout. Defaults to "~/SEAMM/logs/<name>.out"
        exist_ok : bool = False
            If True overwrite an existing file.
        environment : dict(str, str) = None
            Environment variables to set for the service.
        """
        identifier = self.prefix + "." + name

        if user_agent:
            if user_only:
                launchd_path = self.paths[0][0]
                plist_path = launchd_path / f"{identifier}.plist"
            else:
                launchd_path = self.paths[1][0]
                plist_path = launchd_path / f"{identifier}.plist"
        else:
            launchd_path = self.paths[2][0]
            plist_path = launchd_path / f"{identifier}.plist"

        if plist_path.exists():
            if not exist_ok:
                raise FileExistsError()

        if stderr_path is None:
            stderr_path = Path(f"~/SEAMM/logs/{name}.out").expanduser()
        if stdout_path is None:
            stdout_path = Path(f"~/SEAMM/logs/{name}.out").expanduser()

        # And the plist file itself.
        program_arguments = [str(exe_path)]
        for arg in args:
            program_arguments.append(str(arg))

        plist = {
            "Label": identifier,
            "KeepAlive": True,
            "ProgramArguments": program_arguments,
            "ProcessType": "Interactive",
            "StandardErrorPath": str(stderr_path),
            "StandardOutPath": str(stdout_path),
        }
        if environment:
            plist["EnvironmentVariables"] = {k: str(v) for k, v in environment.items()}

        # System-wide daemons need the username
        if not user_agent:
            username = getpass.getuser()
            plist["UserName"] = username

        # Reset the service data so it is re-read
        self._data = None

        # Write the file ... we may not have permission, so catch that.
        try:
            launchd_path.mkdir(parents=True, exist_ok=True)
            with plist_path.open(mode="wb") as fd:
                plistlib.dump(plist, fd)
        except PermissionError:
            path = Path("~/Downloads").expanduser() / f"{identifier}.plist"
            with path.open(mode="wb") as fd:
                plistlib.dump(plist, fd)
            print(f"\nYou do not have permission to write to {launchd_path}.")
            print("If you have administrator access, run the following commands:")
            print("")
            print(f"    sudo mv {path} {plist_path}")
            print(
                "    sudo chown root:wheel /Library/LaunchDaemons/org.molssi.seamm"
                ".dashboard.plist"
            )
            print("")
            print("To move the temporary copy of the file to the correct locations.")
            print("Then start the services as follows:")
            print("")
        except Exception as e:
            print("Caught error?")
            print(e)
            print()
            raise

    def delete(self, service, ignore_errors=False):
        services = self.list()
        if service in services:
            domain, service_target, path = self.data[service]
            # Check if it is running
            if self.is_running(service):
                self.stop(service)
            # Now remove the files
            path.unlink(missing_ok=True)
            # Fix up service data
            del self.data[service]
        else:
            # Check if the plist file exists, and remove if it does.
            for path, _ in self.paths:
                launchd_path = path / f"{self.prefix}.{service}.plist"
                launchd_path.unlink(missing_ok=True)

    def file_path(self, service):
        "Return the path to the plist file for the service."
        data = self.data
        if service in data:
            return data[service][2]
        return ""

    def is_installed(self, service):
        return service in self.list()

    def is_running(self, service):
        result = False
        services = self.list()
        if service in services:
            service_target = self.data[service][1]
            cmd = f"launchctl print {service_target}"

            result = subprocess.run(cmd, shell=True, text=True, capture_output=True)

            if result.returncode == 0:
                result = True
            else:
                result = False
        else:
            result = False
        return result

    def list(self):
        return self.data.keys()

    def restart(self, service, ignore_errors=False):
        self.stop(service, ignore_errors=ignore_errors)
        self.start(service, ignore_errors=ignore_errors)

    def start(self, service, ignore_errors=False):
        if not self.is_running(service):
            services = self.list()
            if service in services:
                domain, service_target, path = self.data[service]

                cmd = f"launchctl bootstrap {domain} {path}"
                result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
                if result.returncode != 0 and not ignore_errors:
                    raise RuntimeError(
                        f"Starting the service '{service}' was not successful:\n"
                        f"{result.stderr}"
                    )
            elif not ignore_errors:
                raise RuntimeError(
                    f"Service '{service}' cannot be started because it is not installed"
                )

    def status(self, service):
        status = {"service": service}
        services = self.list()
        if service in services:
            status["exists"] = True
            service_target = self.data[service][1]
            cmd = f"launchctl print {service_target}"

            result = subprocess.run(cmd, shell=True, text=True, capture_output=True)

            status["running"] = result.returncode == 0

            # Get the root directory and, for the dashboard, port
            path = self.data[service][2]
            logger.debug(f"Checking {path} for the root and port")
            with path.open(mode="rb") as fd:
                data = plistlib.load(fd)

            root = None
            port = None
            name = None
            if "ProgramArguments" in data:
                lines = iter(data["ProgramArguments"])
                for line in lines:
                    if "--root" in line:
                        root = next(lines)
                    if "--port" in line:
                        port = next(lines)
                    if "--dashboard-name" in line:
                        name = next(lines)
            status["root"] = root
            status["port"] = port
            status["dashboard name"] = name
        else:
            status["exists"] = False
        return status

    @staticmethod
    def _wait_until_gone(service_target, timeout=15.0, interval=0.2):
        """Wait for launchd to finish removing a job; True if it is gone."""
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cmd = f"launchctl print {service_target}"
            result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
            if result.returncode != 0:
                return True
            time.sleep(interval)
        return False

    def stop(self, service, ignore_errors=False):
        services = self.list()
        if service in services:
            domain, service_target, path = self.data[service]
            # Check if it is running
            if self.is_running(service):
                cmd = f"launchctl bootout {service_target}"
                result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
                if result.returncode == 0:
                    # bootout returns before launchd has removed the job. Wait,
                    # or an immediate start (services create --force) sees it
                    # as still running and silently does nothing.
                    self._wait_until_gone(service_target)
                elif not ignore_errors:
                    raise RuntimeError(f"Could not stop the service '{service}':")
