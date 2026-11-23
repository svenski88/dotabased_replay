"""Desktop form for creating a pinned Dota client recipe."""

import tkinter as tk
from tkinter import filedialog, ttk

from replay_app.client_recipe import WINDOWS_DEPOTS, import_browser_capture, import_build_pages, read_server_version, save_recipe


def create_recipe_dialog(parent, on_created):
    dialog = tk.Toplevel(parent)
    dialog.title("Create Windows Dota client recipe")
    dialog.transient(parent)
    dialog.grab_set()
    frame = ttk.Frame(dialog, padding=18)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    patch, build, server_version = (tk.StringVar() for _ in range(3))
    manifests = {depot: tk.StringVar() for depot in WINDOWS_DEPOTS}
    status = tk.StringVar()
    imported_sources = []

    def field(row, label, variable, width=38):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=variable, width=width).grid(row=row, column=1, sticky="ew", padx=10)

    def import_manifests(reader, source):
        try:
            target, changes, links = reader(source, build.get().strip())
        except (OSError, ValueError) as exc:
            status.set(str(exc))
            return
        if target:
            build.set(target)
        for depot, value in manifests.items():
            value.set(changes.get(depot, ""))
        imported_sources[:] = links
        missing = [depot for depot in manifests if depot not in changes]
        detail = f" Missing depots: {', '.join(missing)}." if missing else ""
        status.set(f"Imported {len(changes)} of {len(manifests)} depot manifests.{detail}")

    def import_build():
        paths = filedialog.askopenfilenames(parent=dialog, title="Select the target SteamDB build page and any earlier build pages", filetypes=[("HTML", "*.html *.htm")])
        if paths:
            import_manifests(import_build_pages, paths)

    def import_capture():
        path = filedialog.askopenfilename(parent=dialog, title="Select DotaBased SteamDB capture", filetypes=[("JSON capture", "*.json")])
        if path:
            import_manifests(import_browser_capture, path)

    def import_version():
        path = filedialog.askopenfilename(parent=dialog, title="Select archived steam.inf for this build", filetypes=[("Steam metadata", "*.inf"), ("All files", "*.*")])
        if path:
            try:
                server_version.set(read_server_version(path))
            except (OSError, ValueError) as exc:
                status.set(str(exc))

    def close():
        dialog.destroy()
        parent.grab_set()

    def save():
        path = filedialog.asksaveasfilename(parent=dialog, title="Save client recipe", defaultextension=".json",
                                            initialfile=f"client_{patch.get().strip()}.json", filetypes=[("JSON recipe", "*.json")])
        if path:
            try:
                links = [line.strip() for line in sources.get("1.0", "end").splitlines() if line.strip()]
                save_recipe(path, patch.get().strip(), build.get().strip(), server_version.get().strip(),
                            {depot: value.get().strip() for depot, value in manifests.items()},
                            list(dict.fromkeys(imported_sources + links)))
            except (OSError, ValueError) as exc:
                status.set(str(exc))
                return
            close()
            on_created(path)

    field(0, "Gameplay patch", patch)
    field(1, "Steam Build ID", build)
    field(2, "Dota ServerVersion", server_version)
    ttk.Button(frame, text="Read steam.inf…", command=import_version).grid(row=2, column=2, sticky="w")
    ttk.Label(frame, text="Depot manifest IDs", style="Section.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 4))
    ttk.Button(frame, text="Import browser capture…", command=import_capture).grid(row=3, column=1, sticky="e", padx=7, pady=(10, 4))
    ttk.Button(frame, text="Import saved HTML…", command=import_build).grid(row=3, column=2, sticky="e", pady=(10, 4))
    for row, (depot, name) in enumerate(WINDOWS_DEPOTS.items(), 4):
        field(row, f"{name} ({depot})", manifests[depot])
    ttk.Label(frame, text="Source links (one per line)").grid(row=12, column=0, sticky="nw", pady=7)
    sources = tk.Text(frame, height=3, width=38, wrap="none", bg="#18212c", fg="#e6edf5", insertbackground="#e6edf5")
    sources.grid(row=12, column=1, columnspan=2, sticky="ew", padx=10, pady=7)
    ttk.Label(frame, text="Review the captured history and read ServerVersion from the target build's steam.inf. Check the depot history for any gaps.",
              wraplength=570).grid(row=13, column=0, columnspan=3, sticky="w")
    ttk.Label(frame, textvariable=status, wraplength=570).grid(row=14, column=0, columnspan=3, sticky="w", pady=7)
    ttk.Button(frame, text="Save recipe…", style="Accent.TButton", command=save).grid(row=15, column=2, sticky="e")
    dialog.protocol("WM_DELETE_WINDOW", close)
    dialog.bind("<Escape>", lambda event: close())
