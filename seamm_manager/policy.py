# -*- coding: utf-8 -*-

"""How an installation gets the external codes' conda environments.

Every installation on a machine would otherwise share the codes' conda environments
by name (``seamm-lammps``, ``seamm-mopac``, ...), so installing or updating plug-ins
in a trial installation could change production's codes. Each installation therefore
has a *code-environment policy*, kept in ``<root>/installation.ini``:

own
    The plug-ins create and update the codes' environments, as always. The default,
    and the only choice, for the default installation ``~/SEAMM``.
shared
    The plug-ins never create, update or remove a conda environment. Installing a
    plug-in copies the default installation's ``<code>.ini`` into this root, so the
    code runs from the same environment, and reports a code the default installation
    does not have; updating only reports. The default for any other root.
prefixed
    The installation has its own copies, named ``seamm-<tag>-<code>`` (e.g.
    ``seamm-SEAMM_NEW-lammps``), for testing new versions of the codes themselves.

(The file is not ``<root>/seamm.ini``: seamm_util still moves an old
``~/SEAMM/seamm.ini`` into ``~/.seamm.d``.)
"""

import configparser
from pathlib import Path

DEFAULT_ROOT = Path("~/SEAMM").expanduser()
POLICY_FILE = "installation.ini"
SECTION = "installation"
KEY = "code-environments"
POLICIES = ("own", "shared", "prefixed")


def is_default_root(root):
    """Whether `root` is the default installation, ~/SEAMM."""
    try:
        return Path(root).expanduser().resolve() == DEFAULT_ROOT.resolve()
    except OSError:
        return False


def code_environment_policy(root):
    """The installation's code-environment policy: own, shared or prefixed."""
    if is_default_root(root):
        return "own"
    path = Path(root).expanduser() / POLICY_FILE
    if path.exists():
        config = configparser.ConfigParser(interpolation=None)
        config.read(path)
        value = config.get(SECTION, KEY, fallback="").strip().lower()
        if value in POLICIES:
            return value
    return "shared"


def set_code_environment_policy(root, policy):
    """Record the installation's code-environment policy."""
    if policy not in POLICIES:
        raise ValueError(f"The policy must be one of {', '.join(POLICIES)}.")
    if is_default_root(root) and policy != "own":
        raise ValueError(
            "The default installation ~/SEAMM always manages the codes' environments "
            "itself ('own')."
        )
    path = Path(root).expanduser() / POLICY_FILE
    config = configparser.ConfigParser(interpolation=None)
    if path.exists():
        config.read(path)
    if not config.has_section(SECTION):
        config.add_section(SECTION)
    config.set(SECTION, KEY, policy)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fd:
        config.write(fd)
    return path


def prefixed_environment(name, tag):
    """The installation's own copy of a code environment: seamm-<tag>-<code>."""
    if not tag:
        return name
    if name.startswith("seamm-"):
        return f"seamm-{tag}-{name[len('seamm-'):]}"
    return f"{tag}-{name}"
