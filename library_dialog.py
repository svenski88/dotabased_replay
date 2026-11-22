"""Manage registered replay folders and playback clients."""
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from library import LIBRARY_TYPES, LibraryInMigrationRule
from migration_dialog import MigrationDialog
from startup_commands_dialog import open_startup_commands


def tree_table(parent, columns):
    region = ttk.Frame(parent)
    region.pack(fill="both", expand=True)
    tree = ttk.Treeview(region, columns=tuple(range(len(columns))), show="headings", selectmode="browse", height=5)
    for index, (label, width, stretch) in enumerate(columns):
        tree.heading(index, text=label)
        tree.column(index, width=width, minwidth=width if not stretch else 135, stretch=stretch)
    scroll = ttk.Scrollbar(region, command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    return tree


class LibraryDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app, self.store = app, app.store
        self.title("Libraries & clients")
        self.geometry("1040x650")
        self.minsize(830, 520)
        self.transient(app.root)
        self.grab_set()
        self.bind("<Escape>", lambda event: self.destroy())
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        libraries = ttk.Frame(body)
        libraries.pack(fill="both", expand=True)
        ttk.Label(libraries, text="Replay libraries", style="Section.TLabel").pack(anchor="w", pady=(0, 7))
        self.libraries = tree_table(libraries, (("Folder", 550, True), ("Type", 155, False), ("Client", 115, False)))
        actions = ttk.Frame(libraries)
        actions.pack(fill="x", pady=(7, 0))
        ttk.Button(actions, text="Add library…", command=self.edit_library).pack(side="left")
        self.edit_folder = ttk.Button(actions, text="Edit library…", command=lambda: self.edit_library(self.library_selection()))
        self.edit_folder.pack(side="left", padx=6)
        self.remove_folder = ttk.Button(actions, text="Remove library", command=self.remove_library)
        self.remove_folder.pack(side="left")
        ttk.Button(actions, text="Migration rules…", command=self.open_rules).pack(side="right")
        self.libraries.bind("<<TreeviewSelect>>", self.selection_changed)
        self.libraries.bind("<Double-1>", lambda event: self.open_selected_library() if self.libraries.identify_row(event.y) else None)
        ttk.Separator(body).pack(fill="x", pady=13)
        clients = ttk.Frame(body)
        clients.pack(fill="both", expand=True)
        ttk.Label(clients, text="Dota clients", style="Section.TLabel").pack(anchor="w", pady=(0, 7))
        self.clients = tree_table(clients, (("Client", 115, False), ("Type", 80, False),
                                           ("Patch routes", 125, False), ("Executable", 500, True)))
        actions = ttk.Frame(clients)
        actions.pack(fill="x", pady=(7, 0))
        ttk.Button(actions, text="Add installed client…", command=self.add_client).pack(side="left")
        ttk.Button(actions, text="Configure new pinned client…", command=self.configure_client).pack(side="left", padx=6)
        self.edit_profile = ttk.Button(actions, text="Edit client…", command=self.open_selected_client)
        self.edit_profile.pack(side="left")
        self.remove_profile = ttk.Button(actions, text="Remove client", command=self.remove_client)
        self.remove_profile.pack(side="left", padx=6)
        self.startup_commands = ttk.Button(actions, text="Startup commands\u2026", command=self.open_client_commands)
        self.startup_commands.pack(side="left")
        self.clients.bind("<<TreeviewSelect>>", self.selection_changed)
        self.clients.bind("<Double-1>", lambda event: self.open_selected_client() if self.clients.identify_row(event.y) else None)
        footer = ttk.Frame(body)
        footer.pack(fill="x", pady=(14, 0))
        ttk.Button(footer, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(footer, text="Scan libraries", style="Accent.TButton", command=self.scan).pack(side="right", padx=8)
        self.refresh()

    def refresh(self):
        selected_library = self.selected(self.libraries)
        selected_client = self.selected(self.clients)
        self.libraries.delete(*self.libraries.get_children())
        for item in self.store.libraries():
            self.libraries.insert("", "end", iid=str(item["id"]),
                                  values=(item["path"], LIBRARY_TYPES[item["kind"]], item["client"]))
        self.clients.delete(*self.clients.get_children())
        routes = self.store.client_routes()
        paths = self.store.client_paths()
        for name in sorted(paths, key=lambda name: (name != "modern", name.casefold())):
            series = ", ".join(sorted(key for key, value in routes.items() if value == name))
            self.clients.insert("", "end", iid=name,
                                values=(name, "Steam" if name == "modern" else "Pinned", series, paths[name] or "Choose executable"))
        for tree, name in ((self.libraries, selected_library), (self.clients, selected_client)):
            if name and tree.exists(name):
                tree.selection_set(name)
                tree.see(name)
        self.selection_changed()
        self.app.client_combo.configure(values=(self.app.client_combo["values"][0], *paths))

    @staticmethod
    def selected(tree):
        return next(iter(tree.selection()), "")

    def selection_changed(self, event=None):
        have_library = "normal" if self.selected(self.libraries) else "disabled"
        self.edit_folder.configure(state=have_library)
        self.remove_folder.configure(state=have_library)
        client = self.selected(self.clients)
        self.edit_profile.configure(state="normal" if client else "disabled")
        self.startup_commands.configure(state="normal" if client else "disabled")
        self.remove_profile.configure(state="normal" if client and client != "modern" else "disabled")

    def library_selection(self):
        chosen = self.selected(self.libraries)
        return next((row for row in self.store.libraries() if str(row["id"]) == chosen), None)

    def open_selected_library(self):
        item = self.library_selection()
        if item:
            self.edit_library(item)

    def child(self, title):
        window = tk.Toplevel(self)
        window.title(title)
        window.transient(self)
        window.bind("<Escape>", lambda event: window.destroy())
        self.watch_child(window)
        window.grab_set()
        form = ttk.Frame(window, padding=18)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        return window, form

    def watch_child(self, window, refresh=False):
        def closed(event):
            if event.widget == window and self.libraries.winfo_exists():
                self.grab_set()
                if refresh:
                    self.refresh()
        window.bind("<Destroy>", closed, add="+")

    @staticmethod
    def edit_field(form, row, label, variable):
        ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Entry(form, textvariable=variable, width=62).grid(row=row, column=1, sticky="ew", pady=4)

    def edit_library(self, item=None):
        window, form = self.child("Edit library" if item else "Add library")
        values = item or {"path": "", "client": "modern", "kind": "replays"}
        folder = tk.StringVar(window, values["path"])
        client = tk.StringVar(window, values["client"])
        kind = tk.StringVar(window, LIBRARY_TYPES[values["kind"]])
        self.edit_field(form, 0, "Folder", folder)

        def browse():
            path = filedialog.askdirectory(parent=window, initialdir=folder.get(), title="Select replay library folder")
            if path:
                folder.set(path)

        ttk.Button(form, text="Browse…", command=browse).grid(row=0, column=2, padx=(8, 0))
        for row, (label, variable, choices) in enumerate((("Type", kind, tuple(LIBRARY_TYPES.values())),
                                                        ("Client", client, tuple(self.store.client_paths()))), 1):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Combobox(form, textvariable=variable, values=choices, state="readonly", width=22).grid(row=row, column=1, sticky="w")

        def save():
            path = Path(folder.get().strip()).expanduser()
            try:
                if not folder.get().strip() or (folder.get() != values["path"] and not path.is_dir()):
                    raise ValueError("Choose an existing replay folder.")
                if not item and any(Path(row["path"]) == path.resolve() for row in self.store.libraries()):
                    raise ValueError("That folder is already registered. Select it to edit its settings.")
                role = next(key for key, value in LIBRARY_TYPES.items() if value == kind.get())
                library = self.apply_library_change(window, self.store.add_library, path, client.get(), role,
                                                    library_id=item["id"] if item else None)
            except (ValueError, OSError) as exc:
                messagebox.showerror("Cannot save library", str(exc), parent=window)
                return
            if library is None:
                return
            window.destroy()
            self.changed()
            self.libraries.selection_set(str(library))
            self.libraries.see(str(library))

        ttk.Button(form, text="Save library", style="Accent.TButton", command=save).grid(row=3, column=1, sticky="e", pady=(9, 0))
        if not item:
            browse()

    def remove_library(self):
        item = self.library_selection()
        if not item or not messagebox.askyesno("Remove library", f"Remove this folder from the replay catalog?\n\n{item['path']}\n\nReplay files will stay on disk.", parent=self):
            return
        try:
            self.apply_library_change(self, self.store.remove_library, item["id"])
        except ValueError as exc:
            messagebox.showerror("Cannot remove library", str(exc), parent=self)
            return
        self.changed()

    @staticmethod
    def apply_library_change(parent, action, *args, **kwargs):
        try:
            return action(*args, **kwargs)
        except LibraryInMigrationRule as exc:
            if messagebox.askyesno("Remove affected migration rules?", f"{exc}\n\nContinue?", parent=parent):
                return action(*args, discard_rules=True, **kwargs)

    def browse_executable(self, parent):
        return filedialog.askopenfilename(parent=parent, title="Select the installed Dota game executable", filetypes=[("Executable", "*.exe")])

    def add_client(self):
        path = self.browse_executable(self)
        if path:
            self.edit_client(path=path)

    def open_selected_client(self):
        name = self.selected(self.clients)
        if name:
            self.edit_client(name, self.store.client_paths()[name])

    def open_client_commands(self):
        client = self.selected(self.clients)
        if client:
            self.watch_child(open_startup_commands(self, self.store, client))

    def edit_client(self, client=None, path=""):
        window, form = self.child("Edit client" if client else "Add installed client")
        version = next((match[1] for parent in Path(path).parents
                        if (match := re.fullmatch(r"Dota2_([0-9]+\.[0-9]{2}[a-z]?)", parent.name, re.I))), "")
        name = tk.StringVar(window, client or version.lower())
        executable = tk.StringVar(window, path)
        routes = self.store.client_routes()
        series = tk.StringVar(window, ", ".join(sorted(key for key, value in routes.items() if value == client)))
        if client:
            ttk.Label(form, text=client, style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        else:
            self.edit_field(form, 0, "Client name", name)
        self.edit_field(form, 1, "Executable", executable)
        self.edit_field(form, 2, "Patch routes", series)
        ttk.Label(form, text="Enter patch series separated by commas, such as 7.20.", style="Muted.TLabel").grid(row=3, column=1, sticky="w")

        def browse():
            path = self.browse_executable(window)
            if path:
                executable.set(path)

        def save():
            label = name.get().strip()
            target = Path(executable.get().strip()).expanduser()
            patch_series = [value.strip() for value in series.get().split(",") if value.strip()]
            try:
                if not client and (not 0 < len(label) <= 40 or label.casefold() in {key.casefold() for key in (*self.store.client_paths(), "automatic")}):
                    raise ValueError("Choose a unique client name up to 40 characters.")
                if target.suffix.lower() != ".exe" or not target.is_file():
                    raise ValueError("Choose an existing Dota executable.")
                self.store.save_client(label, target.resolve(), patch_series)
            except (ValueError, OSError) as exc:
                messagebox.showerror("Cannot save client", str(exc), parent=window)
                return
            window.destroy()
            self.changed()
            self.clients.selection_set(label)
            self.clients.see(label)

        ttk.Button(form, text="Browse…", command=browse).grid(row=1, column=2, padx=(8, 0))
        ttk.Button(form, text="Save client", style="Accent.TButton", command=save).grid(row=4, column=1, sticky="e", pady=(9, 0))

    def configure_client(self):
        def installed(path):
            name = path.parents[3].name.removeprefix("Dota2_")
            series = [key for key, value in self.store.client_routes().items() if value == name]
            self.store.save_client(name, path, series)
            self.changed()
            self.clients.selection_set(name)
            self.clients.see(name)

        self.watch_child(self.app.install_client_dialog(self, installed))

    def remove_client(self):
        name = self.selected(self.clients)
        if not name or not messagebox.askyesno("Remove client", f"Remove {name} from the app? Its installed files will stay on disk.", parent=self):
            return
        try:
            self.store.remove_client(name)
        except ValueError as exc:
            messagebox.showerror("Cannot remove client", str(exc), parent=self)
            return
        self.changed()

    def open_rules(self):
        selected = self.library_selection()
        client = selected["client"] if selected else (self.selected(self.clients) or "modern")
        window = MigrationDialog(self, self.app, client=client)
        self.watch_child(window, refresh=True)

    def changed(self):
        self.refresh()
        self.app.reload()

    def scan(self):
        self.destroy()
        self.app.scan()
