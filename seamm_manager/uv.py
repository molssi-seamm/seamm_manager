# -*- coding: utf-8 -*-

"""The uv-managed Python environment that holds SEAMM.

``Uv`` wraps the ``uv`` executable for one virtual environment, by default
``<root>/venv``. Every SEAMM package and every Python dependency is
installed into it from PyPI with ``uv pip install``; the interpreter itself
comes from ``uv python install``. Nothing here touches conda: the external
codes' own environments are handled by the plug-in installers.

Versioned environments
----------------------
Once an installation is *versioned*, ``<root>/venv`` is a symlink to the
current environment, which lives in ``<root>/venvs/<stamp>/``. An update
builds a new environment beside the current one and switches the link, so a
running job -- which imports lazily from the environment it started in -- never
sees a half-updated environment. Everything that launches a process (services,
apps, the JobServer's own jobs) must embed the *real* path, because CPython
does not resolve the symlink when it locates a venv: a process started as
``<root>/venv/bin/python`` would follow the link to whatever is current. So
``bin_path``, ``python``, ``bin()`` and ``which()`` all return paths under
``real_path``, and ``path`` stays the logical ``<root>/venv`` for messages.
"""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

logger = logging.getLogger(__name__)

DEFAULT_PYTHON = "3.12"
VERSIONS_DIR = "venvs"


def normalize(name):
    """The canonical form of a distribution name: lower case, '-' separators."""
    return re.sub(r"[-_.]+", "-", name).lower()


def find_uv():
    """The path to the ``uv`` executable, or None.

    Looks on ``PATH`` first, then where uv's own installer puts it.
    """
    uv = shutil.which("uv")
    if uv is None:
        candidate = Path.home() / ".local" / "bin" / "uv"
        if candidate.exists():
            uv = str(candidate)
    return uv


def _rewrite_paths(venv, old, new):
    """Replace the exact text `old` with `new` in the small text files of the
    environment's ``bin`` directory: the console scripts' shebangs and the
    ``activate`` scripts. Binary and large files are left alone."""
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    if not bin_dir.is_dir():
        return 0
    count = 0
    old_b, new_b = old.encode(), new.encode()
    for item in bin_dir.iterdir():
        if not item.is_file() or item.is_symlink():
            continue
        try:
            if item.stat().st_size > 1_000_000:
                continue
            data = item.read_bytes()
        except OSError:
            continue
        if old_b not in data:
            continue
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        mode = item.stat().st_mode
        item.write_bytes(data.replace(old_b, new_b))
        os.chmod(item, mode)
        count += 1
    return count


class UvError(RuntimeError):
    """A uv command failed; the message carries uv's own output."""


class Uv(object):
    """A uv-managed virtual environment.

    Parameters
    ----------
    root : pathlib.Path or str
        The SEAMM root; the environment lives in ``<root>/venv``.
    name : str = "venv"
        The environment directory name under the root.
    python_version : str = "3.12"
        The interpreter version to install when creating the environment.
    """

    def __init__(self, root, name="venv", python_version=DEFAULT_PYTHON):
        self.root = Path(root).expanduser()
        self.name = name
        self.python_version = python_version
        self._uv = None

    def __str__(self):
        return f"uv environment {self.path} (Python {self.python_version})"

    # ---- where things are -------------------------------------------------

    @property
    def uv(self):
        """The uv executable."""
        if self._uv is None:
            self._uv = find_uv()
            if self._uv is None:
                raise UvError(
                    "Cannot find 'uv'. Install it with\n"
                    "    curl -LsSf https://astral.sh/uv/install.sh | sh\n"
                    "and open a new shell, or put ~/.local/bin on your PATH."
                )
        return self._uv

    @property
    def path(self):
        """The environment's logical path, ``<root>/venv`` (a symlink once the
        installation is versioned). Use for messages; see `real_path`."""
        return self.root / self.name

    @property
    def real_path(self):
        """The directory the environment really lives in: `path` with a symlink
        resolved, so that paths embedded in launchers survive a switch."""
        path = self.path
        if path.is_symlink():
            try:
                return path.resolve()
            except OSError:
                return path
        return path

    @property
    def bin_path(self):
        return self.real_path / ("Scripts" if os.name == "nt" else "bin")

    # ---- versions -----------------------------------------------------------

    @property
    def versions_dir(self):
        """Where the versioned environments live, ``<root>/venvs``."""
        return self.root / VERSIONS_DIR

    @property
    def is_versioned(self):
        """Whether `path` is a symlink into `versions_dir`."""
        path = self.path
        if not path.is_symlink():
            return False
        try:
            return path.resolve().parent == self.versions_dir.resolve()
        except OSError:
            return False

    def versions(self):
        """The versioned environments, oldest first, as (name, path) pairs."""
        if not self.versions_dir.is_dir():
            return []
        result = []
        for item in sorted(self.versions_dir.iterdir()):
            if item.is_dir() and (item / "pyvenv.cfg").exists():
                result.append((item.name, item))
        return result

    @property
    def current_version(self):
        """The current version's name, or None if not versioned."""
        return self.real_path.name if self.is_versioned else None

    @staticmethod
    def new_version_name(now=None):
        """A version name from the time: ``2026-10-02T15-04-05``."""
        now = datetime.now() if now is None else now
        return now.strftime("%Y-%m-%dT%H-%M-%S")

    def version(self, name):
        """A ``Uv`` for the versioned environment ``name`` (which need not exist)."""
        return Uv(
            self.root,
            name=f"{VERSIONS_DIR}/{name}",
            python_version=self.python_version,
        )

    def switch_to(self, target):
        """Atomically point `path` (the ``venv`` symlink) at `target`.

        Parameters
        ----------
        target : pathlib.Path or str
            The versioned environment directory, under `versions_dir`.

        Raises
        ------
        UvError
            If `path` is a real directory (migrate first) or `target` is not an
            environment.
        """
        target = Path(target)
        if self.path.exists() and not self.path.is_symlink():
            raise UvError(
                f"{self.path} is a directory, not a link to a versioned "
                "environment; migrate it first."
            )
        if not (target / "pyvenv.cfg").exists():
            raise UvError(f"{target} is not a Python environment.")
        # A relative link, so the root can be moved as a whole.
        try:
            link_target = target.relative_to(self.root)
        except ValueError:
            link_target = target
        tmp = self.root / f".{self.name}-switch-{os.getpid()}"
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        tmp.symlink_to(link_target, target_is_directory=True)
        os.replace(tmp, self.path)
        logger.info(f"{self.path} -> {link_target}")

    def migrate_to_versioned(self, name=None):
        """Turn a plain ``<root>/venv`` directory into a versioned environment.

        The directory is renamed into `versions_dir` and `path` becomes a symlink
        to it. The rename keeps every inode, so processes running from it are
        unaffected. The scripts' shebangs and the ``activate`` scripts, which
        name the old path, are rewritten to the new one so that anything started
        from them afterwards is tied to this version, not to the link.

        Returns the version name, or None if there was nothing to migrate (already
        versioned, or no environment).
        """
        path = self.path
        if path.is_symlink() or not (path / "pyvenv.cfg").exists():
            return None
        name = self.new_version_name() if name is None else name
        target = self.versions_dir / name
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise UvError(f"{target} already exists.")
        os.rename(path, target)
        _rewrite_paths(target, str(path), str(target))
        self.switch_to(target)
        return name

    @property
    def python(self):
        """The environment's interpreter."""
        return self.bin_path / ("python.exe" if os.name == "nt" else "python")

    @property
    def exists(self):
        return self.python.exists()

    def bin(self, name):
        """The path an executable ``name`` would have in this environment."""
        return self.bin_path / name

    def which(self, name):
        """The path of executable ``name`` in this environment, or None."""
        path = self.bin(name)
        return path if path.exists() else None

    # ---- running uv ---------------------------------------------------------

    def run(self, *args, check=True, capture=True):
        """Run ``uv <args>`` and return the CompletedProcess.

        Raises UvError with uv's output if the command fails and ``check``.
        """
        command = [self.uv, *[str(a) for a in args]]
        logger.debug(" ".join(command))
        result = subprocess.run(
            command,
            capture_output=capture,
            text=True,
            env={**os.environ, "UV_NO_PROGRESS": "1"},
        )
        if check and result.returncode != 0:
            raise UvError(
                f"'{' '.join(command)}' failed (exit {result.returncode}):\n"
                f"{(result.stderr or '').strip()}\n{(result.stdout or '').strip()}"
            )
        return result

    # ---- the environment itself --------------------------------------------

    def create(self, python_version=None, seed=True):
        """Create the environment, installing the interpreter if needed.

        ``seed`` adds pip to the environment, which some tools (and the docs
        builds) expect to find as ``python -m pip``.
        """
        if python_version is not None:
            self.python_version = python_version
        print(f"Installing Python {self.python_version} with uv (if not present).")
        self.run("python", "install", self.python_version)
        print(f"Creating the environment {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Only a uv-managed interpreter: an active conda environment (on a cluster,
        # often a centrally provided base) would otherwise be preferred, and the
        # environment would break whenever that installation changed.
        args = [
            "venv",
            "--python",
            self.python_version,
            "--python-preference",
            "only-managed",
        ]
        if seed:
            args.append("--seed")
        args.append(self.path)
        self.run(*args)

    def remove(self):
        """Delete the environment: the real directory, and the link if versioned."""
        path = self.path
        if path.is_symlink():
            real = self.real_path
            path.unlink()
            if real.is_dir():
                shutil.rmtree(real)
        elif path.exists():
            shutil.rmtree(path)

    def python_version_installed(self):
        """The 'X.Y.Z' version of the environment's interpreter, or None."""
        if not self.exists:
            return None
        result = subprocess.run(
            [str(self.python), "--version"], capture_output=True, text=True
        )
        return result.stdout.strip().split()[-1] if result.returncode == 0 else None

    # ---- packages -----------------------------------------------------------

    def _pip(self, *args):
        return self.run("pip", *args, "--python", self.python)

    def install(self, packages, constraints=None, upgrade=False, refresh=True):
        """Install packages into the environment.

        Parameters
        ----------
        packages : str or [str]
            Requirement specifiers, e.g. ``"seamm"`` or ``"seamm==2026.9.25"``.
        constraints : pathlib.Path or str = None
            A constraints file (the published lock) passed with ``-c``.
        upgrade : bool = False
            Upgrade to the newest allowed versions: the named packages and their
            dependencies. With `constraints` (the lock) the allowed versions are the
            tested set. Without them the declared requirements of every other
            installed package are part of the resolution too (see
            `installed_requirements`), so a dependency moves only as far as all
            installed packages allow -- and uv reports an error, installing
            nothing, if no versions satisfy everything.
        refresh : bool = True
            Ignore uv's cached view of the index, so a release published minutes
            ago is seen. Without it uv can reuse stale index metadata and
            report nothing to do.
        """
        if isinstance(packages, str):
            packages = [packages]
        if len(packages) == 0:
            return
        args = ["install"]
        if refresh:
            args.append("--refresh")
        if upgrade:
            args.append("--upgrade")
        floors = None
        if constraints is not None:
            if self.exists:
                # Never below what is installed (seamm_manager#34)
                installed = {k: v["version"] for k, v in self.list().items()}
                text, floored = floored_constraints(
                    Path(constraints).read_text(), installed
                )
                if floored:
                    print(
                        "   keeping what is newer than the published lock: "
                        + ", ".join(sorted(floored))
                    )
                import tempfile

                floors = tempfile.NamedTemporaryFile(
                    "w", suffix="-constraints.txt", delete=False
                )
                floors.write(text)
                floors.close()
                args.extend(["--constraints", floors.name])
            else:
                args.extend(["--constraints", str(constraints)])
        context = None
        if upgrade and constraints is None and self.exists:
            # Resolve with every other installed package's requirements, so that
            # upgrading these packages' dependencies respects the caps those
            # packages declare (uv otherwise considers only the named packages).
            requirements = self.installed_requirements(_requirement_names(packages))
            if requirements:
                import tempfile

                context = tempfile.NamedTemporaryFile(
                    "w", suffix="-installed-requirements.txt", delete=False
                )
                context.write("\n".join(requirements) + "\n")
                context.close()
                args.extend(["--requirements", context.name])
        args.extend(packages)
        try:
            self._pip(*args)
        finally:
            if context is not None:
                Path(context.name).unlink(missing_ok=True)
            if floors is not None:
                Path(floors.name).unlink(missing_ok=True)
        self.report_conflicts()

    # The requirements of the installed packages, markers evaluated, extras-only
    # and URL requirements dropped. Run in the environment's own interpreter.
    # Run in the environment's own python, with only the standard library: the raw
    # requirements of each installed package and the values for evaluating their
    # markers (as packaging.markers.default_environment gives them).
    _REQUIREMENTS_SCRIPT = r"""
import importlib.metadata as m, json, os, platform, sys
impl = sys.implementation
version = impl.version
full = "{0.major}.{0.minor}.{0.micro}".format(version)
if version.releaselevel != "final":
    full += version.releaselevel[0] + str(version.serial)
environment = {
    "implementation_name": impl.name,
    "implementation_version": full,
    "os_name": os.name,
    "platform_machine": platform.machine(),
    "platform_release": platform.release(),
    "platform_system": platform.system(),
    "platform_version": platform.version(),
    "python_full_version": platform.python_version(),
    "platform_python_implementation": platform.python_implementation(),
    "python_version": ".".join(platform.python_version_tuple()[:2]),
    "sys_platform": sys.platform,
}
packages = [[d.metadata["Name"] or "", d.requires or []] for d in m.distributions()]
print(json.dumps({"environment": environment, "packages": packages}))
"""

    def installed_requirements(self, exclude=()):
        """The declared requirements of the installed packages.

        Parameters
        ----------
        exclude : [str]
            Packages whose own requirements to leave out (those being installed;
            requirements *on* them from other packages are kept, since they may cap
            the upgrade).

        Returns
        -------
        [str]
            Requirement specifiers.

        Raises
        ------
        UvError
            If they cannot be read; the upgrade must not go ahead blind.
        """
        if not self.exists:
            return []
        result = subprocess.run(
            [
                str(self.python),
                "-c",
                self._REQUIREMENTS_SCRIPT,
                json.dumps(list(exclude)),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise UvError(
                "Could not read the installed packages' requirements, which an "
                "upgrade without the lock needs so as not to break them: "
                + (result.stderr.strip().splitlines() or [""])[-1]
            )
        data = json.loads(result.stdout)
        environment = {**data["environment"], "extra": ""}
        exclude = {canonicalize_name(name) for name in exclude}
        requirements = set()
        for name, texts in data["packages"]:
            if canonicalize_name(name) in exclude:
                continue
            for text in texts:
                try:
                    requirement = Requirement(text)
                except InvalidRequirement:
                    continue
                if requirement.url:
                    continue
                marker = requirement.marker
                if marker is not None and not marker.evaluate(environment):
                    continue
                requirement.marker = None
                requirements.add(str(requirement))
        return sorted(requirements)

    def report_conflicts(self, quiet=False):
        """Print any installed package whose requirements are not met.

        Returns the conflicts as text ("" if there are none); `quiet` only
        returns them.
        """
        if not self.exists:
            return ""
        result = self.run("pip", "check", "--python", self.python, check=False)
        if result.returncode == 0:
            return ""
        text = (result.stdout or "") + (result.stderr or "")
        lines = [ln for ln in text.splitlines() if ln.strip() and "Checked" not in ln]
        if lines and not quiet:
            print("Warning: some installed packages' requirements are not met:")
            for line in lines:
                print(f"    {line.strip()}")
        return "\n".join(lines)

    def uninstall(self, packages):
        if isinstance(packages, str):
            packages = [packages]
        if len(packages) == 0:
            return
        self._pip("uninstall", *packages)

    def list(self):
        """The installed packages: ``{normalized name: {"version": str}}``."""
        if not self.exists:
            return {}
        result = self._pip("list", "--format", "json")
        packages = {}
        for item in json.loads(result.stdout or "[]"):
            packages[normalize(item["name"])] = {"version": item["version"]}
        return packages

    def freeze(self):
        """The ``pip freeze`` text for the environment (the audit trail)."""
        if not self.exists:
            return ""
        return self._pip("freeze").stdout

    # ---- the manager itself -------------------------------------------------

    def tool_upgrade(self, tool="seamm-manager"):
        """Upgrade a uv tool (the manager's own installation) to the newest
        release. Returns True if it succeeded.

        Not ``uv tool upgrade``: that reuses uv's cached view of the index and
        can report "Nothing to upgrade" minutes after a release. A forced
        reinstall with ``--refresh`` always consults PyPI.
        """
        result = self.run(
            "tool",
            "install",
            "--force",
            "--refresh",
            "--python",
            self.python_version,
            "--python-preference",
            "only-managed",
            tool,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"Could not update {tool} with uv:\n"
                + (result.stderr or result.stdout or "").strip()
                + "\nIf it no longer runs, reinstall it with\n"
                f"    uv tool install --force --python {self.python_version} {tool}"
            )
        return result.returncode == 0


def _requirement_names(specs):
    """The distribution names in requirement specifiers, e.g. seamm==1 -> seamm."""
    names = []
    for spec in specs:
        try:
            names.append(Requirement(str(spec)).name)
        except InvalidRequirement:
            names.append(str(spec).split("=")[0].split("<")[0].split(">")[0].strip())
    return names


def floored_constraints(lock_text, installed):
    """The published lock, with no pin below what is installed.

    The lock is a nightly snapshot, so it lags releases made since. Applied as
    uv constraints it governs every package uv resolves -- including those
    already installed -- so a pin older than the installed version would move
    that package backwards (seamm_manager#34). Such a pin becomes a floor,
    ``name>=installed``; every other line is kept as it is.

    Parameters
    ----------
    lock_text : str
        The lock: ``name==version`` lines, optionally with ``; markers``.
    installed : {str: str}
        Installed versions by distribution name.

    Returns
    -------
    (str, [str])
        The constraints text, and the names whose pins became floors.
    """
    from packaging.version import InvalidVersion, Version

    have = {canonicalize_name(k): v for k, v in installed.items()}
    lines = []
    floored = []
    for line in lock_text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            lines.append(line)
            continue
        try:
            requirement = Requirement(stripped)
        except InvalidRequirement:
            lines.append(line)
            continue
        name = canonicalize_name(requirement.name)
        pins = [s for s in requirement.specifier if s.operator in ("==", "===")]
        if name in have and len(pins) == 1:
            try:
                newer = Version(have[name]) > Version(pins[0].version)
            except InvalidVersion:
                newer = False
            if newer:
                marker = f" ; {requirement.marker}" if requirement.marker else ""
                lines.append(f"{requirement.name}>={have[name]}{marker}")
                floored.append(requirement.name)
                continue
        lines.append(line)
    return "\n".join(lines) + "\n", floored


def freeze_without(freeze_text, names):
    """``uv pip freeze`` output without the lines for `names`.

    A new environment version starts as a copy of the current one; the packages
    being changed are left out of the copy so that their new versions replace
    the old pins. Otherwise an environment whose installed versions conflict
    (one package needing a newer version of another) cannot even be copied, and
    so cannot be repaired by an update (seamm_manager#34).
    """
    drop = {canonicalize_name(n) for n in names}
    kept = []
    for line in freeze_text.splitlines():
        stripped = line.strip()
        name = None
        if stripped and not stripped.startswith(("#", "-")):
            match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(==|@)", stripped)
            if match:
                name = canonicalize_name(match.group(1))
        if name is not None and name in drop:
            continue
        kept.append(line)
    return "\n".join(kept) + ("\n" if kept else "")
