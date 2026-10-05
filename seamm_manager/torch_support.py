# -*- coding: utf-8 -*-

"""PyTorch for a code environment: which build this machine needs, what an
environment holds, and whether what it holds works.

PyTorch wheels bundle their CUDA runtime, so the build a machine needs is set
by its NVIDIA *driver*, which ``nvidia-smi`` reports as a CUDA version ceiling,
not by any CUDA toolkit installed on it. PyPI's default wheel bundles the newest
CUDA runtime, which an older driver cannot run: torch then imports and runs on
the CPU, and nothing says so. A plug-in whose code needs torch (xnn-step,
lammps-step's MLFF engine) therefore installs torch from the PyTorch index that
matches the driver, leaves a working torch alone, and checks the result.

The table of driver ceilings to wheel tags is the only part that goes stale:
update it when PyTorch adds a CUDA build. A machine's choice can be forced
with ``torch-build = <tag>`` in the plug-in's ``.ini`` file, or
``--torch-tag`` on its installer, for a cluster whose login node has no GPU.

The same reasoning, worked out by hand for the LAMMPS environment, is in
``lammps-mdi``'s ``cuda_utils``/``ml_install``; this module is the installer's
copy of it (lammps-mdi runs inside the code environment, where seamm-manager is
not installed).
"""

import json
import logging
import platform
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)

#: The PyTorch wheel indexes
TORCH_INDEX_BASE = "https://download.pytorch.org/whl"
PYPI_INDEX = "https://pypi.org/simple"

#: Minimum driver CUDA ceiling (major, minor) -> the newest PyTorch wheel tag that
#: driver can run, newest first. A wheel's bundled runtime may be newer than the
#: driver's ceiling within the same major version (CUDA's minor-version
#: compatibility), so cu128 runs on any 12.x driver from 12.1; a cu130 wheel needs
#: a 13.x driver. Update when PyTorch adds a build.
DRIVER_TO_TAG = (
    ((13, 0), "cu130"),
    ((12, 1), "cu128"),
    ((11, 8), "cu118"),
)

#: What a probe of an environment reports; see :func:`probe_script`
PROBE_KEYS = (
    "torch",
    "torch_version",
    "cuda_build",
    "cuda_available",
    "mps_available",
    "device_count",
    "imports",
)


def detect_cuda_driver():
    """The driver's CUDA ceiling as ``(major, minor)`` from ``nvidia-smi``, or
    ``None`` when there is no ``nvidia-smi``, it fails, or it reports no GPU."""
    smi = shutil.which("nvidia-smi")
    if smi is None:
        return None
    try:
        result = subprocess.run([smi], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug(f"nvidia-smi failed: {e}")
        return None
    match = re.search(r"CUDA Version:\s+(\d+)\.(\d+)", result.stdout)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def recommend_tag(driver):
    """The wheel tag for a driver ``(major, minor)``: the newest it can run, or
    ``None`` if it is older than any build in :data:`DRIVER_TO_TAG`."""
    for minimum, tag in DRIVER_TO_TAG:
        if tuple(driver) >= minimum:
            return tag
    return None


def torch_target(forced=None, system=None, driver="detect"):
    """Which torch build this machine should have.

    Parameters
    ----------
    forced : str, optional
        A tag to use regardless (``cu128``, ``cpu``, ``default``), from the
        ``.ini`` file or the command line. ``auto``/``""``/``None`` detect.
    system : str, optional
        ``platform.system()``; for tests.
    driver : tuple or None or "detect"
        The driver's CUDA ceiling; ``"detect"`` runs ``nvidia-smi``.

    Returns
    -------
    dict
        ``tag``: the wheel tag, ``"default"`` for PyPI's own wheel (macOS, where
        it carries MPS), ``"cpu"`` for the CPU build, ``None`` when nothing can be
        decided (Linux, no ``nvidia-smi``, nothing forced: the caller decides
        whether to assume a CPU machine); ``index_url``: the index for that tag,
        ``None`` for PyPI; ``driver``: what was detected; ``reason``: one line
        saying why.
    """
    system = system or platform.system()
    detected = detect_cuda_driver() if driver == "detect" else driver
    forced = (forced or "").strip().lower()
    if forced and forced != "auto":
        return _target(forced, detected, f"forced to {forced}")
    if system == "Darwin":
        return _target("default", detected, "macOS: PyPI's wheel, with MPS")
    if detected is None:
        return _target(None, None, "no NVIDIA driver found (no nvidia-smi)")
    tag = recommend_tag(detected)
    if tag is None:
        return _target(
            "cpu",
            detected,
            f"driver CUDA {detected[0]}.{detected[1]} is older than any PyTorch "
            "CUDA build; CPU build",
        )
    return _target(tag, detected, f"driver CUDA {detected[0]}.{detected[1]}")


def _target(tag, driver, reason):
    if tag in (None, "default"):
        index = None
    else:
        index = f"{TORCH_INDEX_BASE}/{tag}"
    return {"tag": tag, "index_url": index, "driver": driver, "reason": reason}


def pip_index_args(target):
    """The pip options that keep torch on the right index: the target's index
    first and PyPI as the extra index, so anything that pulls torch in during
    the step still gets the right build. Empty for PyPI's own wheel."""
    if not target or not target.get("index_url"):
        return []
    return ["--index-url", target["index_url"], "--extra-index-url", PYPI_INDEX]


def probe_script(imports=()):
    """Python that prints, as one JSON line, what an environment's torch is and
    whether the named modules import. Run it with the environment's python."""
    names = json.dumps(list(imports))
    return (
        "import json\n"
        "r = {'torch': False, 'torch_version': None, 'cuda_build': None,"
        " 'cuda_available': False, 'mps_available': False, 'device_count': 0,"
        " 'imports': {}}\n"
        "try:\n"
        "    import torch\n"
        "    r['torch'] = True\n"
        "    r['torch_version'] = torch.__version__\n"
        "    r['cuda_build'] = torch.version.cuda\n"
        "    r['cuda_available'] = bool(torch.cuda.is_available())\n"
        "    r['device_count'] = torch.cuda.device_count() if r['cuda_available']"
        " else 0\n"
        "    mps = getattr(torch.backends, 'mps', None)\n"
        "    r['mps_available'] = bool(mps is not None and mps.is_available())\n"
        "except Exception as e:\n"
        "    r['error'] = str(e)\n"
        f"for name in {names}:\n"
        "    try:\n"
        "        __import__(name)\n"
        "        r['imports'][name] = True\n"
        "    except Exception as e:\n"
        "        r['imports'][name] = str(e)\n"
        "print('PROBE ' + json.dumps(r))\n"
    )


def parse_probe(output):
    """The probe's dictionary from the python's output, or ``None``."""
    for line in reversed((output or "").splitlines()):
        if line.startswith("PROBE "):
            try:
                return json.loads(line[6:])
            except json.JSONDecodeError:
                return None
    return None


def assess(probe, target):
    """Judge an environment's torch against the machine.

    Returns
    -------
    (str, str)
        A status and a sentence. Statuses: ``missing`` (no torch); ``ok`` (torch
        works for this machine); ``gpu-unusable`` (a CUDA build that cannot see
        the GPU this machine has: the driver is too old for it); ``cpu-on-gpu``
        (a CPU build on a machine with an NVIDIA driver); ``unknown`` (the probe
        failed).
    """
    if probe is None:
        return "unknown", "the environment could not be probed"
    if not probe.get("torch"):
        return "missing", "torch is not installed"
    version = probe.get("torch_version")
    build = probe.get("cuda_build")
    has_gpu = bool(target and target.get("driver"))
    if has_gpu:
        if probe.get("cuda_available"):
            n = probe.get("device_count", 0)
            return "ok", f"torch {version} (CUDA {build}) sees {n} GPU(s)"
        if build:
            return (
                "gpu-unusable",
                f"torch {version} is built for CUDA {build} but cannot use this "
                f"machine's GPU (driver CUDA "
                f"{target['driver'][0]}.{target['driver'][1]} is too old for it)",
            )
        return "cpu-on-gpu", f"torch {version} is a CPU build on a machine with a GPU"
    if build:
        return "ok", f"torch {version} (CUDA {build}; no GPU here, runs on the CPU)"
    if probe.get("mps_available"):
        return "ok", f"torch {version} with Apple MPS"
    return "ok", f"torch {version} (CPU)"


def install_command(target, python="python", packages=("torch",)):
    """The pip command, as a list, that installs ``packages`` from the target's
    index."""
    return [python, "-m", "pip", "install", *pip_index_args(target), *packages]
