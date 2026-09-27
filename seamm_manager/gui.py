import collections.abc
import importlib
import locale
import logging
from pathlib import Path
import platform
import sys
import tkinter as tk
import tkinter.ttk as ttk

from packaging.version import Version
import Pmw
import seamm_widgets as sw

from . import apps
from . import my
from .util import (
    find_packages,
    get_metadata,
    run_plugin_installer,
)
from .services import known_services
from .install import install_packages, install_development_environment
from .uninstall import uninstall_packages
from .update import update_packages, update_development_environment

system = platform.system()
if system in ("Darwin",):
    from .mac import ServiceManager
    from .mac import create_app, delete_app, get_apps, update_app  # noqa: F401

    mgr = ServiceManager(prefix="org.molssi.seamm")
    icons = "SEAMM.icns"
elif system in ("Linux",):
    from .linux import ServiceManager
    from .linux import create_app, delete_app, get_apps, update_app  # noqa: F401

    mgr = ServiceManager(prefix="org.molssi.seamm")
    icons = "linux_icons"
else:
    raise NotImplementedError(f"SEAMM does not support services on {system} yet.")

logger = logging.getLogger(__name__)


# Make some styles for coloring labels
dk_green = "#008C00"
red = "#D20000"

# Help text
help_text = """\
The SEAMM installer handles three different aspects of installing SEAMM:
<ol>
  <li><b>Components</b> tab: Install the SEAMM components and plug-ins,</li>
  <li><b>Shortcuts</b> tab: Create application shortcuts so you can click on an icon
    to start the application, and</li>
  <li><b>Services</b> tab: Create services (or daemons) for the Dashboard and JobServer.
  </li>
</ol>
<p>
  <b>Note:</b> Finding all the available plug-ins for SEAMM and examining the
  installation might take a few minutes. Therefore, if you are only interested in
  <b>Shortcuts</b> or <b>Services</b>, do not click on the <b>Components</b> tab.
<p>
  You can install SEAMM in two ways:
  <ol>
    <li>Full installation: install all SEAMM components and any desired plug-ins. This
      allows you to run from the command-line or via the Dashboard.</li>
    <li>Only the graphical user interface (GUI). You won't be able to run locally, but
      can submit jobs to remote Dashboards or copy the flowchart to another machine and
      run manually.</li>
  </ol>
  If you create a full installation, you can have the plug-ins install any
  computational codes they need, e.g. LAMMPS, MOPAC, or DFTB+. If you already have the
  codes installed you can use your version, asking the plug-ins not to install a second
  copy.
<p>
  Detailed instructions:
<ol>
  <li>Select the SEAMM components and desired plug-ins on the <b>Components</b> tab, and
    click the appropriate button to install just the plug-in or both it and any
    computational codes.If you want only the GUI select the <i>GUI only</i>.</li>
  <li>Next, go to the <b>Shortcuts</b> tab and select the shortcuts you want.
    On the Mac the shortcuts will be in <b>~/Applications</b>, and can be dragged to the
    Dock or Desktop. On Linux, they are
    in <b>~/.local/share/applications</b>. Check the documentation for the Desktop you
    use to add them to the launcher, dash, or similar.</li>
  <li>For a full installation, go to the <b>Services</b> tab to create services for
    the Dashboard and JobServer. This keeps them running when you log out, so that
    jobs keep running and you can access the Dashboard remotely even if you are logged
    out of the machine.
    You can also stop and start the services from the <b>Services</b> tab. The Dashboard
    and JobServer use minimal resources, so there is no problem leaving them running at
    all times.
<p>
  We recommend that you run the installer every few weeks to get updates and new
  plug-ins. If you find a bug, check if there are any updates. Maybe the problem has
  already been fixed!  If not, please report it!
"""


class GUI(collections.abc.MutableMapping):
    def __init__(self, logger=logger):
        self.dbg_level = 30
        self.logger = logger
        self._widget = {}

        self.progress_dialog = None
        self.progress_bar = None
        self.cancel = False
        self._selected = {}
        self.packages = None
        self.package_data = {}
        self._gui_only = None  # Creation deferred to setup.

        self.app_data = {}
        self._selected_apps = {}

        self.service_data = {}
        self._selected_services = {}

        self.metadata = get_metadata()

        self.tabs = {}
        self.descriptions = []
        self.description_width = 0

        self.root = self.setup()

    # Provide dict like access to the widgets to make
    # the code cleaner
    def __getitem__(self, key):
        """Allow [] access to the widgets!"""
        return self._widget[key]

    def __setitem__(self, key, value):
        """Allow x[key] access to the data"""
        self._widget[key] = value

    def __delitem__(self, key):
        """Allow deletion of keys"""
        if key in self._widget:
            self._widget[key].destroy()
        del self._widget[key]

    def __iter__(self):
        """Allow iteration over the object"""
        return iter(self._widget)

    def __len__(self):
        """The len() command"""
        return len(self._widget)

    @property
    def gui_only(self):
        "Whether to install only the GUI."
        return self._gui_only.get() == 1

    @gui_only.setter
    def gui_only(self, value):
        if value:
            self._gui_only.set(1)
        else:
            self._gui_only.set(0)

    def event_loop(self):
        self.root.mainloop()

    def setup(self):
        locale.setlocale(locale.LC_ALL, "")

        root = tk.Tk()
        Pmw.initialise(root)

        app_name = "SEAMM Manager (Development)" if my.development else "SEAMM Manager"
        root.title(app_name)

        # This can't be done until the root window is created....
        self._gui_only = tk.IntVar(value=0)
        self.gui_only = self.metadata.get("gui-only", False)

        # The menus
        menu = tk.Menu(root)

        # Set the about and preferences menu items on Mac
        if sys.platform.startswith("darwin"):
            app_menu = tk.Menu(menu, name="apple")
            menu.add_cascade(menu=app_menu)

            app_menu.add_command(label="About " + app_name, command=self.about)
            app_menu.add_separator()
            root.createcommand("tk::mac::ShowPreferences", self.preferences)
            self.CmdKey = "Command-"
        else:
            self.CmdKey = "Control-"

        root.config(menu=menu)
        filemenu = tk.Menu(menu)
        debug_menu = tk.Menu(menu)
        filemenu.add_cascade(label="Debug", menu=debug_menu)
        debug_menu.add_radiobutton(
            label="normal",
            value=30,
            variable=self.dbg_level,
            command=lambda arg0=30: self.handle_dbg_level(arg0),
        )
        debug_menu.add_radiobutton(
            label="info",
            value=20,
            variable=self.dbg_level,
            command=lambda arg0=20: self.handle_dbg_level(arg0),
        )
        debug_menu.add_radiobutton(
            label="debug",
            value=10,
            variable=self.dbg_level,
            command=lambda arg0=10: self.handle_dbg_level(arg0),
        )

        # Add the notebook
        nb = self["notebook"] = ttk.Notebook(root)
        nb.grid(row=0, column=0, sticky=tk.NSEW)
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        nb.bind("<<NotebookTabChanged>>", self._tab_cb)

        # Add the help text
        page = ttk.Frame(nb)
        nb.add(page, text="Help", sticky=tk.NSEW)
        self.tabs[str(page)] = "Help"

        # Get the background color
        style = ttk.Style()
        bg = style.lookup("TLabel", "background")
        del style

        self["help"] = sw.HTMLScrolledText(
            page, html=help_text, wrap=tk.WORD, width=50, background=bg
        )
        self["help"].configure(state=tk.DISABLED)
        self["help"].grid(column=0, row=0, sticky=tk.NSEW)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)

        # Add the table for components
        page = ttk.Frame(nb)
        nb.add(page, text="Components", sticky=tk.NSEW)
        self.tabs[str(page)] = "Components"

        self["table"] = sw.ScrolledLabelFrame(page, text="SEAMM components")
        self["table"].grid(column=0, row=0, sticky=tk.NSEW)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)

        # and buttons below...
        frame = self["component buttons"] = ttk.Frame(page)
        frame.grid(column=0, row=1)

        self["refresh"] = ttk.Button(
            frame, text="Refresh available packages", command=self._refresh_cache
        )
        self["gui only"] = ttk.Checkbutton(
            frame, text="GUI only", command=self.reset_table, variable=self._gui_only
        )

        self["select all"] = ttk.Button(
            frame, text="Select all", command=self._select_all
        )
        self["clear selection"] = ttk.Button(
            frame, text="Clear selection", command=self._clear_selection
        )
        self["install"] = ttk.Button(
            frame, text="Install selected", command=self._install
        )
        self["install gui-only"] = ttk.Button(
            frame,
            text="Install selected, only GUI",
            command=lambda: self._install(gui_only=True),
        )
        self["uninstall"] = ttk.Button(
            frame, text="Uninstall selected", command=self._uninstall
        )
        self["uninstall gui-only"] = ttk.Button(
            frame, text="Uninstall selected, only GUI", command=self._uninstall
        )
        self["update"] = ttk.Button(frame, text="Update selected", command=self._update)
        self["update gui-only"] = ttk.Button(
            frame,
            text="Update selected, only GUI",
            command=lambda: self._update(gui_only=True),
        )

        # Add the apps
        page = ttk.Frame(nb)
        nb.add(page, text="Shortcuts", sticky=tk.NSEW)
        self.tabs[str(page)] = "Shortcuts"

        self["apps"] = sw.ScrolledLabelFrame(page, text="SEAMM shortcuts")
        self["apps"].grid(column=0, row=0, sticky=tk.NSEW)
        page.columnconfigure(0, weight=1)

        # and buttons below...
        frame = ttk.Frame(page)
        frame.grid(column=0, row=1)

        self["create apps"] = ttk.Button(
            frame, text="Create selected apps", command=self._create_apps
        )
        self["remove apps"] = ttk.Button(
            frame, text="Remove selected apps", command=self._remove_apps
        )

        self["create apps"].grid(row=0, column=0, sticky=tk.EW)
        self["remove apps"].grid(row=0, column=1, sticky=tk.EW)

        # Add the services
        page = ttk.Frame(nb)
        nb.add(page, text="Services", sticky=tk.NSEW)
        self.tabs[str(page)] = "Services"

        self["services"] = sw.ScrolledLabelFrame(page, text="SEAMM services")
        self["services"].grid(column=0, row=0, sticky=tk.NSEW)
        page.columnconfigure(0, weight=1)

        # and buttons below...
        frame = ttk.Frame(page)
        frame.grid(column=0, row=1)

        self["create services"] = ttk.Button(
            frame, text="Create selected services", command=self._create_services
        )
        self["remove services"] = ttk.Button(
            frame, text="Remove selected services", command=self._remove_services
        )
        self["start services"] = ttk.Button(
            frame, text="Start selected services", command=self._start_services
        )
        self["stop services"] = ttk.Button(
            frame, text="Stop selected services", command=self._stop_services
        )

        self["create services"].grid(row=0, column=0, sticky=tk.EW)
        self["remove services"].grid(row=1, column=0, sticky=tk.EW)
        self["start services"].grid(row=0, column=1, sticky=tk.EW)
        self["stop services"].grid(row=1, column=1, sticky=tk.EW)

        nb.select(0)

        # Work out and set the window size to nicely fit the screen
        ws = root.winfo_screenwidth()
        hs = root.winfo_screenheight()
        w = int(0.9 * ws)
        if w > 1500:
            w = 1500
        h = int(0.8 * hs)
        x = int((ws - w) / 2)
        y = int(0.2 * hs / 2)

        root.geometry(f"{w}x{h}+{x}+{y}")

        self.logger.debug("Finished initializing the rest of the GUI, drawing window")
        self.logger.debug("SEAMM has been drawn. Now raise it to the top")

        # bring it to the top of all windows
        root.lift()

        # Create a progress dialog
        d = self.progress_dialog = tk.Toplevel()
        d.transient(root)

        w = self.progress_bar = ttk.Progressbar(d, orient=tk.HORIZONTAL, length=400)
        w.grid(row=0, column=0, sticky=tk.NSEW)

        w = self.progress_text = ttk.Label(d, text="Progress")
        w.grid(row=1, column=0)

        w = ttk.Button(d, text="Cancel", command=self.cancel)
        # w.grid(row=2, column=0)
        w.rowconfigure(0, minsize=30)

        # Center
        w = d.winfo_reqwidth()
        h = d.winfo_reqwidth()
        x = int((ws - w) / 2)
        y = int((hs - h) / 2)

        d.geometry(f"+{x}+{y}")
        d.withdraw()

        root.update_idletasks()

        # Styles for coloring lines in table
        style = ttk.Style()
        style.configure("Green.TLabel", foreground=dk_green)
        style.configure("Red.TLabel", foreground=red)

        # root.after_idle(self.refresh)

        return root

    def cancel(self):
        print("Cancel hit!")
        self.cancel = True

    def handle_dbg_level(self, level):
        self.dbg_level = level
        logging.getLogger().setLevel(self.dbg_level)

    def about(self):
        raise NotImplementedError()

    def preferences(self):
        raise NotImplementedError()

    def refresh(self):
        """Update the table of packages."""
        self.progress_bar.configure(mode="indeterminate", value=0)
        self.progress_text.configure(
            text="Finding all packages. This may take a couple minutes."
        )
        self.progress_dialog.deiconify()
        self.root.update()
        self.progress_bar.start()

        self.packages = find_packages(
            progress=True, update=self.root.update, cache_valid=5
        )

        self.progress_bar.stop()

        n = len(self.packages)
        self.progress_bar.configure(mode="determinate", maximum=n, value=0)
        self.progress_text.configure(
            text=f"Finding which packages are installed (0 of {n})"
        )
        self.root.update()

        installed = my.uv.list()

        count = 0
        data = self.package_data = {}
        for package in self.packages:
            count += 1

            available = Version(self.packages[package]["version"])
            if package in self.packages and "description" in self.packages[package]:
                description = self.packages[package]["description"].strip()
            else:
                description = "description unavailable"

            if package not in installed:
                data[package] = [package, "--", available, description, "not installed"]
            else:
                version = Version(installed[package]["version"])
                # See if the package has an installer
                self.progress_text.configure(
                    text=f"Checking background codes for {package}."
                )
                self.root.update()

                result = run_plugin_installer(package, "show", verbose=False)
                if result is not None:
                    if result.returncode == 0:
                        for line in result.stdout.splitlines():
                            description += f"\n{line}"
                    else:
                        description += (
                            f"\nThe installer for {package} "
                            f"returned code {result.returncode}"
                        )
                        for line in result.stderr.splitlines():
                            description += f"\n    {line}"

                if version < available:
                    data[package] = [
                        package,
                        version,
                        available,
                        description,
                        "out of date",
                    ]
                else:
                    data[package] = [
                        package,
                        version,
                        available,
                        description,
                        "up to date",
                    ]

            self.progress_bar.step()
            self.progress_text.configure(
                text=f"Finding which packages are installed ({count} / {n})"
            )
            self.root.update()

        self.progress_dialog.withdraw()

    def reset_table(self):
        "Redraw the table in the GUI."

        # Sort by the plug-in names
        table = self["table"]
        frame = table.interior()

        for child in frame.grid_slaves():
            child.destroy()

        w = ttk.Label(frame, text="Version")
        w.grid(row=0, column=3, columnspan=2)

        w = ttk.Label(frame, text="Component")
        w.grid(row=1, column=1)
        w = ttk.Label(frame, text="Type")
        w.grid(row=1, column=2)
        w = ttk.Label(frame, text="Installed")
        w.grid(row=1, column=3)
        w = ttk.Label(frame, text="Available")
        w.grid(row=1, column=4)
        w = ttk.Label(frame, text="Description")
        w.grid(row=1, column=5)
        row = 2

        # Get the background color
        style = ttk.Style()
        bg = style.lookup("TLabel", "background")
        del style

        self.descriptions = []

        for ptype in ("Core package", "MolSSI plug-in", "3rd-party plug-in"):
            group = []
            for m, v, a, d, status in self.package_data.values():
                if self.gui_only and m in (
                    "seamm-dashboard",
                    "seamm-datastore",
                    "seamm-jobserver",
                ):
                    continue

                if self.packages[m]["type"] == ptype:
                    group.append([m, v, a, d, status])

            group.sort(key=lambda x: x[0])

            for m, v, a, d, status in group:
                if status == "out of date":
                    style = "Red.TLabel"
                    fg = red
                elif status == "up to date":
                    style = "Green.TLabel"
                    fg = dk_green
                else:
                    style = "TLabel"
                    fg = "black"

                if m not in self._selected:
                    self._selected[m] = tk.IntVar()
                w = ttk.Checkbutton(frame, variable=self._selected[m])
                w.grid(row=row, column=0, sticky=tk.N)
                w = ttk.Label(frame, text=m, style=style)
                w.grid(row=row, column=1, sticky="nw")
                w = ttk.Label(frame, text=str(ptype), style=style)
                w.grid(row=row, column=2, sticky=tk.N)
                w = ttk.Label(frame, text=str(v), style=style)
                w.grid(row=row, column=3, sticky=tk.N)
                w = ttk.Label(frame, text=str(a), style=style)
                w.grid(row=row, column=4, sticky=tk.N)
                w = tk.Text(frame, wrap=tk.WORD, width=50, background=bg, foreground=fg)
                w.insert("end", d.strip())
                w.grid(row=row, column=5, sticky=tk.EW)
                self.descriptions.append(w)
                row += 1

        frame.columnconfigure(5, weight=1)

        # Handle the buttons
        frame = self["component buttons"]
        for child in frame.grid_slaves():
            child.grid_forget()

        self["refresh"].grid(row=0, column=0, sticky=tk.EW)
        self["gui only"].grid(row=1, column=0, sticky=tk.EW)

        self["select all"].grid(row=0, column=2, sticky=tk.EW)
        self["clear selection"].grid(row=1, column=2, sticky=tk.EW)

        if self.gui_only:
            self["install gui-only"].grid(row=0, column=4, sticky=tk.EW)
            self["uninstall gui-only"].grid(row=1, column=4, sticky=tk.EW)

            self["update gui-only"].grid(row=0, column=6, sticky=tk.EW)
        else:
            self["install"].grid(row=0, column=4, sticky=tk.EW)
            self["uninstall"].grid(row=1, column=4, sticky=tk.EW)
            self["install gui-only"].grid(row=3, column=4, sticky=tk.EW)
            self["uninstall gui-only"].grid(row=4, column=4, sticky=tk.EW)

            self["update"].grid(row=0, column=6, sticky=tk.EW)
            self["update gui-only"].grid(row=1, column=6, sticky=tk.EW)

        frame.columnconfigure(1, minsize=15)
        frame.columnconfigure(3, minsize=15)
        frame.columnconfigure(5, minsize=15)
        frame.rowconfigure(2, minsize=15)

        self.root.update()

        # This is a kluge! the 2000 height is a reasonable guess but may be too small
        table.canvas.configure(scrollregion=(0, 0, 1287, 2000))

        # Set the heights of the descriptions
        self.description_width = {}
        for w in self.descriptions:
            w.bind("<Configure>", self._configure_text)
            n = w.count("1.0", "end", "displaylines")[0]
            w.configure(height=n, state=tk.DISABLED)
            self.description_width[w] = w.winfo_width()

    def _configure_text(self, event):
        w = event.widget
        width = w.winfo_width()
        if self.description_width[w] != width:
            n = w.count("1.0", "end", "displaylines")[0]
            w.configure(height=n)
            self.description_width[w] = width

    def _select_all(self):
        "Select all the packages."
        for var in self._selected.values():
            var.set(1)

    def _clear_selection(self):
        "Unselect all the packages."
        for var in self._selected.values():
            var.set(0)

    def _select_all_apps(self):
        "Select all the apps."
        for var in self._selected_apps.values():
            var.set(1)

    def _clear_apps_selection(self):
        "Unselect all the apps."
        for var in self._selected_apps.values():
            var.set(0)

    def _select_all_services(self):
        "Select all the services."
        for var in self._selected_services.values():
            var.set(1)

    def _clear_services_selection(self):
        "Unselect all the services."
        for var in self._selected_services.values():
            var.set(0)

    def _install(self, gui_only=False):
        "Install selected packages."
        update = True

        to_install = []
        for package, var in self._selected.items():
            if var.get() == 1:
                to_install.append(package)
        n = len(to_install)

        self.progress_bar.configure(mode="indeterminate", maximum=20, value=0)
        self.progress_text.configure(text=f"Installing/updating {n} packages")
        self.progress_dialog.deiconify()
        self.root.update()

        install_packages(
            to_install,
            update=update,
            gui_only=gui_only,
            progress=self._update_progress_step,
            update_text=self._update_progress_text,
        )

        # Fix the package list
        self._clear_selection()
        self._refresh_cache()

        if my.development:
            self.progress_text.configure(
                text="Installing/updating development packages"
            )
            self.progress_dialog.deiconify()
            self.root.update()

            install_development_environment()

        # self.progress_bar.stop()
        self.progress_dialog.withdraw()

    def _update_progress_step(self):
        self.progress_bar.step()
        self.root.update()

    def _update_progress_text(self, text):
        self.progress_text.configure(text=text)
        self.root.update()

    def _uninstall(self, gui_only=False):
        "Uninstall selected packages."
        to_uninstall = []
        for package, var in self._selected.items():
            if var.get() == 1:
                to_uninstall.append(package)
        n = len(to_uninstall)

        self.progress_bar.configure(mode="indeterminate")
        self.progress_text.configure(text=f"Uninstalling {n} packages")
        self.progress_dialog.deiconify()
        self.root.update()
        self.progress_bar.start()

        uninstall_packages(to_uninstall, gui_only=gui_only)

        # self.reset_table()
        self._clear_selection()
        self._refresh_cache()

        self.progress_bar.stop()
        self.progress_dialog.withdraw()

    def _update(self, gui_only=False):
        "Update the selected packages."
        to_update = []
        for package, var in self._selected.items():
            if var.get() == 1:
                to_update.append(package)
        n = len(to_update)

        self.progress_bar.configure(mode="indeterminate", maximum=20, value=0)
        self.progress_text.configure(text=f"Updating {n} packages")
        self.progress_dialog.deiconify()
        self.root.update()

        update_packages(
            to_update,
            gui_only=gui_only,
            progress=self._update_progress_step,
            update_text=self._update_progress_text,
        )

        self._clear_selection()
        self._refresh_cache()

        self.progress_dialog.withdraw()

        if my.development:
            # Update the development packages
            self.progress_bar.configure(mode="indeterminate", value=0)
            self.progress_text.configure(text="Updating the development environment.")
            self.root.update()
            self.progress_bar.start()

            update_development_environment()

        self._clear_selection()
        self._refresh_cache()

        self.progress_dialog.withdraw()

    def _create_apps(self, all_users=False):
        installed_apps = apps.get_apps()
        for app_lower, var in self._selected_apps.items():
            if var.get() == 1:
                app = apps.app_names[app_lower]
                app_name = f"{app}-dev" if my.development else app
                packages = my.uv.list()
                package = apps.app_package[app_lower]
                if package in packages:
                    version = str(packages[package]["version"])
                else:
                    print(
                        f"The package '{package}' needed by the shortcut {app_name} is "
                        "not installed."
                    )
                    continue
                if app_name in installed_apps:
                    continue

                data_path = importlib.resources.files("seamm_manager") / "data"
                icons_path = data_path / icons
                root = str(my.root)

                if app_lower == "dashboard":
                    bin_path = my.uv.which("seamm-dashboard")
                    create_app(
                        bin_path,
                        "--root",
                        root,
                        "--port",
                        my.options.port,
                        name=app_name,
                        version=version,
                        user_only=not all_users,
                        icons=icons_path,
                    )
                elif app_lower == "jobserver":
                    bin_path = my.uv.which(app.lower())
                    create_app(
                        bin_path,
                        "--root",
                        root,
                        name=app_name,
                        version=version,
                        user_only=not all_users,
                        icons=icons_path,
                    )
                else:
                    bin_path = my.uv.which(app.lower())
                    create_app(
                        bin_path,
                        name=app_name,
                        version=version,
                        user_only=not all_users,
                        icons=icons_path,
                    )
                if all_users:
                    print(f"\nInstalled shortcut {app_name} for all users.")
                else:
                    print(f"\nInstalled shortcut {app_name} for this user.")

        self._clear_apps_selection()
        self.refresh_apps()
        self.layout_apps()

    def _refresh_cache(self):
        """Refresh the cache of available codes and reset the GUI."""
        self.progress_bar.configure(mode="indeterminate", value=0)
        self.progress_text.configure(
            text="Finding all packages. This may take a couple minutes."
        )
        self.progress_dialog.deiconify()
        self.root.update()
        self.progress_bar.start()

        self.packages = find_packages(
            progress=True, update=self.root.update, update_cache=True
        )

        self.progress_bar.stop()

        self.refresh()
        self.reset_table()

        self.progress_dialog.withdraw()

    def _remove_apps(self):
        installed_apps = apps.get_apps()
        for app_lower, var in self._selected_apps.items():
            if var.get() == 1:
                app = apps.app_names[app_lower]
                app_name = f"{app}-dev" if my.development else app
                if app_name in installed_apps:
                    delete_app(app_name, missing_ok=True)
                    print(f"Deleted the shortcut '{app_name}'.")
                else:
                    print(f"Shortcut '{app_name}' was not installed.")
        self._clear_apps_selection()
        self.refresh_apps()
        self.layout_apps()

    def _tab_cb(self, event):
        w = self["notebook"].select()
        tab = self.tabs[w]
        if tab == "Components":
            self.refresh()
            self.reset_table()
        elif tab == "Shortcuts":
            self.refresh_apps()
            self.layout_apps()
        elif tab == "Services":
            self.refresh_services()
            self.layout_services()

    def refresh_apps(self):
        applications = get_apps()

        data = self.app_data = {}
        for app in apps.known_apps:
            app_lower = app.lower()
            app = apps.app_names[app_lower]
            app_name = f"{app}-dev" if my.development else app
            if app_name in applications:
                path = applications[app_name]
                if path.is_relative_to(Path.home()):
                    path = path.relative_to(Path.home())
                    data[app_lower] = (app_name, "~/" + str(path))
                else:
                    data[app_lower] = (app_name, str(path))
            else:
                data[app_lower] = (app_name, "not found")

    def layout_apps(self):
        "Redraw the apps table in the GUI."

        # Sort by the plug-in names
        table = self["apps"]
        frame = table.interior()

        for child in frame.grid_slaves():
            child.destroy()

        w = ttk.Label(frame, text="Shortcut")
        w.grid(row=0, column=1)
        w = ttk.Label(frame, text="Location")
        w.grid(row=0, column=2)
        row = 1
        for app_lower, tmp in self.app_data.items():
            app, location = tmp
            if location == "not found":
                style = "Red.TLabel"
            else:
                style = "Green.TLabel"

            if app_lower not in self._selected_apps:
                self._selected_apps[app_lower] = tk.IntVar()
            w = ttk.Checkbutton(frame, variable=self._selected_apps[app_lower])
            w.grid(row=row, column=0, sticky=tk.N)
            w = ttk.Label(frame, text=app, style=style)
            w.grid(row=row, column=1, sticky=tk.W)
            w = ttk.Label(frame, text=location, style=style)
            w.grid(row=row, column=2, sticky=tk.W)
            row += 1

        self.root.update()

    def refresh_services(self):
        services = mgr.list()

        data = self.service_data = {}
        for service in known_services:
            service_name = f"dev_{service}" if my.development else service

            if service_name in services:
                path = Path(mgr.file_path(service_name))
                if path.is_relative_to(Path.home()):
                    path = path.relative_to(Path.home())
                    data[service] = {"path": "~/" + str(path)}
                else:
                    data[service] = {"path": str(path)}
                status = mgr.status(service_name)
                data[service]["status"] = (
                    "running" if status["running"] else "not running"
                )
                data[service]["root"] = (
                    "---" if status["root"] is None else status["root"]
                )
                data[service]["port"] = (
                    "---" if status["port"] is None else status["port"]
                )
                data[service]["dashboard name"] = (
                    "---"
                    if status["dashboard name"] is None
                    else status["dashboard name"]
                )
            else:
                data[service] = {"status": "not found"}
            data[service]["name"] = service_name

    def layout_services(self):
        "Redraw the services table in the GUI."

        # Sort by the plug-in names
        table = self["services"]
        frame = table.interior()

        for child in frame.grid_slaves():
            child.destroy()

        w = ttk.Label(frame, text="Service")
        w.grid(row=0, column=1)
        w = ttk.Label(frame, text="Status")
        w.grid(row=0, column=2)
        w = ttk.Label(frame, text="Root")
        w.grid(row=0, column=3)
        w = ttk.Label(frame, text="Port")
        w.grid(row=0, column=4)
        w = ttk.Label(frame, text="Name")
        w.grid(row=0, column=5)
        row = 1
        for service, tmp in self.service_data.items():
            status = tmp["status"]
            if status == "not found":
                style = "Red.TLabel"
            elif status == "running":
                style = "Green.TLabel"
            else:
                style = "TLabel"

            if service not in self._selected_services:
                self._selected_services[service] = tk.IntVar()
            w = ttk.Checkbutton(frame, variable=self._selected_services[service])
            w.grid(row=row, column=0, sticky=tk.N)
            w = ttk.Label(frame, text=tmp["name"], style=style)
            w.grid(row=row, column=1, sticky=tk.W)
            w = ttk.Label(frame, text=status, style=style)
            w.grid(row=row, column=2, sticky=tk.W)
            if status != "not found":
                w = ttk.Label(frame, text=tmp["root"], style=style)
                w.grid(row=row, column=3, sticky=tk.W)
                w = ttk.Label(frame, text=tmp["port"], style=style)
                w.grid(row=row, column=4, sticky=tk.W)
                w = ttk.Label(frame, text=tmp["dashboard name"], style=style)
                w.grid(row=row, column=5, sticky=tk.W)
            row += 1

        self.root.update()

    def _create_services(self):
        port = 55155 if my.development else 55055
        root = str(my.root)
        tmp = platform.node()
        if tmp == "":
            tmp = "Dashboard"
        name = tmp + " Development" if my.development else tmp
        services = mgr.list()
        for service, var in self._selected_services.items():
            if var.get() == 1:
                if service == "dashboard":
                    port, name = self._dashboard_parameters(port, name)
                service_name = f"dev_{service}" if my.development else service
                if service_name in services:
                    if my.options.force:
                        mgr.delete(service_name)
                    else:
                        continue
                # Proceed to creating the service.
                exe_path = my.uv.which(f"seamm-{service}")
                if exe_path is None:
                    exe_path = my.uv.which(service)
                if exe_path is None:
                    print(
                        f"Could not find seamm-{service} or {service}. Is it installed?"
                    )
                    print()
                    continue

                stderr_path = Path(f"{root}/logs/{service}.out").expanduser()
                stdout_path = Path(f"{root}/logs/{service}.out").expanduser()

                if service == "dashboard":
                    mgr.create(
                        service_name,
                        exe_path,
                        "--port",
                        port,
                        "--root",
                        root,
                        "--dashboard-name",
                        name,
                        stderr_path=str(stderr_path),
                        stdout_path=str(stdout_path),
                    )
                else:
                    mgr.create(
                        service_name,
                        exe_path,
                        "--root",
                        root,
                        "JobServer",
                        "--no-windows",
                        stderr_path=str(stderr_path),
                        stdout_path=str(stdout_path),
                    )
                # And start it up
                mgr.start(service_name)
                print(f"Created and started the service {service_name}")
        self._clear_services_selection()
        self.refresh_services()
        self.layout_services()

    def _dashboard_parameters(self, port, name):
        "Let the user edit the parameters for the Dashboard service."
        dialog = Pmw.Dialog(
            self.root,
            buttons=("OK",),
            defaultbutton="OK",
            title="Dashboard Parameters",
        )
        # command=dialog.deactivate,
        dialog.withdraw()

        # Create a frame to hold everything in the dialog
        frame = ttk.Frame(dialog.interior())
        frame.pack(expand=tk.YES, fill=tk.BOTH)

        # Then create the widgets
        w_port = sw.LabeledEntry(frame, labeltext="Port:", width=50)
        w_port.set(str(port))
        w_name = sw.LabeledEntry(frame, labeltext="Name:", width=50)
        w_name.set(name)

        w_port.grid(row=0, column=0, sticky=tk.EW)
        w_name.grid(row=1, column=0, sticky=tk.EW)

        dialog.activate(geometry="centerscreenfirst")

        try:
            port = int(w_port.get())
        except Exception:
            pass
        name = w_name.get()

        dialog.destroy()

        return port, name

    def _remove_services(self):
        for service, var in self._selected_services.items():
            if var.get() == 1:
                service_name = f"dev_{service}" if my.development else service
                mgr.delete(service_name)
                print(f"The service {service_name} was deleted.")
        self._clear_services_selection()
        self.refresh_services()
        self.layout_services()

    def _start_services(self):
        for service, var in self._selected_services.items():
            if var.get() == 1:
                service_name = f"dev_{service}" if my.development else service
                if mgr.is_running(service_name):
                    print(f"The service '{service_name}' was already running.")
                else:
                    try:
                        mgr.start(service_name)
                    except (RuntimeError, NotImplementedError) as e:
                        print(e)
                    else:
                        print(f"The service '{service_name}' has been started.")
        self._clear_services_selection()
        self.refresh_services()
        self.layout_services()

    def _stop_services(self):
        for service, var in self._selected_services.items():
            if var.get() == 1:
                service_name = f"dev_{service}" if my.development else service
                if mgr.is_running(service_name):
                    try:
                        mgr.stop(service_name)
                    except (RuntimeError, NotImplementedError) as e:
                        print(e)
                    else:
                        print(f"The service '{service_name}' has been stopped.")
                else:
                    print(f"The service '{service_name}' was not running.")
        self._clear_services_selection()
        self.refresh_services()
        self.layout_services()
