# -*- coding: utf-8 -*-

"""Handle the services (daemons) for SEAMM."""

import importlib.resources
from pathlib import Path
import platform
import plistlib

from tabulate import tabulate

from . import datastore
from . import my
from .naming import bundle_name, same_root, service_kind, service_name, tag

system = platform.system()
if system in ("Darwin",):
    from .mac import ServiceManager

    mgr = ServiceManager(prefix="org.molssi.seamm")
elif system in ("Linux",):
    from .linux import ServiceManager

    mgr = ServiceManager(prefix="org.molssi.seamm")
else:
    raise NotImplementedError(f"SEAMM does not support services on {system} yet.")

known_services = ["dashboard", "jobserver", "webui"]


def setup(parser):
    """Define the command-line interface for handling services.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The main parser for the application.
    """
    services_parser = parser.add_parser("services")
    subparser = services_parser.add_subparsers()

    # Create
    tmp_parser = subparser.add_parser("create")
    tmp_parser.set_defaults(func=create)
    tmp_parser.add_argument(
        "--force",
        action="store_true",
        help="Recreate the service if it already exists.",
    )
    tmp_parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=None,
        help=(
            "The port for the web interface (or dashboard). Default: the service's "
            "current port if it exists, else the first free port from 55055."
        ),
    )
    tmp_parser.add_argument(
        "--dashboard-name",
        default=None,
        help="The dashboard's name. Default: the host name, plus the installation.",
    )
    tmp_parser.add_argument(
        "--webui-host",
        default="0.0.0.0",
        help=(
            "Host for the webui service to bind to (default: %(default)s, "
            "i.e. reachable from other machines -- seamm_webui then "
            "requires per-user login and self-signed HTTPS automatically; "
            "use 127.0.0.1 for local-only, no-login access instead)."
        ),
    )
    tmp_parser.add_argument(
        "services",
        nargs="*",
        default=known_services,
        help="The services to create: %(default)s",
    )

    # Delete
    tmp_parser = subparser.add_parser("delete")
    tmp_parser.set_defaults(func=delete)
    tmp_parser.add_argument(
        "services",
        nargs="*",
        default=known_services,
        help="The services to delete: %(default)s",
    )

    # Start
    tmp_parser = subparser.add_parser("start")
    tmp_parser.set_defaults(func=start)
    tmp_parser.add_argument(
        "services",
        nargs="*",
        default=known_services,
        help="The services to start: %(default)s",
    )

    # Stop
    tmp_parser = subparser.add_parser("stop")
    tmp_parser.set_defaults(func=stop)
    tmp_parser.add_argument(
        "services",
        nargs="*",
        default=known_services,
        help="The services to stop: %(default)s",
    )

    # restart
    tmp_parser = subparser.add_parser("restart")
    tmp_parser.set_defaults(func=restart)
    tmp_parser.add_argument(
        "services",
        nargs="*",
        default=known_services,
        help="The services to restart: %(default)s",
    )

    # Show
    tmp_parser = subparser.add_parser("show")
    tmp_parser.set_defaults(func=show)
    tmp_parser.add_argument(
        "--all",
        action="store_true",
        help="List the services of every SEAMM installation on this machine.",
    )
    tmp_parser.add_argument(
        "services",
        nargs="*",
        default=known_services,
        help="The services to show: %(default)s",
    )

    # Status
    tmp_parser = subparser.add_parser("status")
    tmp_parser.set_defaults(func=status)
    tmp_parser.add_argument(
        "--all",
        action="store_true",
        help="List the services of every SEAMM installation on this machine.",
    )
    tmp_parser.add_argument(
        "services",
        nargs="*",
        default=known_services,
        help="The services to show: %(default)s",
    )


# The name each service's process gets on macOS (see mac.create_service_bundle)
bundle_names = {
    "dashboard": "SEAMM-Dashboard",
    "jobserver": "SEAMM-JobServer",
    "webui": "SEAMM-WebUI",
}


def _launch(service, exe_path):
    """How to launch a service: (program, leading arguments, environment).

    On macOS the program is the interpreter inside a per-service app bundle, so
    the process is named e.g. SEAMM-JobServer and has the SEAMM icon, rather
    than python3.12; it runs the service's script with the venv selected by
    ``__PYVENV_LAUNCHER__``. Elsewhere, or if the script is not in a venv with
    a ``python`` beside it, the script is run directly as before.
    """
    python = Path(exe_path).parent / "python"
    if system != "Darwin" or service not in bundle_names or not python.exists():
        return str(exe_path), [], None
    from .mac import create_service_bundle

    name = bundle_name(bundle_names[service])
    icons = importlib.resources.files("seamm_manager") / "data" / "SEAMM.icns"
    with importlib.resources.as_file(icons) as icons_path:
        program = create_service_bundle(my.root / "services", name, python, icons_path)
    return str(program), [str(exe_path)], {"__PYVENV_LAUNCHER__": str(python)}


def refresh_service_bundles():
    """Keep the macOS service bundles in step with their environments.

    Re-links a bundle's interpreter when its environment's Python has changed
    (effective at the service's next restart), and points out services still
    run directly as ``python3.12``. Returns the bundles re-linked.
    """
    if system != "Darwin":
        return []
    from .mac import refresh_service_bundle

    relinked = []
    for bundle in sorted((my.root / "services").glob("*.app")):
        if refresh_service_bundle(bundle):
            relinked.append(bundle.stem)
    if relinked:
        print(
            f"Updated the interpreter for {', '.join(relinked)}; it is used when the "
            "service next restarts."
        )

    old_style = []
    for service in bundle_names:
        entry = mgr.data.get(service_name(service))
        if entry is None:
            continue
        try:
            with open(entry[2], "rb") as fd:
                program = plistlib.load(fd)["ProgramArguments"][0]
        except Exception:
            continue
        if ".app/Contents/MacOS/" not in program:
            old_style.append(service)
    if old_style:
        print(
            "To show the services by name (e.g. SEAMM-JobServer rather than "
            "python3.12) with the SEAMM icon, recreate them when no jobs are "
            f"running: seamm-manager services create --force {' '.join(old_style)}"
        )
    return relinked


def _port_available(port):
    """Whether nothing is listening on the port on this machine."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def free_port(exclude=(), start=55055):
    """The first port from `start` that no other SEAMM service uses and is free."""
    used = set()
    for name in mgr.list():
        if name in exclude:
            continue
        try:
            used.add(int(mgr.status(name).get("port")))
        except (TypeError, ValueError):
            pass
    port = start
    while port in used or not _port_available(port):
        port += 1
    return port


def same_root_services(service):
    """Other SEAMM services of this kind started with this installation's root.

    Whatever their names -- the older ``dev_jobserver``, or one made by hand -- two
    services of one kind on one root would share a datastore, so creating a service
    replaces them.
    """
    this = service_name(service)
    result = []
    for name in mgr.list():
        if name == this or service_kind(name) != service:
            continue
        if same_root(mgr.status(name).get("root"), my.root):
            result.append(name)
    return result


def create_service(
    service, force=False, port=None, dashboard_name=None, webui_host="0.0.0.0"
):
    """Create and start one of this installation's services.

    Parameters
    ----------
    service : str
        "jobserver", "webui" or "dashboard".
    force : bool = False
        Recreate the service if it exists.
    port : int = None
        The web interface's or dashboard's port. Default: the service's current port,
        else that of a same-root service it replaces, else the first free port from
        55055.
    dashboard_name : str = None
        The dashboard's name. Default: the host name, plus the installation's tag.
    webui_host : str = "0.0.0.0"
        The address the web interface listens on.

    Returns
    -------
    bool
        Whether the service was created.
    """
    name = service_name(service)
    services = mgr.list()
    if name in services and not force:
        print(
            f"The service '{name}' already exists! Use --force to recreate the "
            "service from scratch."
        )
        return False

    # Find the program before changing anything.
    if service == "webui":
        # Lives in its own dedicated environment (venv-webui), not the main
        # one -- see install.py's install_seamm_webui().
        exe_path = my.uv.root / "venv-webui" / "bin" / "seamm-webui"
        if not exe_path.is_file():
            print(
                "Could not find seamm-webui in the venv-webui environment. "
                "Run 'seamm-manager install seamm-webui' first."
            )
            return False
        exe_path = str(exe_path)
    else:
        exe_path = my.uv.which(f"seamm-{service}") or my.uv.which(service)
        if exe_path is None:
            print(f"Could not find seamm-{service} or {service}. Is it installed?")
            return False

    # The port: keep this service's, or take over a replaced one's, or a free one.
    replaced = same_root_services(service)
    if service in ("webui", "dashboard") and port is None:
        for other in ([name] if name in services else []) + replaced:
            try:
                port = int(mgr.status(other).get("port"))
                break
            except (TypeError, ValueError):
                continue
        if port is None:
            port = free_port(exclude=[name, *replaced])

    if name in services:
        mgr.delete(name)
    for other in replaced:
        mgr.delete(other)
        print(f"Removed the service '{other}', which also ran this installation.")

    root = str(my.root)
    stderr_path = my.root / "logs" / f"{service}.out"
    stdout_path = my.root / "logs" / f"{service}.out"

    program, leading, environment = _launch(service, exe_path)
    extra = {} if environment is None else {"environment": environment}

    if service == "dashboard":
        if dashboard_name is None:
            host = platform.node() or "unknown"
            dashboard_name = host if tag() == "" else f"{host} ({tag()})"
        args = ["--root", root, "--port", port, "--dashboard-name", dashboard_name]
    elif service == "webui":
        args = ["--root", root, "--port", port, "--host", webui_host]
    else:
        args = ["--root", root, "JobServer", "--no-windows"]
    mgr.create(
        name,
        program,
        *leading,
        *args,
        stderr_path=str(stderr_path),
        stdout_path=str(stdout_path),
        **extra,
    )
    # The services need the datastore; create it if this is a fresh root.
    datastore.ensure()
    mgr.start(name)
    where = f" on port {port}" if service in ("webui", "dashboard") else ""
    print(f"Created and started the service {name}{where}")
    return True


def create():
    for service in my.options.services:
        create_service(
            service,
            force=my.options.force,
            port=my.options.port,
            dashboard_name=my.options.dashboard_name,
            webui_host=my.options.webui_host,
        )


def delete():
    for service in my.options.services:
        name = service_name(service)
        mgr.delete(name)
        print(f"The service {name} was deleted.")


def restart():
    for service in my.options.services:
        name = service_name(service)
        try:
            mgr.restart(name)
        except (RuntimeError, NotImplementedError) as e:
            print(e)
        else:
            print(f"The service '{name}' was restarted.")


def _names_to_list():
    """The service names to show: this installation's, or with --all every one."""
    if my.options.all:
        return sorted(mgr.list())
    return [service_name(service) for service in my.options.services]


def show():
    services = mgr.list()
    table = []
    for name in _names_to_list():
        if name in services:
            path = mgr.file_path(name)
            if path.is_relative_to(Path.home()):
                table.append((name, "~/" + str(path.relative_to(Path.home()))))
            else:
                table.append((name, str(path)))
        else:
            table.append((name, "not found"))
    if len(table) == 0:
        print("Found no services.")
    else:
        print(tabulate(table, ("Service", "Path"), tablefmt="fancy_grid"))


def start():
    for service in my.options.services:
        service = service_name(service)
        if mgr.is_running(service):
            print(f"The service '{service}' was already running.")
        else:
            try:
                mgr.start(service)
            except (RuntimeError, NotImplementedError) as e:
                print(e)
            else:
                print(f"The service '{service}' has been started.")


def status():
    services = mgr.list()
    table = []
    for name in _names_to_list():
        if name in services:
            status = mgr.status(name)
            row = [
                name,
                "running" if status["running"] else "not running",
                "---" if status["root"] is None else status["root"],
                "---" if status["port"] is None else status["port"],
                (
                    "---"
                    if status["dashboard name"] is None
                    else status["dashboard name"]
                ),
            ]
        else:
            row = [name, "not created"]
        table.append(row)
    print(
        tabulate(
            table,
            ("Service", "Status", "Root", "Port", "Name"),
            tablefmt="fancy_grid",
        )
    )


def stop():
    for service in my.options.services:
        name = service_name(service)
        if mgr.is_running(name):
            try:
                mgr.stop(name)
            except (RuntimeError, NotImplementedError) as e:
                print(e)
            else:
                print(f"The service '{name}' has been stopped.")
        else:
            print(f"The service '{name}' was not running.")
