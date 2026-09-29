# -*- coding: utf-8 -*-

"""The uv-managed Python environment that holds SEAMM.

``Uv`` wraps the ``uv`` executable for one virtual environment, by default
``<root>/venv``. Every SEAMM package and every Python dependency is
installed into it from PyPI with ``uv pip install``; the interpreter itself
comes from ``uv python install``. Nothing here touches conda: the external
codes' own environments are handled by the plug-in installers.
"""

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
        """The environment directory."""
        return self.root / self.name

    @property
    def bin_path(self):
        return self.path / ("Scripts" if os.name == "nt" else "bin")

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
        """Delete the environment directory."""
        if self.path.exists():
            shutil.rmtree(self.path)

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
        if constraints is not None:
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

    def report_conflicts(self):
        """Print any installed package whose requirements are not met.

        Returns the conflicts as text ("" if there are none).
        """
        if not self.exists:
            return ""
        result = self.run("pip", "check", "--python", self.python, check=False)
        if result.returncode == 0:
            return ""
        text = (result.stdout or "") + (result.stderr or "")
        lines = [ln for ln in text.splitlines() if ln.strip() and "Checked" not in ln]
        if lines:
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
