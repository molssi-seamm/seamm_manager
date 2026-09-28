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
    code = (
        "import importlib.metadata as m\n"
        "files = [p for p in (m.files('seamm-datastore') or []) "
        "if 'alembic.ini' in str(p)]\n"
        "print(files[0].locate().parent if files else '')\n"
    )
    result = subprocess.run(
        [str(my.uv.python), "-c", code], capture_output=True, text=True
    )
    text = result.stdout.strip()
    if result.returncode != 0 or text == "":
        return None
    return Path(text)
