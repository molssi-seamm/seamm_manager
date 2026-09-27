# -*- coding: utf-8 -*-

"""Names of an installation's services, apps and service bundles.

Several SEAMM installations can live on one machine (``~/SEAMM``, ``~/SEAMM_DEV``,
``~/SEAMM_NEW``, ...). Each is identified by a *tag*: empty for the default
installation ``~/SEAMM``, otherwise the root's directory name with its case kept
(or the ``--name`` given to the manager). The default installation keeps the plain
names (``jobserver``, ``SEAMM``); any other gets the tag in its names
(``jobserver-SEAMM_DEV``, ``SEAMM (SEAMM_DEV)``), so installations never collide.
"""

from pathlib import Path

from . import my

DEFAULT_ROOT = Path("~/SEAMM").expanduser()


def compute_tag(root, name=None):
    """The tag for the installation at `root`.

    Parameters
    ----------
    root : str or pathlib.Path
        The installation's root.
    name : str = None
        An explicit name for the installation, which wins.

    Returns
    -------
    str
        "" for the default installation ~/SEAMM.
    """
    if name:
        return name
    root = Path(root).expanduser()
    try:
        if root.resolve() == DEFAULT_ROOT.resolve():
            return ""
    except OSError:
        pass
    return root.name


def tag():
    """The current installation's tag."""
    return getattr(my, "tag", "") or ""


def service_name(service):
    """The service's name for this installation, e.g. jobserver-SEAMM_DEV."""
    t = tag()
    return service if t == "" else f"{service}-{t}"


def app_name(app):
    """The desktop app's name for this installation, e.g. SEAMM (SEAMM_DEV)."""
    t = tag()
    return app if t == "" else f"{app} ({t})"


def bundle_name(base):
    """A service bundle's name for this installation, e.g. SEAMM-JobServer-SEAMM_DEV."""
    t = tag()
    return base if t == "" else f"{base}-{t}"


def service_kind(name):
    """The kind of a SEAMM service from its name: jobserver, webui or dashboard.

    Handles the current names (``jobserver``, ``jobserver-SEAMM_NEW``) and the older
    development names (``dev_jobserver``).
    """
    if name.startswith("dev_"):
        name = name[4:]
    return name.split("-", 1)[0]


def same_root(a, b):
    """Whether two root paths name the same directory."""
    if a is None or b is None:
        return False
    try:
        return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()
    except OSError:
        return False
