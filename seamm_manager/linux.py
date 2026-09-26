# -*- coding: utf-8 -*-
"""Linux OS specific routines handling unique operations.

* Installing daemons to handle the Dashboard and JobServer
"""

from configparser import ConfigParser
import getpass
import logging
import os
from pathlib import Path
import shlex
import shutil
from string import Template
import subprocess

logger = logging.getLogger(__name__)

app_text = """\
[Desktop Entry]
# The version of the desktop entry specification to which this file complies
Version=1.5

Type=Application
Name=${name}
Comment=${comment}
Exec=${exe}
Icon=${icon}
Terminal=false
SingleMainWindow=true
Categories=Education;Science;Chemistry;Physics
"""

user_text = """\
[Unit]
Description=${description}
[Service]
WorkingDirectory=${wd}
ExecStart=${exe}
Type=simple
TimeoutStopSec=10
Restart=on-failure
RestartSec=5
[Install]
WantedBy=default.target
"""

service_text = """\
[Unit]
Description=${description}
[Service]
User=${username}
WorkingDirectory=${wd}
ExecStart=${exe}
Type=simple
TimeoutStopSec=10
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
"""


def list_to_dict(lst):
    res_dct = {lst[i]: lst[i + 1] for i in range(0, len(lst), 2)}
    return res_dct


def create_app(
    exe_path,
    *args,
    name="SEAMM",
    comment="the Simulation Environment for Atomistic and Molecular Modeling",
    user_only=False,
    icons=None,
    **kwargs,
):
    """Create an application bundle for a Linux app.

    Parameters
    ----------
    exe_path : pathlib.Path or str
        The path to the executable (required). Either a path-like object or string
    name : str
        The name of the app
    comment : str = "the Simulation Environment for Atomistic and Molecular Modeling"
        A comment for use in tooltips, etc.
    user_only : bool = False
        Whether to install for just the current user or all users (default).
    icons : pathlib.Path or str
        Optional path to the icns files to use.
    kwargs :
        Other keywords arguments for compatibility with other OS's. Ignored
    """
    if user_only:
        applications_path = Path("~/.local/share/applications/").expanduser()
        applications_path.mkdir(mode=0o755, parents=True, exist_ok=True)
    else:
        applications_path = Path("/usr/local/share/applications/")

    # And put the icons in place
    icons_path = Path("~/.local/share/icons/hicolor/").expanduser()
    path = Path(icons).expanduser().resolve()
    for icon in path.iterdir():
        dimensions = icon.stem
        if "x" in dimensions:
            directory = icons_path / dimensions / "apps"
            directory.mkdir(mode=0o755, parents=True, exist_ok=True)
            shutil.copyfile(icon, directory / f"{name}.png")

    # And the desktop file itself.
    desktop = Template(app_text).substitute(
        name=name,
        comment=comment,
        exe=exe_path,
        icon=name,
    )
    desktop_path = applications_path / f"{name}.desktop"
    desktop_path.write_text(desktop)


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
        apps[name].unlink(missing_ok=missing_ok)
    elif not missing_ok:
        raise FileNotFoundError(f"App '{name}' does not exist.")


def get_apps():
    """Return a list of all user applications.

    Returns
    -------
    {str: str}
        Dictionary of app names and paths to the desktop file.
    """
    paths = (
        Path("~/.local/share/applications/").expanduser(),
        Path("/usr/local/share/applications/"),
    )
    apps = {}
    for path in paths:
        for file_path in path.glob("*.desktop"):
            name = file_path.stem
            apps[name] = file_path
    return apps


def update_app(name, version, missing_ok=False):
    """Update the version for a Linux app.

    Since the desktop file does not have the version,
    nothing to do.

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
        pass
    elif not missing_ok:
        raise FileNotFoundError(f"App '{name}' does not exist.")


class ServiceManager:
    def __init__(self, prefix=""):
        """A manager for handling services on Linux

        Parameters
        ----------
        prefix : str
            The prefix for all services, limiting searches, etc.
        """
        self.prefix = prefix
        self._data = None  # Dictionary of existing services
        self._uid = os.getuid()
        self._paths = (
            (Path("~/.config/systemd/user").expanduser(), "user"),
            (Path("/etc/systemd/user"), "all users"),
            (Path("/etc/systemd/system"), "system"),
        )

    @property
    def data(self):
        if self._data is None:
            self._data = {}
            pattern = self.prefix + ".*"
            for path, domain in self.paths:
                for file_path in path.glob(pattern):
                    service = file_path.stem
                    short_name = file_path.suffixes[-2][1:]
                    self._data[short_name] = (domain, service, file_path)
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
    ):
        """Create a service on Linux.

        Linux supports three types of services. This function uses `user_agent` and
        `user_only` to control which is selected.

            1. A user service for a single user, which runs while that user is
               logged in. (True, True)

            2. A service installed by the admin that is available for all users,
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
        """
        identifier = self.prefix + "." + name

        if user_agent:
            if user_only:
                systemd_path = self.paths[0][0]
                systemd_path.mkdir(mode=0o755, parents=True, exist_ok=True)
                service_path = systemd_path / f"{identifier}.service"
            else:
                systemd_path = self.paths[1][0]
                service_path = systemd_path / f"{identifier}.service"
        else:
            systemd_path = self.paths[2][0]
            service_path = systemd_path / f"{identifier}.service"

        if service_path.exists():
            if not exist_ok:
                raise FileExistsError()

        description = name.replace("-", " ").title().replace("Seamm", "SEAMM")

        # Handle any arguments
        program_arguments = [str(x) for x in args]
        arguments = list_to_dict(program_arguments)

        if "--root" in arguments:
            root_path = Path(arguments["--root"]).expanduser()
        else:
            root_path = Path("~/SEAMM").expanduser()

        wd_path = root_path / "services"
        wd_path.mkdir(mode=0o755, parents=True, exist_ok=True)

        # Create the command with arguments
        cmd = exe_path
        if len(program_arguments) > 0:
            cmd += " "
            cmd += " ".join(program_arguments)

        # And the service file
        if user_agent:
            service = Template(user_text).substitute(
                description=description,
                wd=str(wd_path),
                exe=cmd,
            )
        else:
            # System-wide daemons need the username
            username = getpass.getuser()
            service = Template(user_text).substitute(
                description=description,
                user=username,
                wd=str(wd_path),
                exe=cmd,
            )

        # Reset the service data so it is re-read
        self._data = None

        # Write the file ... we may not have permission, so catch that.
        try:
            service_path.write_text(service)
        except PermissionError:
            downloads = Path("~/Downloads").expanduser()
            downloads.mkdir(exist_ok=True)
            path = downloads / f"{name}.service"
            path.write_text(service)
            print(f"\nYou do not have permission to write to {systemd_path}.")
            print("If you have administrator access, run the following commands:")
            print("")
            print(f"    sudo mv {path} {service_path}")
            print(f"    sudo chown root:root {service_path}")
            print("")
            print("To move the temporary copy of the file to the correct locations.")
        except Exception as e:
            print("Caught error?")
            print(e)
            print()
            raise

    def delete(self, service, ignore_errors=False):
        services = self.list()
        if service in services:
            domain, service_name, path = self.data[service]
            # Check if it is running
            if self.is_running(service):
                self.stop(service)
            # Now remove the files
            path.unlink(missing_ok=True)
            # Fix up service data
            del self.data[service]
        else:
            # Check if the service file exists, and remove if it does.
            for path, _ in self.paths:
                systemd_path = path / f"{self.prefix}.{service}.service"
                systemd_path.unlink(missing_ok=True)

    def file_path(self, service):
        "Return the path to the unit file for the service."
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
            domain, service_target, path = self.data[service]
            if "user" in domain:
                cmd = f"systemctl --user is-active {service_target}"
            else:
                cmd = f"systemctl is-active {service_target}"

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
                if "user" in domain:
                    cmd = f"systemctl --user --now enable {path}"
                else:
                    cmd = f"systemctl --now enable {path}"
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
            status["running"] = self.is_running(service)

            # Get the root directory and, for the dashboard, port
            path = self.data[service][2]
            logger.debug(f"Checking {path} for the root and port")
            config = ConfigParser()
            config.read(path)

            root = None
            port = None
            name = None
            if "Service" in config.sections() and "ExecStart" in config["Service"]:
                keywords = list_to_dict(shlex.split(config["Service"]["ExecStart"])[1:])
                root = keywords.get("--root")
                port = keywords.get("--port")
                if "--dashboard-name" in keywords:
                    name = keywords.get("--dashboard-name")
            status["root"] = root
            status["port"] = port
            status["dashboard name"] = name
        else:
            status["exists"] = False
        return status

    def stop(self, service, ignore_errors=False):
        services = self.list()
        if service in services:
            domain, service_target, path = self.data[service]
            # Check if it is running
            if self.is_running(service):
                if "user" in domain:
                    cmd = f"systemctl --user disable {service_target}"
                else:
                    cmd = f"systemctl disable {service_target}"
                result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
                if result.returncode == 0:
                    pass
                elif not ignore_errors:
                    raise RuntimeError(f"Could not stop the service '{service}':")
                if "user" in domain:
                    cmd = f"systemctl --user stop {service_target}"
                else:
                    cmd = f"systemctl stop {service_target}"
                result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
                if result.returncode == 0:
                    pass
                elif not ignore_errors:
                    raise RuntimeError(f"Could not stop the service '{service}':")
