# -*- coding: utf-8 -*-

"""Handle the datastore for SEAMM."""

from pathlib import Path
import platform
import re
import sqlite3
import subprocess

from . import my
from .naming import service_name as installation_service_name

system = platform.system()
if system in ("Darwin",):
    from .mac import ServiceManager

    mgr = ServiceManager(prefix="org.molssi.seamm")
elif system in ("Linux",):
    from .linux import ServiceManager

    mgr = ServiceManager(prefix="org.molssi.seamm")
else:
    raise NotImplementedError(f"SEAMM does not support services on {system} yet.")


def setup(parser):
    """Define the command-line interface for handling services.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The main parser for the application.
    """
    services_parser = parser.add_parser("datastore")
    subparser = services_parser.add_subparsers()

    # Show
    tmp_parser = subparser.add_parser("show")
    tmp_parser.set_defaults(func=show)

    # Update
    tmp_parser = subparser.add_parser("update")
    tmp_parser.set_defaults(func=update)

    # Rebuild
    tmp_parser = subparser.add_parser(
        "rebuild",
        help="Rebuild the datastore from the job directories, keeping the accounts",
    )
    tmp_parser.set_defaults(func=rebuild)


def _alembic():
    """The environment's alembic executable, or None.

    The manager may run from a different interpreter (the uv tool
    environment), which has no alembic; the datastore's is in the venv.
    """
    return my.uv.which("alembic") if my.uv is not None else None


def latest_version():
    """Show information about the datastore."""
    path = _find_path()
    alembic = _alembic()
    version = None
    if path is not None and alembic is not None:
        cmd = f'"{alembic}" heads'
        result = subprocess.run(
            cmd, cwd=path, shell=True, text=True, capture_output=True
        )
        if result.returncode == 0:
            version = result.stdout.strip()
        else:
            my.logger.warning(f"Running '{cmd}' was not successful:")
            my.logger.warning(result.stderr)
    return version


def db_version():
    """Return the version of the database."""
    db_path = my.root / "Jobs" / "seamm.db"
    if not db_path.expanduser().exists():
        version = "not installed"
    else:
        path = _find_path()
        alembic = _alembic()
        version = "unknown"
        if path is not None and alembic is not None:
            uri = f"sqlite:///{str(db_path.expanduser())}"
            cmd = f'"{alembic}" -x uri="{uri}" current'
            result = subprocess.run(
                cmd, cwd=path, shell=True, text=True, capture_output=True
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                if version == "":
                    version = "--none--"
            else:
                my.logger.warning(f"Running '{cmd}' was not successful:")
                my.logger.warning(result.stderr)
    return version


def ensure(default_project="default"):
    """Create the datastore if it does not exist, using the environment's own
    seamm_datastore, so that the JobServer and the web interface can start in
    any order. Returns True if it was created.

    The first version of the manager left this to the web interface's first
    start; a JobServer created before it crash-looped on the missing database.
    """
    db_path = my.root / "Jobs" / "seamm.db"
    if db_path.exists():
        state = _seed_state(db_path)
        if state == "seeded":
            return False
        if state == "no tables":
            # A file with none of SEAMM's tables holds no data: e.g. a JobServer
            # started before seamm-datastore was installed creates an empty
            # seamm.db. Replace it with a proper one.
            print(f"The datastore {db_path} is empty; creating it afresh.")
            for suffix in ("", "-wal", "-shm"):
                Path(str(db_path) + suffix).unlink(missing_ok=True)
        else:  # the tables exist but there are no users: seed them below
            print(f"The datastore {db_path} has no users; adding the defaults.")
    if not my.uv.exists or my.uv.which("python") is None:
        return False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    projects = db_path.parent / "projects"
    if not db_path.exists() and any(projects.glob("*/*/job_data.json")):
        # There are jobs already: build the datastore from them
        print(f"Creating the datastore {db_path} from the jobs in {projects}")
        code = (
            "import seamm_datastore\n"
            f"print(seamm_datastore.build_from_jobs(r'{db_path}', r'{projects}', "
            f"default_project='{default_project}'))\n"
        )
    else:
        if not db_path.exists():
            print(f"Creating the datastore {db_path}")
        code = (
            "import seamm_datastore\n"
            f"seamm_datastore.connect(database_uri='sqlite:///{db_path}', "
            f"datastore_location='{db_path.parent}', initialize=True, "
            f"default_project='{default_project}')\n"
        )
    result = subprocess.run(
        [str(my.uv.python), "-c", code], capture_output=True, text=True
    )
    if result.returncode != 0:
        print("   ...could not create the datastore:")
        print("\n".join("      " + line for line in result.stderr.splitlines()[-6:]))
        return False
    print("   done; the administrator account is 'admin' (password 'admin').")
    # seamm_datastore creates the tables without recording their revision; record
    # it so later updates migrate from the right place.
    revision = unversioned_revision(db_path)
    if revision is not None:
        try:
            stamp(revision)
        except Exception as e:
            print(f"   (could not record the database's version: {e})")
    return True


def _seed_state(db_path):
    """How far an existing datastore file is set up.

    Returns "no tables" (none of SEAMM's tables), "no users" (the tables but no
    user accounts), or "seeded".
    """
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            tables = {r[0] for r in db.execute("select name from sqlite_master")}
            if "users" not in tables:
                return "no tables"
            if db.execute("select count(*) from users").fetchone()[0] == 0:
                return "no users"
    except sqlite3.Error:
        return "seeded"  # not ours to judge; leave it alone
    return "seeded"


# Revisions of seamm_datastore's migrations whose schema can be recognized in a
# database that was never put under alembic (it has no alembic_version table).
# Older databases have a ``path`` column in ``flowcharts``; the first migration,
# 7b24598d1fee, removes it and adds ``flowchart_metadata``; d7d6859198e9 adds a
# unique constraint on ``sha256_strict``.
_BASE_REVISION = "7b24598d1fee"
_HASH_REVISION = "d7d6859198e9"


def unversioned_revision(db_path):
    """The revision an unversioned database's tables already match, or None.

    None when the database is versioned, has no jobs table, or predates the
    first migration (which alembic can then apply from scratch).
    """
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            tables = {r[0] for r in db.execute("select name from sqlite_master")}
            if "alembic_version" in tables or "flowcharts" not in tables:
                return None
            columns = {r[1] for r in db.execute("pragma table_info(flowcharts)")}
            if "path" in columns or "flowchart_metadata" not in columns:
                return None
            sql = " ".join(
                r[0] or ""
                for r in db.execute(
                    "select sql from sqlite_master where tbl_name = 'flowcharts'"
                )
            )
            unique_index = any(
                idx[2]
                and [c[2] for c in db.execute(f"pragma index_info('{idx[1]}')")]
                == ["sha256_strict"]
                for idx in db.execute("pragma index_list(flowcharts)")
            )
    except sqlite3.Error:
        return None
    unique = (
        unique_index
        or "uq_flowcharts_sha256_strict" in sql
        or re.search(r"unique\s*\(\s*sha256_strict\s*\)", sql, re.IGNORECASE)
    )
    return _HASH_REVISION if unique else _BASE_REVISION


def stamp(revision):
    """Record in the database that its tables are at `revision`, without changes."""
    db_path = my.root / "Jobs" / "seamm.db"
    path = _find_path()
    alembic = _alembic()
    if path is None or alembic is None:
        raise RuntimeError("seamm-datastore (and its alembic) is not installed.")
    uri = f"sqlite:///{db_path}"
    cmd = f'"{alembic}" -x uri="{uri}" stamp {revision}'
    result = subprocess.run(cmd, cwd=path, shell=True, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"Running '{cmd}' was not successful:\n\n{result.stderr}")


def update():
    """Update the database to the latest version."""
    db_path = my.root / "Jobs" / "seamm.db"
    if not db_path.expanduser().exists() or _seed_state(db_path) != "seeded":
        # Missing, or an empty file / tables without users: migrations would not
        # create SEAMM's tables, only mark the file as migrated. Create it properly.
        if not ensure():
            print(f"The database file '{db_path}' could not be created.")
    else:
        version = db_version()
        latest = latest_version()
        if version == latest:
            print(f"The database at '{db_path}' is already up-to-date.")
        else:
            service_name = installation_service_name("jobserver")
            restart = mgr.is_running(service_name)
            if restart:
                print(f"Stopping the service {service_name}")
                mgr.stop(service_name)

            # A database that was never put under alembic would otherwise be
            # migrated from the first revision and fail; record the revision its
            # tables already have first.
            revision = unversioned_revision(db_path)
            if revision is not None:
                print(
                    f"The database has no version recorded; its tables match "
                    f"revision {revision}, so recording that first."
                )
                stamp(revision)

            print("Updating the database.")
            update_db()

            if restart:
                print(f"Restarting the service {service_name}")
                mgr.start(service_name)

            version = db_version()
            if version == latest:
                print(
                    f"The database at '{db_path}' has been updated to version {version}"
                )
            else:
                raise RuntimeError(
                    f"The database at '{db_path}' was updated to version {version},\n"
                    f"but it should be {latest}. Something went wrong!"
                )


def rebuild():
    """Rebuild the datastore from the job directories.

    The job directories hold each job's flowchart and job_data.json, which is what
    the datastore records. A new datastore is built from them, keeping the accounts
    (users, groups, roles), the details of projects that still exist, and the owner
    of each job from the current datastore, which is kept as a dated backup. Jobs
    whose directories are gone are not in the new datastore.
    """
    import datetime

    db_path = my.root / "Jobs" / "seamm.db"
    projects = db_path.parent / "projects"
    if not my.uv.exists or my.uv.which("python") is None:
        print(f"There is no SEAMM environment in {my.root}")
        return
    n_dirs = len(list(projects.glob("*/*/job_data.json")))
    print(f"Rebuilding the datastore {db_path} from {n_dirs} job directories")

    when = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    new = db_path.with_name(f"seamm.db.rebuilding-{when}")
    keep = db_path if db_path.exists() else None

    services = [installation_service_name(s) for s in ("jobserver", "webui")]
    stopped = [s for s in services if mgr.is_running(s)]
    for service in stopped:
        print(f"Stopping the service {service}")
        mgr.stop(service)
    try:
        code = (
            "import seamm_datastore\n"
            f"result = seamm_datastore.build_from_jobs(r'{new}', r'{projects}', "
            f"keep_from={repr(str(keep)) if keep else None})\n"
            "print('RESULT', result['projects'], result['jobs'])\n"
        )
        result = subprocess.run(
            [str(my.uv.python), "-c", code], capture_output=True, text=True
        )
        skipped = [
            line
            for line in result.stdout.splitlines() + result.stderr.splitlines()
            if "not imported:" in line or "Could not read the job data" in line
        ]
        counts = [
            line.split()[1:]
            for line in result.stdout.splitlines()
            if line.startswith("RESULT")
        ]
        if result.returncode != 0 or not counts:
            print("   ...the rebuild failed; the datastore is unchanged:")
            print("\n".join("      " + x for x in result.stderr.splitlines()[-8:]))
            for suffix in ("", "-wal", "-shm"):
                Path(str(new) + suffix).unlink(missing_ok=True)
            return
        n_projects, n_jobs = counts[0]
        if keep is not None:
            backup = db_path.with_name(f"seamm.db.bak-{when}-before-rebuild")
            for suffix in ("", "-wal", "-shm"):
                old = Path(str(db_path) + suffix)
                if old.exists():
                    old.rename(str(backup) + suffix)
            print(f"   The previous datastore is kept as {backup}")
        new.rename(db_path)
        print(f"   Imported {n_jobs} jobs in {n_projects} projects.")
        if skipped:
            print(f"   {len(skipped)} job directories were not imported:")
            print("\n".join("      " + x for x in skipped[:20]))
        revision = unversioned_revision(db_path)
        if revision is not None:
            try:
                stamp(revision)
            except Exception as e:
                print(f"   (could not record the database's version: {e})")
    finally:
        for service in stopped:
            print(f"Starting the service {service}")
            mgr.start(service)


def update_db():
    """Update the database to the latest version."""
    db_path = my.root / "Jobs" / "seamm.db"
    if not db_path.expanduser().exists():
        raise RuntimeError(f"The database '{db_path}' does not exist.")

    path = _find_path()
    if path is None:
        raise RuntimeError(
            "Cannot find the path to the installed version of seamm-datastore.\n"
            "Is it installed?"
        )
    uri = f"sqlite:///{str(db_path.expanduser())}"
    alembic = _alembic()
    if alembic is None:
        raise RuntimeError(
            f"Cannot find 'alembic' in the SEAMM environment {my.uv.path}.\n"
            "Is seamm-datastore installed?"
        )
    cmd = f'"{alembic}" -x uri="{uri}" upgrade head'
    result = subprocess.run(cmd, cwd=path, shell=True, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"Running '{cmd}' was not successful:\n\n{result.stderr}")


def show():
    """Show information about the datastore."""
    db_path = my.root / "Jobs" / "seamm.db"
    latest = latest_version()
    if not db_path.expanduser().exists():
        print(f"The database file '{db_path}' does not exist.")
    else:
        version = db_version()
        if version == latest:
            print(f"The database at '{db_path}' (version {version}) is up-to-date.")
        else:
            print(
                f"The database at '{db_path}' (version {version}) should be upgraded "
                f"to {latest} by running"
                "\n\n"
                "          seamm-manager datastore update"
            )


def _find_path():
    """Return the path for alembic in the datastore installation.

    Asks the SEAMM environment's own interpreter, since the manager may be
    running from a different one.

    Returns
    -------
    pathlib.Path
        The path to the alembic installation, or None if not present.
    """
    # The installed files list alembic.ini, except for an editable install (e.g. a
    # development checkout), whose files are its source directory.
    code = (
        "import importlib.metadata as m\n"
        "files = [p for p in (m.files('seamm-datastore') or []) "
        "if 'alembic.ini' in str(p)]\n"
        "if files:\n"
        "    print(files[0].locate().parent)\n"
        "else:\n"
        "    import pathlib, seamm_datastore\n"
        "    ini = pathlib.Path(seamm_datastore.__file__).parent / 'database' / "
        "'alembic.ini'\n"
        "    print(ini.parent if ini.exists() else '')\n"
    )
    result = subprocess.run(
        [str(my.uv.python), "-c", code], capture_output=True, text=True
    )
    text = result.stdout.strip()
    if result.returncode != 0 or text == "":
        return None
    return Path(text)
