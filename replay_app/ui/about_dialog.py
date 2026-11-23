"""Project links, build version, and offline attribution notices."""
import tkinter as tk
from tkinter import ttk
import webbrowser

from replay_app.build_info import display_version
from replay_app.resources import ASSETS, RESOURCE_ROOT


LINKS = (
    ("Source repository", "https://github.com/svenski88/dotabased_replay", "Source, releases, and issue reports"),
    ("DotaBASED", "https://dotabased.com/", "Dota 2 stats and draft tools"),
    ("TheWonderCow on Patreon", "https://www.patreon.com/TheWonderCow", "micro19 prediction model, included with permission"),
    ("SteamDB", "https://steamdb.info/", "Steam build and manifest references"),
    ("DepotDownloader", "https://github.com/SteamRE/DepotDownloader", "Optional pinned client downloads from Steam"),
    ("Manta", "https://github.com/dotabuff/manta", "Native replay parsing"),
    ("OpenDota", "https://www.opendota.com/", "Optional match and player enrichment"),
    ("Dotabuff", "https://www.dotabuff.com/", "Match links"),
    ("LightGBM", "https://lightgbm.readthedocs.io/", "Offline model inference"),
)

NOTICE_FILES = (
    ("Distribution notices", RESOURCE_ROOT / "third_party" / "distribution-notices.txt"),
    ("Valve hero artwork", ASSETS / "valve" / "heroes" / "LICENSE.txt"),
    ("Parser licenses", RESOURCE_ROOT / "third_party" / "parser-licenses.txt"),
    ("Inference licenses", RESOURCE_ROOT / "third_party" / "inference-licenses.txt"),
)


def dialog(parent, title):
    window = tk.Toplevel(parent)
    window.title(title)
    window.transient(parent)
    window.bind("<Escape>", lambda event: window.destroy())
    return window


def show_notices(parent):
    window = dialog(parent, "Third-party notices")
    frame = ttk.Frame(window, padding=12)
    frame.pack(fill="both", expand=True)
    tabs = ttk.Notebook(frame)
    tabs.pack(fill="both", expand=True)
    tabs.enable_traversal()
    style = ttk.Style(window)
    for title, path in NOTICE_FILES:
        panel = ttk.Frame(tabs)
        tabs.add(panel, text=title)
        content = tk.Text(panel, width=78, height=20, wrap="word", padx=8, pady=8,
                          bg=style.lookup("TEntry", "fieldbackground"), fg=style.lookup("TLabel", "foreground"))
        scrollbar = ttk.Scrollbar(panel, command=content.yview)
        content.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        content.pack(fill="both", expand=True)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            text = "This notice is unavailable in this build. See the source repository for details."
        content.insert("1.0", text)
        content.configure(state="disabled")
    ttk.Button(frame, text="Close", command=window.destroy).pack(anchor="e", pady=(8, 0))
    tabs.focus_set()
    return window


def show_about(parent):
    window = dialog(parent, "About DotaBased Replay")
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="DotaBased Replay", style="Brand.TLabel").pack(anchor="w")
    version = display_version()
    build = ttk.Frame(frame)
    build.pack(anchor="w", pady=(6, 10))
    ttk.Label(build, text=version, style="Section.TLabel").pack(side="left", padx=(0, 8))

    def copy_version():
        window.clipboard_clear()
        window.clipboard_append(version)
        copy_button.configure(text="Copied")

    copy_button = ttk.Button(build, text="Copy version", command=copy_version)
    copy_button.pack(side="left")
    ttk.Label(frame, text="A desktop library for browsing, organizing, and watching local Dota 2 replays.",
              wraplength=500).pack(anchor="w")

    links = ttk.Frame(frame)
    links.pack(fill="x", pady=10)
    for row, (label, url, description) in enumerate(LINKS):
        ttk.Button(links, text=label, style="Compact.TButton", command=lambda link=url: webbrowser.open(link)).grid(
            row=row, column=0, sticky="ew", padx=(0, 10), pady=1)
        ttk.Label(links, text=description, style="Muted.TLabel", wraplength=315).grid(row=row, column=1, sticky="w")

    for paragraph in (
        "Win probabilities are model estimates. Dota 2 hero artwork © Valve Corporation. "
        "This is an independent community project with no Valve affiliation or endorsement.",
        "Replay files and the library database stay local. Optional OpenDota lookups send requested IDs. "
        "DepotDownloader handles Steam downloads and sign-in.",
    ):
        ttk.Label(frame, text=paragraph, wraplength=500, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
    actions = ttk.Frame(frame)
    actions.pack(fill="x", pady=(4, 0))
    ttk.Button(actions, text="Third-party notices", command=lambda: show_notices(window)).pack(side="left")
    ttk.Button(actions, text="Close", command=window.destroy).pack(side="right")
    copy_button.focus_set()
    return window
