# -*- coding: utf-8 -*-

"""Upgrade an installation's flowcharts to format 3.0.

The flowchart of each job (``flowchart.flow`` in its directory) and the datastore's
record of it are converted from format 2.0 to 3.0 by ``seamm-flowchart migrate``, in the
installation's environment. This module wraps it in one step for users: a dry run and
its summary, a confirmation, then -- with the services stopped -- the migration itself,
which backs up the datastore and writes a manifest to undo the file changes.
"""

import json
from pathlib import Path
import subprocess

from . import my
from .naming import service_name as installation_service_name

# The keys of the plan's summary that mean there is something to do
_WORK = (
    "job flowcharts to convert",
    "flowcharts in job directories not in the datastore, to convert",
    "rows updated in place",
    "rows created (splits)",
    "rows deleted (merged, or unused)",
    "jobs pointed at another row",
)

_PLAN_CODE = """\
import json
from seamm import migrate3
plan = migrate3.plan(r'{root}')
print(migrate3.text_report(plan))
print('SUMMARY ' + json.dumps(plan['summary']))
"""


def setup(parser):
    """Define the command-line interface for the flowcharts.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The main parser for the application.
    """
    flowcharts_parser = parser.add_parser(
        "flowcharts", help="The installation's job flowcharts"
    )
    subparser = flowcharts_parser.add_subparsers()

    tmp_parser = subparser.add_parser(
        "migrate",
        help="Convert the job flowcharts and the datastore to flowchart format 3.0",
    )
    tmp_parser.add_argument(
        "--yes",
        action="store_true",
        help="Do not ask for confirmation before converting",
    )
    tmp_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be converted",
    )
    tmp_parser.set_defaults(func=migrate)

    tmp_parser = subparser.add_parser(
        "status", help="Whether any job flowcharts are still in format 2.0"
    )
    tmp_parser.set_defaults(func=status)


def _python():
    """The installation's Python, if SEAMM is installed there with the migration."""
    if not my.uv.exists or my.uv.which("python") is None:
        print(f"There is no SEAMM environment in {my.root}")
        return None
    result = subprocess.run(
        [str(my.uv.python), "-c", "import seamm.migrate3"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            "The SEAMM installed here cannot convert flowcharts yet. Update it first "
            "with 'seamm-manager update --all'."
        )
        return None
    return my.uv.python


def old_job_flowcharts(root=None, stop_at=None):
    """The number of job directories whose flowchart is in format 2.0 (or 1.0).

    Parameters
    ----------
    root : pathlib.Path, optional
        The installation's root; by default the current one.
    stop_at : int, optional
        Stop counting once this many are found.
    """
    root = Path(my.root if root is None else root)
    count = 0
    for path in (root / "Jobs" / "projects").glob("*/*/flowchart.flow"):
        try:
            with path.open() as fd:
                fd.readline()
                second = fd.readline()
        except OSError:
            continue
        if second.startswith("!MolSSI flowchart"):
            count += 1
            if stop_at is not None and count >= stop_at:
                break
    return count


def status():
    """Report whether any job flowcharts are still in format 2.0 (a full scan,
    which also refreshes the record ``update`` relies on)."""
    n = old_job_flowcharts()
    if n == 0:
        record_migration()
        print(f"All the job flowcharts in {my.root} are in format 3.0.")
    else:
        record_migration(done=False)
        print(
            f"{n} job flowcharts in {my.root} are in the old format 2.0. Convert them "
            "with 'seamm-manager flowcharts migrate'."
        )


MIGRATED_SECTION = "flowcharts"
MIGRATED_KEY = "format"


def migration_recorded(root=None):
    """Whether ``<root>/installation.ini`` records that every job flowchart is
    in format 3.0, so the scan of the job directories can be skipped. The scan
    reads one line of every job's flowchart, which on a cluster's network file
    system with tens of thousands of jobs takes many minutes; once no old
    flowchart remains none can appear (seamm 3.0 writes only 3.0), so the
    result is recorded and the scan not repeated. ``flowcharts status`` always
    scans, and refreshes the record."""
    import configparser

    from .policy import POLICY_FILE

    path = Path(my.root if root is None else root) / POLICY_FILE
    if not path.exists():
        return False
    config = configparser.ConfigParser(interpolation=None)
    config.read(path)
    return config.get(MIGRATED_SECTION, MIGRATED_KEY, fallback="").strip() == "3.0"


def record_migration(root=None, done=True):
    """Record in ``<root>/installation.ini`` that the job flowcharts are all in
    format 3.0 (``done``), or remove the record."""
    import configparser
    from datetime import date

    from .policy import POLICY_FILE

    path = Path(my.root if root is None else root) / POLICY_FILE
    config = configparser.ConfigParser(interpolation=None)
    if path.exists():
        config.read(path)
    if not config.has_section(MIGRATED_SECTION):
        config.add_section(MIGRATED_SECTION)
    if done:
        config.set(MIGRATED_SECTION, MIGRATED_KEY, "3.0")
        config.set(MIGRATED_SECTION, "checked", date.today().isoformat())
    else:
        config.remove_section(MIGRATED_SECTION)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fd:
        config.write(fd)


def notice():
    """A one-line notice for 'seamm-manager update' and 'install' if old
    flowcharts remain.

    Skipped once :func:`migration_recorded`; when a scan finds nothing old, that
    is recorded so the next update does not scan again."""
    try:
        if migration_recorded():
            return
        if old_job_flowcharts(stop_at=1) == 0:
            record_migration()
            return
        result = subprocess.run(
            [str(my.uv.python), "-c", "import seamm.migrate3"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return
    except Exception:
        return
    print(
        "\nThis installation has job flowcharts in the old format 2.0. To convert them "
        "and the datastore to 3.0 (with a backup):\n"
        "    seamm-manager flowcharts migrate"
    )


def _plan(python):
    """The dry run's report and summary."""
    result = subprocess.run(
        [str(python), "-c", _PLAN_CODE.format(root=my.root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("Could not work out the migration:")
        print("\n".join("    " + x for x in result.stderr.splitlines()[-10:]))
        return None, None
    report = []
    summary = {}
    for line in result.stdout.splitlines():
        if line.startswith("SUMMARY "):
            summary = json.loads(line[len("SUMMARY ") :])  # noqa: E203
        else:
            report.append(line)
    return "\n".join(report), summary


def migrate():
    """Convert the installation's job flowcharts and datastore to format 3.0."""
    from .services import mgr

    python = _python()
    if python is None:
        return 1

    print(f"Working out what to convert in {my.root} (nothing is changed yet)...\n")
    report, summary = _plan(python)
    if report is None:
        return 1
    print(report)
    if sum(summary.get(key, 0) for key in _WORK) == 0:
        print("Nothing to convert: the flowcharts are already in format 3.0.")
        record_migration()
        return 0
    if getattr(my.options, "dry_run", False):
        print("Dry run: nothing was changed.")
        return 0
    if not getattr(my.options, "yes", False):
        answer = input(
            "Convert these flowcharts and the datastore to format 3.0? The datastore "
            "is backed up first. [y/N] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing was changed.")
            return 0

    services = [
        installation_service_name(s) for s in ("jobserver", "webui", "dashboard")
    ]
    stopped = [s for s in services if mgr.is_running(s)]
    for service in stopped:
        print(f"Stopping the service {service}")
        mgr.stop(service)
    try:
        seamm_flowchart = my.uv.which("seamm-flowchart")
        command = [str(seamm_flowchart), "migrate", "--root", str(my.root), "--apply"]
        result = subprocess.run(command, capture_output=True, text=True)
        lines = result.stdout.splitlines()
        if result.returncode != 0:
            print("The migration failed:")
            print("\n".join("    " + x for x in result.stderr.splitlines()[-10:]))
            return 1
        for line in lines:
            if line.startswith(("Datastore backup:", "Manifest of file changes:")):
                print(line)
        print("The flowcharts and the datastore are now in format 3.0.")
    finally:
        for service in stopped:
            print(f"Starting the service {service}")
            mgr.start(service)
    return 0
