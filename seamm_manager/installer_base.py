# !/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import logging
import os
import re
from pathlib import Path
import shutil

import seamm_manager

logger = logging.getLogger(__name__)

prolog = """\
# Configuration options for SEAMM.
#
# The options in this file override any defaults in SEAMM
# and its plug-ins; however, command-line arguments will
# in turn override the values here.
#
# The keys should have dashes '-' separating words. In either case,
# the command line options is '--<key with dashes>' and the variable
# name inside SEAMM is '<key with underscores>', e.g. 'log-level' in
# this file corresponds to the command line option '--log-level'
# and the variable in SEAMM 'log_level'.
#
# The file is broken into sections, with a name in square brackets,
# like [lammps-step]. Within each section there can be a series of
# option = value statements. '#' introduces comment lines. The
# section names and variables should be in lower case except for
# the [DEFAULT] and [SEAMM] sections which are special.
#
# [DEFAULT] provides default values for any other section. If an
# option is requested for a section, but does not exist in that
# section, the option is looked for in the [DEFAULT] section. If it
# exists there, the corresponding value is used.
#
# The [SEAMM] section contains options for the SEAMM environment
# itself. On the command line these come before any options for
# plug-ins, which follow the name of the plug-in. The plug-in name is
# also the section in this file for that plug-in.
#
# All other sections are for the plug-ins, and generally have the form
# [xxxxx-step], in lowercase.
#
# Finally, options can refer to options in the same or other sections
# with a syntax like ${section:option}. If the section is omitted,
# the current section and [DEFAULT] are searched, in that
# order. Otherwise the given section and [DEFAULT] are searched.

[DEFAULT]
# Default values for options in any section.

[SEAMM]
# Options for the SEAMM infrastructure.

"""


def environment_created_by_seamm(prefix):
    """Whether conda's history says a SEAMM installer created the environment at
    ``prefix``: its first command is ``conda env create ... --file
    seamm-<step>.yml``. ``None`` when the history cannot be read."""
    try:
        history = Path(prefix) / "conda-meta" / "history"
        for line in history.read_text(errors="replace").splitlines():
            if line.startswith("# cmd:"):
                return bool(
                    re.search(r"\benv\s+create\b", line)
                    and re.search(r"--file\s+\S*seamm-[\w.-]+\.ya?ml", line)
                )
    except Exception:
        pass
    return None


class InstallerBase(object):
    """A base class for plug-in installers.

    This base class provides much of the functionality needed by installers for
    plug-ins, but not the functionality specific to a given plug-in.

    Attributes
    ----------
    section : str
        The section of the configuration file to use. Defaults to None.
    """

    def __init__(self, ini_file="~/.seamm.d/seamm.ini", logger=logger):
        # Create the ini file if it does not exist.
        self._check_ini_file(ini_file)

        self.logger = logger

        # and make the configuration, conda and pip objects
        self._configuration = seamm_manager.Configuration(ini_file)
        self._conda = seamm_manager.Conda()
        self._pip = seamm_manager.Pip()

        # Setup the parseer for the command-line
        self.options = None
        self.subparser = {}
        self.parser = self.setup_parser()

        # Other attributes
        self.section = None
        self.path_name = None
        self.executables = None
        self.resource_path = None
        self._root = None
        self._exe_config = seamm_manager.Configuration(None)
        self._init_file_name = None
        self.environment = None
        #: A plug-in whose code needs PyTorch sets this: torch is then installed
        #: from the index matching the machine's NVIDIA driver, a working torch is
        #: left alone, and the environment is checked after install and update
        #: (seamm_manager.torch_support). ``torch_imports`` names the modules the
        #: check must import, e.g. ("torch", "xnn", "mdi").
        self.torch_managed = False
        self.torch_imports = ("torch",)

    @property
    def conda(self):
        """The Conda object to use for accessing Conda."""
        return self._conda

    @property
    def configuration(self):
        """The Configuration object for working with the ini file."""
        return self._configuration

    @property
    def exe_config(self):
        # The ini data for the executables
        if self._exe_config.path is None:
            path = self.root / self.init_file_name
            if path.exists():
                self._exe_config.path = path
        return self._exe_config

    @property
    def init_file_name(self):
        """The initialization file for the executable."""
        if self._init_file_name is None:
            self._init_file_name = self.section.replace("-step", "") + ".ini"
        return self._init_file_name

    @init_file_name.setter
    def init_file_name(self, value):
        self._init_file_name = value

    @property
    def pip(self):
        """The Pip object used for working with pip."""
        return self._pip

    @property
    def root(self):
        """The root of the SEAMM installation being worked on.

        In order: ``SEAMM_ROOT``, which seamm-manager sets for the installation it is
        working on; ``root`` in the ``[SEAMM]`` section of the per-user seamm.ini
        (deprecated, since every installation shares that file); the installation this
        Python belongs to (``<root>/venv``); ``~/SEAMM``. The codes' ``.ini`` files are
        written here.
        """
        if self._root is None:
            value = os.environ.get("SEAMM_ROOT", "").strip()
            if value == "" and self.configuration.section_exists("SEAMM"):
                value = self.configuration.get_values("SEAMM").get("root", "") or ""
            if value == "":
                try:
                    from seamm_util import installation_root
                except ImportError:  # seamm-util older than 2026.9.27
                    installation_root = None
                root = installation_root() if installation_root else None
                value = str(root) if root is not None else "~/SEAMM"
            self._root = Path(value).expanduser()
        return self._root

    @property
    def code_environments(self):
        """This installation's code-environment policy: own, shared or prefixed.

        See seamm_manager.policy. In a ``shared`` installation the plug-ins never
        create, update or remove a conda environment.
        """
        from .policy import code_environment_policy

        return code_environment_policy(self.root)

    @property
    def shared_codes(self):
        """Whether this installation uses the default installation's codes."""
        return self.code_environments == "shared"

    def _use_shared_code(self):
        """Point this installation at the default installation's copy of the code.

        Copies ``~/SEAMM/<code>.ini`` into this root if the root has none, and
        reports whether the conda environment it names exists. Never touches conda.
        """
        from .policy import DEFAULT_ROOT

        name = self.init_file_name
        own = self.root / name
        default = DEFAULT_ROOT / name
        if not own.exists():
            if not default.exists():
                print(
                    f"    This installation shares the default installation's codes, "
                    f"which has no {name}: install the code there first "
                    f"(seamm-manager install {self.section}), or give this "
                    "installation its own codes (--code-environments own or prefixed)."
                )
                return False
            own.parent.mkdir(parents=True, exist_ok=True)
            own.write_text(default.read_text())
            print(f"    Using the default installation's configuration {default}.")
        self.exe_config.path = own
        data = self.exe_config.get_values("local")
        environment = data.get("conda-environment", "")
        if data.get("installation") == "conda" and environment:
            if self.conda.exists(environment):
                print(f"    Shares the Conda environment '{environment}'.")
                return True
            print(
                f"!   The Conda environment '{environment}' named in {own} does not "
                "exist. Install the code in the default installation first."
            )
            return False
        print(f"    Uses the code as configured in {own}.")
        return True

    # An environment file is applied again only if it changed, or after this long,
    # so that ``update --all`` is quick but the codes still get new builds.
    REFRESH_DAYS = 7

    def _applied_marker(self, environment):
        """The file recording which environment file was last applied."""
        return (
            self.conda.path(environment) / "conda-meta" / f"seamm-{self.section}.sha256"
        )

    def _environment_file_hash(self):
        import hashlib

        return hashlib.sha256(Path(self.environment_file).read_bytes()).hexdigest()

    def _unchanged_since_applied(self, environment):
        """Whether the environment file was applied recently and not changed since.

        ``SEAMM_REFRESH_CODES`` (set by ``seamm-manager update --refresh-codes``)
        forces the file to be applied again.
        """
        import time

        if os.environ.get("SEAMM_REFRESH_CODES"):
            return False
        try:
            marker = self._applied_marker(environment)
            if not marker.exists():
                return False
            age_days = (time.time() - marker.stat().st_mtime) / 86400
            return (
                marker.read_text().strip() == self._environment_file_hash()
                and age_days < self.REFRESH_DAYS
            )
        except Exception:
            return False

    def _not_ours(self, environment):
        """Whether ``environment`` exists but was not made by a SEAMM installer.

        Conda records in ``conda-meta/history`` the command that created an
        environment; one SEAMM made was created ``--file seamm-<step>.yml``. That
        is the test. An environment with the name SEAMM gives it is SEAMM's; one
        whose history cannot be read falls back to the ``seamm-<step>.sha256``
        records SEAMM leaves when it applies a file. Anything else -- a
        hand-built environment named in the .ini file (a pinned CUDA torch, a
        package from a git commit) -- is the user's, and an update must not
        apply SEAMM's environment file to it (seamm_manager#28). The records
        alone were not enough: an environment SEAMM mistakenly updated once has
        them and is still not SEAMM's.
        """
        try:
            if not self.conda.exists(environment):
                return False
            if environment == self.environment:
                return False
            prefix = self.conda.path(environment)
            created = environment_created_by_seamm(prefix)
            if created is not None:
                return not created
            return not any((prefix / "conda-meta").glob("seamm-*.sha256"))
        except Exception:
            return False

    def _record_applied(self, environment):
        try:
            marker = self._applied_marker(environment)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(self._environment_file_hash() + "\n")
        except Exception as e:  # never fail an installation over the record
            self.logger.debug(f"Could not record the applied environment file: {e}")

    # ------------------------------------------------------------------
    # PyTorch in a code environment (torch_managed plug-ins)
    # ------------------------------------------------------------------
    def torch_target(self):
        """The torch build this machine needs: ``--torch-tag`` on the command
        line, else ``torch-build`` in the plug-in's .ini file (``auto`` detects),
        else detection. See :func:`seamm_manager.torch_support.torch_target`."""
        from . import torch_support

        forced = getattr(self.options, "torch_tag", None)
        if not forced:
            try:
                forced = self.exe_config.get_values("local").get("torch-build", "")
            except Exception:
                forced = ""
        return torch_support.torch_target(forced=forced)

    def _probe_torch(self, environment):
        from . import torch_support

        output = self.conda.run_python(
            environment, torch_support.probe_script(self.torch_imports)
        )
        return torch_support.parse_probe(output)

    def _ensure_torch(self, environment, apply_file=True):
        """Bring the environment's torch into line with the machine, apply the
        plug-in's environment file (its pip part on torch's index), and check.

        Returns True when the environment is usable afterwards. Prints what it
        found and did; never replaces a torch that works, and never replaces a
        broken one silently -- that takes ``--torch-tag`` (or
        ``SEAMM_REFRESH_CODES``), since a user may have built it deliberately.
        """
        from . import torch_support

        target = self.torch_target()
        probe = self._probe_torch(environment)
        status, note = torch_support.assess(probe, target)
        print(f"    PyTorch: {note}.")
        forced = bool(getattr(self.options, "torch_tag", None)) or bool(
            os.environ.get("SEAMM_REFRESH_CODES")
        )
        index_args = torch_support.pip_index_args(target)

        if status == "missing" or (status in ("gpu-unusable", "cpu-on-gpu") and forced):
            if target["tag"] is None:
                print(
                    "!   No NVIDIA driver was found on this machine, so which torch "
                    "to install cannot be decided here (a cluster login node, for "
                    "instance, has no GPU although its compute nodes do). Set "
                    f"'torch-build = <tag>' in {self.section}.ini -- cu128 for a "
                    "current NVIDIA driver, cpu for a machine without a GPU -- or "
                    "run the installer with --torch-tag, and try again."
                )
                return False
            what = "Installing" if status == "missing" else "Replacing"
            where = target["index_url"] or "PyPI"
            print(f"    {what} torch from {where} ({target['reason']}).")
            self.conda.pip_install(
                environment,
                ["torch"],
                upgrade=(status != "missing"),
                index_args=index_args,
            )
        elif status in ("gpu-unusable", "cpu-on-gpu"):
            print(
                f"!   {note}. It is left as it is: it may have been built on purpose. "
                f"To replace it with the build for this machine "
                f"({target['tag'] or 'undecided'}), run the installer again with "
                f"--torch-tag {target['tag'] or '<tag>'}."
            )
            if status == "gpu-unusable":
                # Nothing that depends on torch will work; do not pile on.
                return False
        elif status == "unknown":
            print(f"!   {note}; the environment is left as it is.")
            return False

        if apply_file:
            self.conda.update_environment(
                self.environment_file, name=environment, index_args=index_args
            )
            self._record_applied(environment)

        probe = self._probe_torch(environment)
        status, note = torch_support.assess(probe, target)
        failed = [
            f"{name}: {err}"
            for name, err in (probe or {}).get("imports", {}).items()
            if err is not True
        ]
        if status != "ok" or failed:
            print(f"!   Check of '{environment}' failed: {note}.")
            for line in failed:
                print(f"!       {line}")
            return False
        print(f"    Checked '{environment}': {note}; imports OK.")
        return True

    def ask_yes_no(self, text, default=None):
        """Ask a simple yes/no question, returning True/False.

        Parameters
        ----------
        text : str
             The text of the question.

        Returns
        -------
        bool
            True for yes; False, no
        """
        if default is None:
            answer = input(f"{text} y/n: ")
        elif default == "yes":
            answer = input(f"{text} [y]/n: ")
        elif default == "no":
            answer = input(f"{text} y/[n]: ")
        else:
            answer = input(f"{text} y/n: ")

        while True:
            if len(answer) == 0:
                if default == "yes":
                    return True
                elif default == "no":
                    return False
            else:
                answer = answer[0].lower()
                if answer == "y":
                    return True
                elif answer == "n":
                    return False
            input("Please answer 'y' or 'n': ")

    def _check_ini_file(self, ini_file):
        """Ensure that the ini file exists.

        If it does not, it will be created and a template written to it. The
        template contains a prolog with a description of the file followed by
        empty [DEFAULT] and [SEAMM] sections, which ensures that they are
        present and at the top of the file.
        """
        path = Path(ini_file).expanduser().resolve()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(prolog)

    def check(self):
        """Check the installation and fix errors if requested.

        If the option `yes` is present and True, this method will attempt to
        correct any errors in the configuration file. Use `--yes` on the
        command line to enable this.

        The information in the configuration file is:

            installation
                How the executables are installed. One of `user`, `modules` or `conda`
            conda-environment
                The Conda environment if and only if `installation` = `conda`
            modules
                The environment modules if `installation` = `modules`
            {self.path_name}
                The path where the executables are. Automatically
                defined if `installation` is `conda` or `modules`, but given
                by the user is it is `user`.

        Returns
        -------
        bool
            True if everything is OK, False otherwise. If `yes` is given as an
            option, the return value is after fixing the configuration.
        """
        self.logger.debug("Entering check method.")
        if not self.configuration.section_exists(self.section):
            if self.options.yes or self.ask_yes_no(
                f"There is no section for {self.section} in the configuration "
                f" file ({self.configuration.path}).\nAdd one?",
                default="yes",
            ):
                self.check_configuration_file()
                print(
                    f"    Added the {self.section} section to the configuration file "
                    f"{self.configuration.path}"
                )

        # Ensure that the config file for the executable exists
        self.check_exe_configuration_file()

        # Get the values from the executable configuration
        data = self.exe_config.get_values("local")

        if "conda-environment" in data and data["conda-environment"] != "":
            self.environment = data["conda-environment"]

        # Save the initial values, if any, of the key configuration variables
        if self.path_name in data and data[self.path_name] != "":
            path = Path(data[self.path_name]).expanduser().resolve()
            initial_exe_path = path
        else:
            initial_exe_path = None
        if "installation" in data and data["installation"] != "":
            initial_installation = data["installation"]
        else:
            initial_installation = None
        if "conda-environment" in data and data["conda-environment"] != "":
            initial_conda_environment = data["conda-environment"]
        else:
            initial_conda_environment = None
        if "modules" in data and data["modules"] != "":
            initial_modules = data["modules"]
        else:
            initial_modules = None

        # Is there a valid -path?
        self.logger.debug(
            "Checking for the executable in the initial path " f"{initial_exe_path}."
        )
        if initial_exe_path is None or not self.have_executables(initial_exe_path):
            exe_path = None
        else:
            exe_path = initial_exe_path
        self.logger.debug(f"initial-exe-path = {initial_exe_path}.")

        # Is there an installation indicated?
        if initial_installation in ("conda", "modules", "local"):
            installation = initial_installation
        else:
            installation = None
        self.logger.debug(f"initial-installation = {initial_installation}.")

        if installation == "conda":
            # Is there a conda environment?
            conda_environment = None
            if initial_conda_environment is None or not self.conda.exists(
                initial_conda_environment
            ):
                if exe_path is not None:
                    # see if this path corresponds to a Conda environment
                    for tmp in self.conda.environments:
                        tmp_path = self.conda.path(tmp) / "bin"
                        if tmp_path == exe_path:
                            conda_environment = tmp
                            break
                    if conda_environment is not None:
                        if self.options.yes or self.ask_yes_no(
                            "The Conda environment in the config file "
                            "is not correct.\n"
                            f"It should be {conda_environment}. Fix?",
                            default="yes",
                        ):
                            self.exe_config.set_value("local", "installation", "conda")
                            self.exe_config.set_value(
                                "local", "conda-environment", conda_environment
                            )
                            conda_exe = seamm_manager.find_conda()
                            if conda_exe is None:
                                print(
                                    "    Cannot find the path to the conda executable! "
                                    "Please fix the path in the configuration file."
                                )
                            else:
                                self.exe_config.set_value("local", "conda", conda_exe)

                            # Clean up the environment file
                            self.exe_config.set_value("local", "modules", None)
                            self.exe_config.set_value("local", "container", None)
                            self.exe_config.set_value("local", "platform", None)

                            self.exe_config.save()

                            print(
                                "    Corrected the conda environment to "
                                f"{conda_environment}"
                            )
                else:
                    conda_environment = None
                    print(
                        "    The mopac.ini file specifies using a Conda environment, "
                        "however, the executable(s) are not in the environment."
                    )
            else:
                # Have a Conda environment!
                conda_path = self.conda.path(initial_conda_environment) / "bin"
                self.logger.debug(
                    f"Checking for executable in conda-path: {conda_path}."
                )
                if self.have_executables(conda_path):
                    # All is good!
                    conda_environment = initial_conda_environment
                    conda_exe = seamm_manager.find_conda()
                    if conda_exe is None:
                        print(
                            "    Cannot find the path to the conda executable! "
                            "Please fix the path in the configuration file."
                        )
                    else:
                        self.exe_config.set_value("local", "conda", conda_exe)
                        self.exe_config.save()
                        print("    The conda path is correct.")
                else:
                    conda_environment = None
                    print(
                        "    The mopac.ini file specifies using a Conda environment, "
                        "however, the executable(s) are not in the environment."
                    )
        elif installation == "modules":
            print(f"Can't check the actual modules {initial_modules} yet")
            if initial_conda_environment is not None:
                if self.options.yes or self.ask_yes_no(
                    "A Conda environment is given: "
                    f"{initial_conda_environment}.\n"
                    "A Conda environment should not be used when using "
                    "modules. Remove it from the configuration?",
                    default="yes",
                ):

                    # Clean up the environment file
                    self.exe_config.set_value("local", "conda", None)
                    self.exe_config.set_value("local", "conda-environment", None)
                    self.exe_config.set_value("local", "container", None)
                    self.exe_config.set_value("local", "platform", None)

                    self.exe_config.save()
                    print(
                        "    Using modules, so removed the conda-environment from "
                        "the configuration"
                    )
        else:
            if exe_path is None:
                # No path or executable in the path!
                environments = self.conda.environments
                if self.environment in environments:
                    # Make sure it is first!
                    environments.remove(self.environment)
                    environments.insert(0, self.environment)
                for tmp in environments:
                    tmp_path = self.conda.path(tmp) / "bin"
                    if self.have_executables(tmp_path):
                        if self.options.yes or self.ask_yes_no(
                            f"There are no valid executables in the {self.path_name}"
                            " in the config file, but there are in the Conda "
                            f"environment {tmp} ({tmp_path}).\n"
                            "Use them?",
                            default="yes",
                        ):
                            conda_environment = tmp
                            exe_path = tmp_path
                            self.exe_config.set_value("local", self.path_name, exe_path)
                            self.exe_config.set_value("local", "installation", "conda")
                            self.exe_config.set_value(
                                "local", "conda-environment", conda_environment
                            )

                            # Clean up the environment file
                            self.exe_config.set_value("local", "conda", None)
                            self.exe_config.set_value(
                                "local", "conda-environment", None
                            )
                            self.exe_config.set_value("local", "modules", None)
                            self.exe_config.set_value("local", "conda", None)
                            self.exe_config.set_value("local", "container", None)
                            self.exe_config.set_value("local", "platform", None)

                            self.exe_config.save()

                            print(
                                "    Will use the conda environment "
                                f"'{conda_environment}'"
                            )
                            break
            if exe_path is None:
                # Haven't found it. Check in the path.
                exe_path = self.executables_in_path()
                if exe_path is not None:
                    if self.options.yes or self.ask_yes_no(
                        "Found valid executable(s) in the PATH at "
                        f"{exe_path}\n"
                        "Use them?",
                        default="yes",
                    ):
                        self.exe_config.set_value("local", "installation", "local")

                        # Clean up the environment file
                        self.exe_config.set_value("local", "conda", None)
                        self.exe_config.set_value("local", "conda-environment", None)
                        self.exe_config.set_value("local", "modules", None)
                        self.exe_config.set_value("local", "container", None)
                        self.exe_config.set_value("local", "platform", None)

                        self.exe_config.save()
                        print("    Using the executable(s) at {exe_path}")

            if exe_path is None:
                # Can't find the executable(s)
                print(
                    f"    Cannot find the executable(s): {', '.join(self.executables)}."
                    "\n    You will need to install them."
                )
                if (
                    initial_installation is not None
                    and initial_installation != "not installed"
                ):
                    if self.options.yes or self.ask_yes_no(
                        "The configuration file indicates that the executable(s) "
                        "are installed, but they can't be found.\n"
                        "Fix the configuration file?",
                        default="yes",
                    ):
                        # Update the configuration file.
                        self.exe_config.set_value("local", "installation", None)
                        self.exe_config.set_value("local", "conda", None)
                        self.exe_config.set_value("local", "conda-environment", None)
                        self.exe_config.set_value("local", "modules", None)
                        self.exe_config.set_value("local", "container", None)
                        self.exe_config.set_value("local", "platform", None)

                        self.exe_config.save()

                        print(
                            "    Since no executable(s) were found, cleared "
                            "the configuration."
                        )
            else:
                print("    The check completed successfully.")

    def check_configuration_file(self):
        """Checks that the necessary section for the plug-in is in the
        configuration file.
        """
        if not self.configuration.section_exists(self.section):
            # Get the text of the data
            path = self.resource_path / "configuration.txt"
            text = path.read_text()

            # Add it to the configuration file and write to disk.
            self.configuration.add_section(self.section, text)
            self.configuration.save()

    def check_exe_configuration_file(self):
        """Checks that the init file for the executable for the plug-in exists.

        If it does not, it is created from the plug-in's template
        (``data/<code>.ini``), when the plug-in ships one.

        Returns
        -------
        bool
            True if the file was created.
        """
        path = self.root / self.init_file_name
        created = False
        if not path.exists():
            template = (
                None
                if self.resource_path is None
                else self.resource_path / self.init_file_name
            )
            if template is not None and template.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(template.read_text())
                print(
                    f"    The {self.init_file_name} file did not exist. Created {path}"
                )
                created = True

        self.exe_config.path = path
        return created

    @property
    def manual_code(self):
        """Whether the code is installed by hand rather than with Conda.

        Licensed codes such as ORCA, Gaussian and VASP have no environment file.
        """
        return (
            getattr(self, "environment_file", None) is None or self.environment is None
        )

    def _check_manual_code(self):
        """Give a hand-installed code its configuration file, and say how to finish.

        The plug-in's template is written to ``<root>/<code>.ini`` if the file does
        not exist; an existing file is never changed.
        """
        path = self.root / self.init_file_name
        if self.check_exe_configuration_file():
            print(
                "    This code is not installed automatically. Install it yourself, "
                f"then edit {path} to say how to run it."
            )
        elif not path.exists():
            print(
                "    This code is not installed automatically. Install it yourself "
                f"and give its location in {path}."
            )

    def have_executables(self, path):
        """Check whether the executables are found at the given path.

        Parameters
        ----------
        path : pathlib.Path
            The directory to check.

        Returns
        -------
        bool
            True if all of the executables are found.
        """
        for executable in self.executables:
            tmp_path = path / executable
            if not tmp_path.exists():
                self.logger.debug(f"Did not find {executable} in {path}")
                return False
        self.logger.debug(f"Found all executables in {path}")
        return True

    def executables_in_path(self):
        """Check whether the executables are found in the PATH.

        Returns
        -------
        pathlib.Path
            The path where the executables are, or None.
        """
        path = None
        for executable in self.executables:
            path = shutil.which(executable)
            if path is not None:
                path = Path(path).expanduser().resolve()
                break
        # And check that have all the executables
        if path is not None and self.have_executables(path):
            return path
        else:
            return None

    def install(self):
        """Install using a Conda environment.

        A plug-in whose code cannot be installed this way (ORCA, Gaussian,
        VASP, ... are licensed manual installations) has no
        ``environment_file``; say so instead of failing.
        """
        if self.shared_codes:
            self._use_shared_code()
            return
        if self.code_environments == "prefixed" and self.environment:
            from .naming import compute_tag
            from .policy import prefixed_environment

            self.environment = prefixed_environment(
                self.environment, compute_tag(self.root)
            )
        if self.manual_code:
            self._check_manual_code()
            return
        environment_file = self.environment_file
        if self.conda.exists(self.environment):
            # e.g. a reinstall: 'update' brings the environment up to date.
            print(f"    Using the existing Conda environment '{self.environment}'.")
            if self.torch_managed:
                self._ensure_torch(self.environment, apply_file=False)
        elif self.torch_managed:
            print(
                f"    Installing Conda environment '{self.environment}'. This "
                "may take a minute or two."
            )
            # The conda part first, then torch from the right index, then the
            # rest of the pip part on that index too.
            self.conda.create_environment(
                environment_file, name=self.environment, conda_only=True
            )
            self._ensure_torch(self.environment, apply_file=True)
        else:
            print(
                f"    Installing Conda environment '{self.environment}'. This "
                "may take a minute or two."
            )
            self.conda.create_environment(environment_file, name=self.environment)
            self._record_applied(self.environment)

        # Update the configuration file.
        self.check_exe_configuration_file()

        # Update the executable configuration file.
        self.exe_config.set_value("local", "installation", "conda")
        conda_exe = seamm_manager.find_conda()
        if conda_exe is not None:
            self.exe_config.set_value("local", "conda", conda_exe)
        self.exe_config.set_value("local", "conda-environment", self.environment)

        # Clean up the environment file
        self.exe_config.set_value("local", "modules", None)
        self.exe_config.set_value("local", "container", None)
        self.exe_config.set_value("local", "platform", None)

        self.exe_config.save()
        print("    Done!\n")

    def run(self):
        """Do what the user asks via the commandline."""
        self.options = self.parser.parse_args()

        if "method" not in self.options:
            self.parser.print_help()
        else:
            # Run the requested subcommand
            self.options.method()

    def setup_parser(self):
        """Parse the command line into the options."""

        parser = argparse.ArgumentParser()

        parser.add_argument(
            "--log-level",
            default="WARNING",
            type=str.upper,
            choices=["NOTSET", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            help=("The level of informational output, defaults to " "'%(default)s'"),
        )
        parser.add_argument(
            "--environment",
            default="seamm",
            type=str.lower,
            help="The conda environment for seamm, defaults to '%(default)s'",
        )

        subparsers = parser.add_subparsers()
        self.subparser["subparsers"] = subparsers

        # check
        self.subparser["check"] = check = subparsers.add_parser("check")
        check.add_argument(
            "-y", "--yes", action="store_true", help="Answer 'yes' to all prompts"
        )
        check.set_defaults(method=self.check)

        torch_help = (
            "For a code that needs PyTorch: the wheel build to install, e.g. cu128, "
            "cu118, cpu or default (PyPI's), instead of the one chosen from this "
            "machine's NVIDIA driver; also replaces a torch that cannot use the GPU."
        )
        # install
        self.subparser["install"] = install = subparsers.add_parser("install")
        install.add_argument("--torch-tag", metavar="TAG", help=torch_help)
        install.set_defaults(method=self.install)

        # update
        self.subparser["update"] = update = subparsers.add_parser("update")
        update.add_argument("--torch-tag", metavar="TAG", help=torch_help)
        update.set_defaults(method=self.update)

        # uninstall
        uninstall = subparsers.add_parser("uninstall")
        self.subparser["uninstall"] = uninstall
        uninstall.set_defaults(method=self.uninstall)

        # show
        self.subparser["show"] = show = subparsers.add_parser("show")
        show.set_defaults(method=self.show)

        # Parse what we know so that we can set up logging.
        tmp = parser.parse_known_args()
        self.options = tmp[0]

        # Set up the logging
        level = self.options.log_level
        logging.basicConfig(level=level)
        # Don't know why basicConfig doesn't seem to work!
        self.logger.setLevel(level)
        self.logger.info(f"Logging level is {level}")

        return parser

    def show(self):
        """Show the current installation status."""
        self.logger.debug("Entering show")

        path = self.root / self.init_file_name
        if not path.exists():
            print(f"The {self.init_file_name} file does not exist. Check can make it.")

        self.exe_config.path = path

        # See if the executables are already registered in the configuration file
        if not self.exe_config.section_exists("local"):
            print("    There is no section in the configuration file for 'local'.")
        data = self.exe_config.get_values("local")

        if "code" in data:
            print(f"    The command line:\n\t{data['code']}")
        else:
            print("!   There is no command line specified.")

        if "installation" in data:
            installation = data["installation"]
            if installation == "conda":
                if "conda-environment" in data and data["conda-environment"] != "":
                    print(
                        "    run using the Conda environment "
                        f"{data['conda-environment']}."
                    )
                    name, version = self.exe_version(data)
                    print(f"    {name} version {version}.")
                else:
                    print("!  run from an unknown Conda environment.")
            elif installation == "modules":
                if "modules" in data and data["modules"] != "":
                    print(f"    run using module(s) {data['modules']}.")
                else:
                    print("!   run using unknown modules.")
            elif installation == "local":
                pass
            else:
                print(f"!    Unknown installation method '{installation}'")
        else:
            print("!   Does not seem to be configured to run!")

    def uninstall(self):
        """Uninstall the Conda environment."""
        if self.shared_codes:
            print(
                "    This installation shares the default installation's codes; "
                "their Conda environment is left alone."
            )
            return
        # See if the executables are already registered in the configuration file
        data = self.exe_config.get_values("local")
        if "installation" in data and data["installation"] == "conda":
            if "conda-environment" in data and data["conda-environment"] != "":
                environment = data["conda-environment"]
                print(
                    f"    Uninstalling Conda environment '{environment}'. This "
                    "may take a minute or two."
                )
                self.conda.remove_environment(environment)

                # Update the configuration file.
                self.exe_config.set_value("local", "installation", None)
                self.exe_config.set_value("local", "conda", None)
                self.exe_config.set_value("local", "conda-environment", None)
                self.exe_config.set_value("local", "modules", None)
                self.exe_config.set_value("local", "container", None)
                self.exe_config.set_value("local", "platform", None)

                self.exe_config.save()
                print("    Done!\n")

    def update(self):
        """Update the installation, if possible.

        In a ``shared`` installation this only reports: the default installation
        keeps the codes up to date.
        """
        if self.shared_codes:
            self._use_shared_code()
            return
        if self.manual_code:
            # Nothing to update: the code is the user's own installation.
            self._check_manual_code()
            return
        # See if the executables are already registered in the configuration file
        data = self.exe_config.get_values("local")
        if "installation" in data and data["installation"] == "conda":
            environment = self.environment
            if "conda-environment" in data and data["conda-environment"] != "":
                environment = data["conda-environment"]
            if self._not_ours(environment):
                print(
                    f"    The Conda environment '{environment}' named in "
                    f"{self.section}.ini was not created by SEAMM, so it is left as "
                    "it is. Update it yourself, or point the .ini file at an "
                    "environment SEAMM manages."
                )
                return
            if self._unchanged_since_applied(environment):
                print(
                    f"    The Conda environment '{environment}' is up to date (the "
                    "environment file is unchanged since it was applied)."
                )
                return
            print(
                f"    Updating Conda environment '{environment}'. This may "
                "take a minute or two."
            )
            if self.torch_managed:
                if not self._ensure_torch(environment, apply_file=True):
                    return
            else:
                self.conda.update_environment(self.environment_file, name=environment)
                self._record_applied(environment)
            # Update the configuration file, just in case.
            self.exe_config.set_value("local", "installation", "conda")
            conda_exe = seamm_manager.find_conda()
            if conda_exe is not None:
                self.exe_config.set_value("local", "conda", conda_exe)
            self.exe_config.set_value("local", "conda-environment", environment)

            # Clean up the environment file
            self.exe_config.set_value("local", "modules", None)
            self.exe_config.set_value("local", "container", None)
            self.exe_config.set_value("local", "platform", None)

            self.exe_config.save()
            print("    Done!\n")
        else:
            print(
                "!   Unable to update the executables because they were not installed "
                "using Conda"
            )
