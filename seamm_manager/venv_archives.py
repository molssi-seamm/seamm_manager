# -*- coding: utf-8 -*-

"""The SEAMM environment as an archive (``seamm-environment-storage = archive``).

On a cluster whose shared file system creates files slowly (ARC's GPFS manages a few
files a second at busy times), building a new version of the SEAMM environment
(~46,000 files) beside the current one takes hours, although the same build takes a
minute on a compute node's local disk. So an installation with archive storage
changes its environment like this, inside a Slurm job:

#. The current version is unpacked from its archive onto local disk (seconds), and
   the new version is built there from it, exactly as `versions.build_version` does
   beside the current one: a relocatable environment, with uv's cache on local disk.
#. The new version is checked (`versions.regressions`), compiled, and packed into
   ``<root>/env-archives/seamm-venv-<stamp>.tar``; the link ``seamm-venv.tar`` is
   switched to it (`archives.publish`; archives are never rewritten). From then on
   jobs whose queue's setup sources ``<root>/bin/stage_seamm_venv.sh`` unpack it on
   their own nodes and run from that copy.
#. The archive is unpacked into ``<root>/venvs/<stamp>`` with several tar streams at
   once (the shared file system's latency per file, not its bandwidth, is the limit)
   and the ``venv`` link switched, for everything that does not stage: the login
   nodes, queues whose tasks run as separate jobs, the plug-ins' installers.

The archive is what jobs run, and the directory is unpacked from the same file, so
the two are identical. ``<stamp>`` is the version's name in both places, which lets
``environment switch`` and ``rollback`` move the archive's link with the directory's.
"""

from datetime import datetime, timedelta
import hashlib
import importlib.resources
import logging
import os
from pathlib import Path
import shutil
import subprocess
import time

from . import archives
from . import my
from .uv import Uv

logger = logging.getLogger(__name__)

#: The archive's name in <root>/env-archives: seamm-venv-<stamp>.tar, seamm-venv.tar
NAME = "seamm-venv"
#: The top directory inside the archive (jobs unpack with --strip-components=1)
TOP = "venv"
#: The scripts installed in <root>/bin for the queues
STAGE_SCRIPT = "stage_seamm_venv.sh"
LAUNCHERS = ("run_from_jobserver", "run_flowchart")
#: Tar streams unpacking into the shared file system at once. On ARC GPFS (11-08)
#: 1 stream wrote 42 files/s, 16 wrote 323 and 32 wrote 559: the venv in 83 s.
STREAMS = int(os.environ.get("SEAMM_UNPACK_STREAMS", "32"))


def _root():
    """The installation's root (the environment's, if the root is not set)."""
    return getattr(my, "root", None) or getattr(my.uv, "root", None)


def enabled():
    """Whether this installation stores its SEAMM environment as archives."""
    from .policy import seamm_environment_storage

    root = _root()
    if os.name == "nt" or root is None:
        return False
    return seamm_environment_storage(root) == "archive"


def archive_for(name):
    """The archive of the version `name`, or None."""
    path = archives.archive_dir(_root()) / f"{NAME}-{name}.tar"
    return path if path.is_file() else None


def current_archive():
    """The archive jobs stage now (``seamm-venv.tar`` points at it), or None."""
    return archives.current_archive(_root(), NAME)


def version_of(archive):
    """The version name of an archive ``seamm-venv-<stamp>.tar``."""
    return Path(archive).name[len(NAME) + 1 : -len(".tar")]


def follow(name):
    """Point ``seamm-venv.tar`` at the archive of version `name`, if there is one.

    Returns True if the link now points there.
    """
    archive = archive_for(name)
    if archive is None:
        print(
            f"There is no archive of {name}, so jobs keep staging "
            f"{_describe(current_archive())}. Build one with "
            "'seamm-manager environment archive' (in a Slurm job)."
        )
        return False
    archives.point_link(archives.archive_dir(_root()), NAME, archive.name)
    return True


def _describe(archive):
    if archive is None:
        return "nothing (they use the shared environment)"
    return archive.name


# ---- the scripts the queues use ---------------------------------------------------


def install_job_scripts(root=None):
    """Install ``<root>/bin/stage_seamm_venv.sh`` and the launchers that use the
    staged copy. Returns the paths written (new or changed)."""
    root = Path(root or _root()).expanduser()
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    data = importlib.resources.files("seamm_manager") / "data" / "archive"
    written = []
    for name, mode in [(STAGE_SCRIPT, 0o640)] + [(n, 0o750) for n in LAUNCHERS]:
        text = (data / name).read_text().replace("@ROOT@", str(root))
        path = bin_dir / name
        if path.exists() and path.read_text() == text:
            continue
        tmp = bin_dir / f".{name}.{os.getpid()}"
        tmp.write_text(text)
        tmp.chmod(mode)
        os.replace(tmp, path)
        written.append(path)
    return written


def queue_settings(root=None):
    """The lines a queue section needs for its jobs to stage the environment."""
    root = Path(root or _root()).expanduser()
    return (
        f"setup = source {root / 'bin' / STAGE_SCRIPT}\n"
        f"remote_run_from_jobserver = {root / 'bin' / 'run_from_jobserver'}"
    )


# ---- building ---------------------------------------------------------------------


class _LocalCache:
    """uv's cache on the build's local disk while building (fast, and leaves the
    shared cache alone)."""

    def __init__(self, path):
        self.path = path
        self.saved = None

    def __enter__(self):
        self.saved = os.environ.get("UV_CACHE_DIR")
        os.environ["UV_CACHE_DIR"] = str(self.path)
        return self

    def __exit__(self, *args):
        if self.saved is None:
            os.environ.pop("UV_CACHE_DIR", None)
        else:
            os.environ["UV_CACHE_DIR"] = self.saved


def _run(args, what):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if p.returncode != 0:
        raise archives.ArchiveError(
            f"{what} failed ({p.returncode}):\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}"
        )
    return p.stdout


def stage_current(work):
    """The current version as a ``Uv``: unpacked from its archive into `work`, or
    the installation's own environment if there is no archive yet."""
    archive = current_archive()
    if archive is None:
        return my.uv
    path = Path(work) / "current"
    path.mkdir(parents=True)
    t0 = time.time()
    _run(
        ["tar", "-C", path, "--strip-components=1", "-xf", archive],
        f"Unpacking {archive.name}",
    )
    print(
        f"   unpacked the current version, {archive.name}, in {time.time() - t0:.0f} s"
    )
    return Uv(work, name="current", python_version=my.uv.python_version)


def new_version_name():
    """A version name not taken by a directory or an archive."""
    from .versions import _free_version_name

    moment = datetime.now()
    while True:
        name = _free_version_name(my.uv, moment)
        if archive_for(name) is None:
            return name
        moment = datetime.strptime(name, "%Y-%m-%dT%H-%M-%S") + timedelta(seconds=1)


def _check(new):
    """Compile the new environment and check that SEAMM imports from it."""
    jobs = os.environ.get("SLURM_CPUS_PER_TASK") or str(min(os.cpu_count() or 1, 8))
    site = next((new.real_path / "lib").glob("python*/site-packages"), None)
    if site is not None:
        # Byte-compile once here rather than in every job (warnings only)
        subprocess.run(
            [str(new.python), "-m", "compileall", "-q", "-j", jobs, str(site)],
            capture_output=True,
        )
    if "seamm" in new.list():
        _run([new.python, "-c", "import seamm"], "Importing seamm from the new version")


def pack(new, work):
    """Pack the environment `new` (in ``<work>/venv``) into one tar file."""
    tarfile = Path(work) / f"{NAME}.tar"
    _run(["tar", "-C", new.real_path.parent, "-cf", tarfile, new.real_path.name], "tar")
    return tarfile


def publish(new, work, name):
    """Check, pack and publish `new` as version `name`. Returns the archive's path."""
    _check(new)
    freeze = new.freeze()
    t0 = time.time()
    tarfile = pack(new, work)
    archive = archives.publish(
        _root(),
        NAME,
        tarfile,
        freeze,
        hashlib.sha256(freeze.encode()).hexdigest(),
        stamp=name,
    )
    print(
        f"Published {archive} ({archive.stat().st_size / 2**30:.1f} GiB) in "
        f"{time.time() - t0:.0f} s; jobs that stage the environment use it from now on."
    )
    return archive


# ---- unpacking into the shared file system ---------------------------------------


def unpack(tarfile, target, streams=None):
    """Unpack the archive `tarfile` into the directory `target` with several tar
    streams at once.

    Each stream extracts a contiguous part of the archive's member list, so the
    streams mostly create files in different directories. The files go into
    ``.<target name>.part`` first, which is renamed when complete, so `target`
    never exists half-written. Returns the number of files.
    """
    tarfile = Path(tarfile)
    target = Path(target)
    if target.exists():
        raise archives.ArchiveError(f"{target} already exists.")
    streams = max(1, streams or STREAMS)
    part = target.with_name(f".{target.name}.part")
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    members = _run(["tar", "-tf", tarfile], f"Listing {tarfile.name}").splitlines()
    files = [m for m in members if m and not m.endswith("/")]
    directories = [m for m in members if m.endswith("/")]
    lists = Path(part.parent) / f".{target.name}.lists"
    shutil.rmtree(lists, ignore_errors=True)
    lists.mkdir()
    t0 = time.time()
    try:
        processes = []
        size = -(-len(files) // streams)
        for i in range(streams):
            chunk = files[i * size : (i + 1) * size]
            if not chunk:
                break
            names = lists / f"{i:03d}"
            names.write_text("\n".join(chunk) + "\n")
            processes.append(
                subprocess.Popen(
                    [
                        "tar",
                        "-C",
                        str(part),
                        "--strip-components=1",
                        "-xf",
                        str(tarfile),
                        "-T",
                        str(names),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        errors = []
        for process in processes:
            out, err = process.communicate()
            if process.returncode != 0:
                errors.append(err.strip()[-1000:])
        if errors:
            raise archives.ArchiveError(
                f"Unpacking {tarfile.name} into {part} failed:\n" + "\n".join(errors)
            )
        # Directories that hold no files are not created by the streams
        for directory in directories:
            relative = Path(*Path(directory).parts[1:])
            (part / relative).mkdir(parents=True, exist_ok=True)
        count = sum(
            1 for path in part.rglob("*") if path.is_symlink() or not path.is_dir()
        )
        if count != len(files):
            raise archives.ArchiveError(
                f"Unpacking {tarfile.name} into {part} gave {count} files, not "
                f"{len(files)}."
            )
        os.rename(part, target)
    finally:
        shutil.rmtree(lists, ignore_errors=True)
    print(
        f"Unpacked {len(files)} files into {target} with {len(processes)} streams in "
        f"{time.time() - t0:.0f} s."
    )
    return len(files)


# ---- the operations ---------------------------------------------------------------


def apply_change(specs, constraints=None, upgrade=False, from_freeze=True, check=True):
    """`versions.apply_change` for archive storage: build on local disk, publish
    the archive, unpack it into ``<root>/venvs/<stamp>``, switch.

    Returns True if the change is now current, False if it was refused (and sets
    `versions.refused`). `check` False skips the check for regressions (recreate,
    which may take older versions from the lock on purpose).
    """
    from . import versions
    from .util import sync_manager

    versions.ensure_versioned()
    try:
        work = archives.build_directory() / f"seamm-venv-build-{os.getpid()}"
    except archives.ArchiveError as e:
        print(f"\n{e}")
        versions.refused = True
        return False
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    t0 = time.time()
    archive = None
    try:
        with _LocalCache(work / "uv-cache"):
            current = stage_current(work)
            name = new_version_name()
            new = Uv(work, name=TOP, python_version=current.python_version)
            versions.build_version(
                specs,
                constraints=constraints,
                upgrade=upgrade,
                from_freeze=from_freeze,
                current=current,
                new=new,
            )
            saved, my.uv = my.uv, new
            try:
                sync_manager()
            finally:
                my.uv = saved
            versions.synced_manager = True
            problems = versions.regressions(current, new, specs) if check else []
            if problems:
                print(
                    f"The new version {name} was built but NOT published:\n"
                    + "\n".join(f"    {line}" for line in problems)
                    + "\nNothing has changed. To take the newest releases instead, "
                    "use 'seamm-manager update --latest <packages>' (or "
                    "'--no-constraints')."
                )
                versions.refused = True
                return False
            print(f"   built in {time.time() - t0:.0f} s")
            archive = publish(new, work, name)
            install_job_scripts()
            target = my.uv.version(name)
            unpack(work / f"{NAME}.tar", target.path)
        if not versions.switch(target, force=bool(getattr(my.options, "force", False))):
            print(
                f"Jobs that stage the environment already use {archive.name}; "
                f"{my.uv.path} still links to {my.uv.current_version}."
            )
            versions.refused = True
            return False
        _prune()
        print(f"Done in {time.time() - t0:.0f} s; {archive.name} is current.")
        return True
    except archives.ArchiveError as e:
        print(f"\n{e}")
        if archive is None:
            print("Nothing has changed.")
        else:
            print(
                f"Jobs that stage the environment already use {archive.name}, but "
                f"{my.uv.path} was not switched to it. Finish with 'seamm-manager "
                "environment unpack' in a Slurm job."
            )
        versions.refused = True
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def archive_current():
    """Publish the installation's current environment as an archive, e.g. to start
    using archive storage. Returns the archive's path."""
    name = my.uv.current_version
    if name is None:
        raise archives.ArchiveError(
            f"{my.uv.path} is not a versioned environment; run "
            "'seamm-manager environment migrate' first."
        )
    existing = archive_for(name)
    if existing is not None:
        print(f"{existing.name} already exists.")
        follow(name)
        install_job_scripts()
        return existing
    from . import versions

    work = archives.build_directory() / f"seamm-venv-build-{os.getpid()}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        with _LocalCache(work / "uv-cache"):
            new = Uv(work, name=TOP, python_version=my.uv.python_version)
            # The exact packages of the current version, copied by their pins
            versions.build_version([], current=my.uv, new=new)
            problems = versions.regressions(my.uv, new)
            if problems:
                raise archives.ArchiveError(
                    "The copy differs from the current environment:\n"
                    + "\n".join(f"    {line}" for line in problems)
                )
            archive = publish(new, work, name)
        install_job_scripts()
        return archive
    finally:
        shutil.rmtree(work, ignore_errors=True)


def unpack_current(force=False):
    """Unpack the current archive into ``<root>/venvs/<stamp>`` and switch to it,
    e.g. when the job that published it ended before doing so."""
    from . import versions

    archive = current_archive()
    if archive is None:
        print("There is no archive of the SEAMM environment.")
        return False
    name = version_of(archive)
    target = my.uv.version(name)
    if target.exists:
        print(f"{target.path} already exists.")
    else:
        unpack(archive, target.path)
    if my.uv.current_version == name:
        print(f"{name} is already the current version.")
        return True
    return versions.switch(target, force=force)


def _prune():
    try:
        removed = archives.prune(_root(), NAME)
    except OSError as e:
        logger.warning(f"Could not prune the old archives: {e}")
        return
    for path in removed:
        if path.suffix == ".tar":
            print(f"Removed the old archive {path.name}.")
