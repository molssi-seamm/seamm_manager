"""Global module for passing around objects and constants."""

# The uv-managed environment that holds SEAMM (a seamm_manager.uv.Uv), and
# the conda wrapper the plug-in installers use for the external codes' own
# environments (None when conda is not installed; only needed then).
uv = None
conda = None
pip = None
development = None
# A label for this installation ("seamm" or "seamm-dev"): keys the metadata file
environment = None
logger = None
options = None
package_metadata = {}
# The published lock file for the package list, as a local path once fetched
lock = None
root = None
tag = ""  # the installation's tag (see naming.py)
