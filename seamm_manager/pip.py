# -*- coding: utf-8 -*-
import logging
import pprint
import re
import subprocess

import requests

logger = logging.getLogger(__name__)

# Regular expressions for pypi query results.
SNIPPET_RE = re.compile(r"<a class=\"package-snippet\".*>")
NAME_RE = re.compile(r"<span class=\"package-snippet__name\">(.+)</span>")
VERSION_RE = re.compile(r".*<span class=\"package-snippet__version\">(.+)</span>")
DESCRIPTION_RE = re.compile(r".*<p class=\"package-snippet__description\">(.+)</p>")
NEXT_RE = re.compile(
    r'<a href="/search/.*page=(.+)" ' 'class="button button-group__button">Next</a>'
)


class Pip(object):
    """
    Class for handling pip

    Attributes
    ----------

    """

    def __init__(self):
        logger.debug("Creating Pip {str(type(self))}")

        self._base_url = "https://pypi.org/search/"

    def install(self, package):
        """Install the requested package.

        Parameters
        ----------
        package : str
            The package of interest.
        """
        if isinstance(package, list):
            packages = " ".join(package)
            command = f"pip install {packages}"
        else:
            command = f"pip install {package}"
        try:
            subprocess.check_output(
                command, shell=True, text=True, stderr=subprocess.STDOUT
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"Calling pip, returncode = {e.returncode}")
            logger.warning(f"Output: {e.output}")
            raise

    def list(self, outdated=False, uptodate=False):
        """List the installed packages.

        Parameters
        ----------
        outdated: bool
            If true, list only the outdated packages. Cannot be used with
            `uptodate`.
        uptodate: bool
            If true, list only the up-to-date packages. Cannot be used with
            `outdated`.
        """
        command = "pip list"
        if outdated:
            if uptodate:
                raise ValueError("May only use one of 'outdated' and 'uptodate'.")
            command += " --outdated"
        elif uptodate:
            command += " --uptodate"
        try:
            output = subprocess.check_output(
                command, shell=True, text=True, stderr=subprocess.STDOUT
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"Calling pip, returncode = {e.returncode}")
            logger.warning(f"Output: {e.output}")
            raise

        result = {}
        for line in output.splitlines():
            package, version = line.split()
            result[package] = version
        return result

    def search(
        self,
        query=None,
        framework=None,
        exact=False,
        progress=False,
        newline=True,
        update=None,
    ):
        """Search PyPi for packages.

        Parameters
        ----------
        query : str
            The text of the query, if any.
        framework : str
            The framework classifier, if any.
        exact : bool = False
            Whether to only return the exact match, defaults to False.
        progress : bool = False
            Whether to show progress dots.
        newline : bool = True
            Whether to print a newline at the end if showing progress
        update : None or method
            Method to call to e.g. update a progress bar

        Returns
        -------
        [str]
            A list of packages matching the query.
        """
        # Can not have exact match if no query term
        if query is None:
            exact = False

        # Set up the arguments for the http get
        args = {"q": query}
        if framework is not None:
            args["c"] = f"Framework::{framework}"

        logger.debug(f"search query: {args}")

        # PyPi serves up the results one page at a time, so loop
        if progress:
            count = 0
        result = {}
        while True:
            response = requests.get(self._base_url, params=args)
            logger.log(5, f"response: {response.text}")

            snippets = SNIPPET_RE.split(response.text)

            for snippet in snippets:
                name = NAME_RE.findall(snippet)
                version = VERSION_RE.findall(snippet)
                description = DESCRIPTION_RE.findall(snippet)

                # Ignore any snippets without data, e.g. the first one.
                if len(name) > 0:
                    if not exact or name[0] == query:
                        if len(version) == 0:
                            version = None
                        else:
                            version = version[0]
                        if len(description) == 0:
                            description = "no description given"
                        else:
                            description = description[0]
                        result[name[0]] = {
                            "channel": "pypi",
                            "version": version,
                            "description": description,
                        }

                        if exact:
                            break

            if progress:
                if update is None:
                    count += 1
                    if count <= 50:
                        print(".", end="", flush=True)
                    else:
                        count = 1
                        print("\n.", end="", flush=True)
                else:
                    update()
            # See if there is a next page
            next_page = NEXT_RE.findall(snippet)
            if len(next_page) == 0:
                break
            else:
                args["page"] = next_page[0]

        if progress and newline and count > 0:
            if update is None:
                print("", flush=True)

        logger.debug(f"Package information:\n{pprint.pformat(result)}")

        return result

    def show(self, package):
        """Return the information for an installed package.

        Parameters
        ----------
        package : str
            The package of interest.
        """
        command = f"pip show {package}"
        try:
            result = subprocess.check_output(
                command, shell=True, text=True, stderr=subprocess.STDOUT
            )
        except subprocess.CalledProcessError as e:
            if "Package(s) not found:" in e.output:
                result = ""
            else:
                logger.warning(f"Calling pip, returncode = {e.returncode}")
                logger.warning(f"Output: {e.output}")
                raise

        data = {}
        for line in result.splitlines():
            key, value = line.split(":", maxsplit=1)
            key = key.lower()
            value = value.strip()
            if "require" in key:
                value = [x.strip() for x in value.split(",")]
            if key == "version":
                data[key] = value
            else:
                data[key] = value

        logger.debug(f"{command}\n{pprint.pformat(data)}")

        return data

    def uninstall(self, package):
        """Remove the requested packages.

        Parameters
        ----------
        package : str or [str]
            The package of interest.
        """
        if isinstance(package, str):
            command = f"pip uninstall --yes '{package}'"
        else:
            packages = "', '".join(package)
            command = f"pip uninstall --yes '{packages}'"
        try:
            output = subprocess.check_output(
                command, shell=True, text=True, stderr=subprocess.STDOUT
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"Calling pip, returncode = {e.returncode}")
            logger.warning(f"Output: {e.output}")
            raise
        logger.debug("pip uninstall -->")
        logger.debug(output)

    def update(self, package):
        """Update the requested package.

        Parameters
        ----------
        package : str
            The package of interest.
        """
        if isinstance(package, list):
            packages = " ".join(package)
            command = f"pip install --upgrade {packages}"
        else:
            command = f"pip install --upgrade {package}"
        try:
            subprocess.check_output(
                command, shell=True, text=True, stderr=subprocess.STDOUT
            )
        except subprocess.CalledProcessError as e:
            line = e.output.splitlines()[-1]
            if "FileNotFoundError" in line:
                logger.warning(f"Pip returned a warning: {line}")
            else:
                logger.warning(f"Calling pip, returncode = {e.returncode}")
                logger.warning(f"Output: {e.output}")
                raise
