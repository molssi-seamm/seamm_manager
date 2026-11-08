# -*- coding: utf-8 -*-

"""The codes' conda environments as archives (``code-environment-storage = archive``).

On a cluster whose shared file system creates files slowly (ARC's GPFS manages
1-30 files a second), a conda environment of ~30,000 files takes hours to create or
update in place, and as long to unpack there. The same environment builds in a few
minutes on a compute node's local disk. So an installation with archive storage:

#. builds each environment from the plug-in's environment file in ``$TMPDIR`` on a
   compute node (with the packages cached there too),
#. packs it with conda-pack into one file, ``<root>/env-archives/<name>-<stamp>.tar``,
   written as ``.part`` and renamed, with ``<name>-<stamp>.explicit.txt`` (the exact
   packages) and ``<name>-<stamp>.yml.sha256`` (the environment file it was built
   from) beside it,
#. points the link ``<name>.tar`` at it. Archives are never rewritten: a process
   reading a file that is replaced gets "Stale file handle" on GPFS, so a new
   version is a new file and the link is switched atomically.

Jobs use them through ``<root>/bin/seamm-conda``, a wrapper for conda that the job's
queue exports as ``CONDA_EXE``: ``conda run -n <name>`` then runs in a copy unpacked
on the job's node, once per job and node. The code's ``<code>.ini`` is unchanged
(``installation = conda``, ``conda-environment = <name>``).
"""

from datetime import datetime
import hashlib
import importlib.resources
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

logger = logging.getLogger(__name__)

ARCHIVE_DIR = "env-archives"
WRAPPER = "seamm-conda"
#: Keep this many versions of each archive (and any newer than MIN_AGE_DAYS):
#: jobs that started staging an older one may still be reading it.
KEEP = 3
MIN_AGE_DAYS = 1.0


class ArchiveError(RuntimeError):
    pass


def archive_dir(root):
    return Path(root).expanduser() / ARCHIVE_DIR


def current_archive(root, name):
    """The archive ``<name>.tar`` points at, or None if there is none."""
    link = archive_dir(root) / f"{name}.tar"
    if not (link.exists() or link.is_symlink()):
        return None
    target = link.resolve()
    return target if target.is_file() else None


def _stem(archive):
    return Path(archive).name[: -len(".tar")]


def archive_hash(root, name):
    """The hash of the environment file the current archive was built from."""
    archive = current_archive(root, name)
    if archive is None:
        return None
    path = archive.with_name(_stem(archive) + ".yml.sha256")
    try:
        return path.read_text().strip()
    except OSError:
        return None


def archive_age_days(root, name):
    archive = current_archive(root, name)
    if archive is None:
        return None
    return (time.time() - archive.stat().st_mtime) / 86400


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_directory():
    """Node-local scratch for a build: ``SEAMM_ARCHIVE_BUILD_DIR``, or ``$TMPDIR``
    inside a Slurm job.

    Building is real work and needs fast local disk, so it is refused outside a job
    (e.g. on a login node).
    """
    explicit = os.environ.get("SEAMM_ARCHIVE_BUILD_DIR", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
    tmpdir = os.environ.get("TMPDIR", "").strip()
    if os.environ.get("SLURM_JOB_ID") and tmpdir and Path(tmpdir).is_dir():
        return Path(tmpdir)
    raise ArchiveError(
        "This installation stores the codes' environments as archives "
        "(code-environment-storage = archive), which are built on a compute node's "
        "local disk: run seamm-manager inside a Slurm job, e.g.\n"
        "    sbatch -N1 -n1 -c4 --mem=16G -t 2:00:00 \\\n"
        "        --wrap 'seamm-manager update ...'\n"
        "or set SEAMM_ARCHIVE_BUILD_DIR to a fast local directory."
    )


def _stamp():
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def _run(args, env=None, what=""):
    logger.info(f"running {args}")
    p = subprocess.run(args, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise ArchiveError(
            f"{what or args[0]} failed ({p.returncode}):\n{p.stdout[-3000:]}"
            f"\n{p.stderr[-3000:]}"
        )
    return p.stdout


def pack(prefix, output, n_threads=None):
    """Pack the environment at `prefix` into the tar file `output` (conda-pack)."""
    import conda_pack

    conda_pack.pack(
        prefix=str(prefix),
        output=str(output),
        format="tar",
        n_threads=n_threads or min(os.cpu_count() or 1, 8),
        force=True,
        verbose=False,
    )


def publish(root, name, tarfile, explicit, env_hash, stamp=None):
    """Copy a built archive into ``<root>/env-archives`` and point ``<name>.tar`` at
    it. Returns the new archive's path."""
    directory = archive_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = stamp or _stamp()
    stem = f"{name}-{stamp}"
    archive = directory / f"{stem}.tar"
    if archive.exists():
        raise ArchiveError(f"{archive} already exists: archives are never rewritten.")
    part = directory / f"{stem}.tar.part"
    shutil.copyfile(tarfile, part)
    os.replace(part, archive)
    (directory / f"{stem}.explicit.txt").write_text(explicit)
    (directory / f"{stem}.yml.sha256").write_text(env_hash + "\n")
    for path in directory.glob(f"{stem}.*"):
        path.chmod(0o640)
    # Switch the link atomically: a new link, renamed over the old one
    link = directory / f"{name}.tar"
    tmp = directory / f".{name}.tar.{os.getpid()}"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(archive.name)
    os.replace(tmp, link)
    return archive


def build_conda_archive(conda_exe, environment_file, name, root, check=None):
    """Build the environment `name` from `environment_file` on local disk, pack it,
    publish it in ``<root>/env-archives``, and return the archive's path.

    Parameters
    ----------
    conda_exe : str
        The conda executable.
    environment_file : str or pathlib.Path
        The plug-in's environment file (seamm-<code>.yml).
    name : str
        The environment's name, as in the code's .ini file.
    root : str or pathlib.Path
        The installation's root.
    check : callable(prefix) or None
        Called with the built environment's prefix before it is packed, e.g. to
        check that the code runs; raise to stop.
    """
    conda_exe = real_conda(conda_exe)
    work = build_directory() / f"seamm-env-build-{name}-{os.getpid()}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        prefix = work / "envs" / name
        env = {**os.environ, "CONDA_PKGS_DIRS": str(work / "pkgs")}
        t0 = time.time()
        print(f"    Building the Conda environment '{name}' in {work} ...")
        _run(
            [
                str(conda_exe),
                "env",
                "create",
                "--quiet",
                "--file",
                str(environment_file),
                "--prefix",
                str(prefix),
            ],
            env=env,
            what=f"Creating the environment '{name}'",
        )
        if check is not None:
            check(prefix)
        explicit = _run(
            [str(conda_exe), "list", "--prefix", str(prefix), "--explicit", "--md5"],
            env=env,
            what="Listing the environment's packages",
        )
        t1 = time.time()
        tarfile = work / f"{name}.tar"
        pack(prefix, tarfile)
        t2 = time.time()
        archive = publish(root, name, tarfile, explicit, file_hash(environment_file))
        t3 = time.time()
        print(
            f"    Built in {t1 - t0:.0f} s, packed in {t2 - t1:.0f} s, published "
            f"{archive} ({archive.stat().st_size / 2**30:.1f} GiB) in {t3 - t2:.0f} s."
        )
        return archive
    finally:
        shutil.rmtree(work, ignore_errors=True)


def real_conda(conda_exe):
    """The real conda behind `conda_exe`, which may be this wrapper (CONDA_EXE is
    the wrapper inside a job whose queue uses the archives)."""
    if conda_exe is None or Path(conda_exe).name != WRAPPER:
        return conda_exe
    value = os.environ.get("SEAMM_REAL_CONDA", "").strip()
    if value:
        return value
    try:
        match = re.search(
            r"^REAL=\$\{SEAMM_REAL_CONDA:-(.+)\}$", Path(conda_exe).read_text(), re.M
        )
    except OSError:
        match = None
    if match is None:
        raise ArchiveError(f"Cannot find the real conda behind {conda_exe}.")
    return match.group(1)


def install_wrapper(root, conda_exe):
    """Install ``<root>/bin/seamm-conda`` for this conda and archive directory.

    Returns True if it was written (new or changed).
    """
    template = (
        importlib.resources.files("seamm_manager") / "data" / "archive" / WRAPPER
    ).read_text()
    text = template.replace("@REAL_CONDA@", str(real_conda(conda_exe))).replace(
        "@ARCHIVES@", str(archive_dir(root))
    )
    path = Path(root).expanduser() / "bin" / WRAPPER
    if path.exists() and path.read_text() == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{WRAPPER}.{os.getpid()}")
    tmp.write_text(text)
    tmp.chmod(0o750)
    os.replace(tmp, path)
    return True


def queue_setup_line(root):
    """The line a queue's setup needs for its jobs to use the archives."""
    return f"export CONDA_EXE={Path(root).expanduser() / 'bin' / WRAPPER}"


def prune(root, name, keep=KEEP, min_age_days=MIN_AGE_DAYS, dry_run=False):
    """Remove old versions of the archive `name`, keeping the current one, the
    newest `keep`, and any younger than `min_age_days`. Returns the removed paths."""
    directory = archive_dir(root)
    current = current_archive(root, name)
    # Only <name>-<stamp>.tar: seamm-lammps must not match seamm-lammps-xnn0240-...
    pattern = re.compile(
        re.escape(name) + r"-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.tar$"
    )
    versions = sorted(
        (p for p in directory.iterdir() if pattern.match(p.name) and p.is_file()),
        key=lambda p: p.name,
        reverse=True,
    )
    removed = []
    now = time.time()
    for archive in versions[keep:]:
        if current is not None and archive.resolve() == current:
            continue
        if (now - archive.stat().st_mtime) / 86400 < min_age_days:
            continue
        stem = _stem(archive)
        for path in directory.glob(f"{stem}.*"):
            removed.append(path)
            if not dry_run:
                path.unlink()
    return removed
