"""DotaBased Replay desktop application. Offline parsing and timeline graphs."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import webbrowser
from replay_app.ui.branding import apply_window_icon, brand_root, set_windows_identity
from replay_app.ui.about_dialog import show_about

from replay_app.client_catalog import load_catalog, recipe_for_patch
from replay_app.client_install import install_client, load_recipe
from replay_app.ui.client_recipe_dialog import create_recipe_dialog
from replay_app.library import (COMPATIBILITY_CLIENT, Store, client_for_replay, filter_matches, format_size,
                     launch, note_preview, presence)
from replay_app.ui.delete_dialog import DeleteDialog
from replay_app.ui.library_dialog import LibraryDialog
from replay_app.deletion import delete_files, make_delete_plan
from replay_app.notes_import import DEFAULT_NOTES, import_notes
from replay_app.opendota import OpenDota
from replay_app.ui.replay_grid import ReplayGrid
from replay_app.local_parser import LocalParser
from replay_app.ui.parse_progress import ParseProgress, ParseProgressWindow
from replay_app.search import SearchIndex
from replay_app.ui.startup_commands_dialog import commands_for_client, open_startup_commands
from replay_app.chat import chat_lines
from replay_app.ui.graph_view import CollapsiblePanel, ReplayGraph
from replay_app.ui.ui_helpers import HorizontalToolbar, HoverTip
from replay_app.graphs import CATEGORIES

BG = "#10151d"
PANEL = "#18212c"
FG = "#e6edf5"
MUTED = "#96a7ba"
ACCENT = "#58d1bc"
AUTOMATIC_CLIENT = "Automatic"
LOBBIES = {0: "Normal", 1: "Practice", 2: "Tournament", 3: "Tutorial", 4: "Co-op bots", 5: "Ranked team", 6: "Ranked solo", 7: "Ranked", 8: "Solo mid", 9: "Battle Cup", 10: "Local bots"}
MODES = {1: "All Pick", 2: "Captains Mode", 3: "Random Draft", 4: "Single Draft", 5: "All Random", 16: "Captains Draft", 18: "Ability Draft", 22: "Ranked All Pick", 23: "Turbo"}


def hero_name(value):
    return (value or "Unknown hero").replace("_", " ").title()


def winner(match):
    return {2: "Radiant", 3: "Dire"}.get(match.get("winner"), "Unknown")


def when(match):
    timestamp = match.get("start_time") or match.get("end_time")
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d") if timestamp else "Unknown"
    except (ValueError, OSError, OverflowError):
        return "Unknown"


def duration_seconds(match):
    seconds = match.get("duration")
    return seconds if type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0 else None


def duration(match):
    seconds = duration_seconds(match)
    return f"{int(seconds) // 60}:{int(seconds) % 60:02}" if seconds is not None else "Unknown"


def sort_durations(matches, reverse=False):
    known = [match for match in matches if duration_seconds(match) is not None]
    unknown = [match for match in matches if duration_seconds(match) is None]
    return sorted(known, key=duration_seconds, reverse=reverse) + unknown


def score(match):
    radiant, dire = match.get("radiant_score"), match.get("dire_score")
    return f"{radiant} : {dire}" if radiant is not None and dire is not None else "Unknown"


def pinned_teams(match, labels):
    groups = {2: [], 3: [], None: []}
    for player in match.get("players", []):
        if player.get("account_id") in labels:
            team = player.get("team") if player.get("team") in (2, 3) else None
            groups[team].append(labels[player["account_id"]])
    lines = []
    for team, label in ((2, "Radiant"), (3, "Dire")):
        if groups[team]:
            if match.get("winner") in (2, 3):
                label = f"({'Win' if match['winner'] == team else 'Loss'}) {label}"
            lines.append(label + ": " + ", ".join(dict.fromkeys(groups[team])))
    if groups[None]:
        lines.append("Unknown team: " + ", ".join(dict.fromkeys(groups[None])))
    return "\n".join(lines)


class ReplayApp:
    def __init__(self, root, store):
        self.root, self.store = root, store
        self.api = OpenDota(store)
        self.events = queue.Queue()
        self.catalog = []
        self.search_index = SearchIndex([])
        self.search_timer = None
        self.visible = []
        self.current_key = None
        self.selected_account = None
        self.busy = False
        self.closed = False
        self.cancel = threading.Event()
        self.local_parser = LocalParser()
        self.parse_progress = ParseProgress()
        self.parse_window = None
        self.copy_options = []
        self.avatar_url = ""
        self.sort_column, self.sort_reverse = "match", True
        self.root.title("DotaBased Replay")
        self.window_icons = apply_window_icon(self.root)
        self.root.geometry(store.get_pref("geometry", "1540x920"))
        self.root.minsize(1100, 720)
        self.root.configure(bg=BG)
        self.style()
        self.build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.poll)
        self.reload()
        self.root.after(180, self.scan)

    def style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Brand.TLabel", font=("Segoe UI", 23, "bold"), foreground="#75c7ff")
        style.configure("Section.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("TButton", background="#253447", foreground=FG, padding=(10, 7), borderwidth=0)
        style.map("TButton", background=[("active", "#36516a"), ("disabled", "#202936")], foreground=[("disabled", "#758497")])
        style.configure("Accent.TButton", background="#23796d")
        style.map("Accent.TButton", background=[("active", "#299183")])
        style.configure("Danger.TButton", background="#833d43")
        style.map("Danger.TButton", background=[("active", "#a34c54"), ("disabled", "#202936")])
        style.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG, padding=5)
        style.configure("TCombobox", fieldbackground=PANEL, foreground=FG, background="#253447", padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)])
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=31, borderwidth=0)
        style.map("Treeview", background=[("selected", "#244c59")], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background="#233040", foreground=MUTED, padding=(5, 8), font=("Segoe UI", 9, "bold"))
        style.configure("TPanedwindow", background=BG)
        style.configure("Compact.TButton", padding=(6, 3))
        style.configure("CompactAccent.TButton", padding=(6, 3), background="#23796d")
        style.configure("CompactDanger.TButton", padding=(6, 3), background="#833d43")
        style.configure("Compact.TMenubutton", padding=(6, 3), background="#253447")
        # Clam's global map otherwise replaces fully visible/disabled bars with
        # classic grey, even when the base scrollbar background is configured.
        style.configure("TScrollbar", background="#293949", troughcolor=BG,
                        arrowcolor=MUTED, bordercolor=BG, lightcolor="#293949",
                        darkcolor="#293949", borderwidth=0)
        for option in ("background", "lightcolor", "darkcolor"):
            style.map("TScrollbar", **{option: [("disabled", "#202b38"),
                      ("pressed", "#4b6b87"), ("active", "#3b536a")]})
        style.map("TScrollbar", arrowcolor=[("disabled", "#536479"), ("active", FG)],
                  troughcolor=[("disabled", BG), ("active", BG)],
                  bordercolor=[("disabled", BG), ("active", BG)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)

    def build(self):
        header = ttk.Frame(self.root, padding=(22, 10, 22, 6))
        header.pack(fill="x")
        self.brand_mark = tk.PhotoImage(master=self.root, file=str(brand_root() / "replay-mark-48.png"))
        ttk.Label(header, image=self.brand_mark).pack(side="left", padx=(0, 10))
        ttk.Label(header, text="DotaBased / Replay", style="Brand.TLabel").pack(side="left")
        self.about_window = None
        self.about_button = ttk.Button(header, text="About…", command=self.open_about)
        self.about_button.pack(side="right", padx=(8, 0))
        ttk.Button(header, text="Libraries & clients", command=self.settings).pack(side="right", padx=(8, 0))
        self.scan_button = ttk.Button(header, text="Rescan library", style="Accent.TButton", command=self.scan)
        self.scan_button.pack(side="right")
        ttk.Button(header, text="Import notes…", command=self.import_match_notes).pack(side="right", padx=8)
        self.summary = tk.StringVar(value="Your replay collection, on your machine")
        ttk.Label(self.root, textvariable=self.summary, style="Muted.TLabel", padding=(24, 0, 24, 6)).pack(anchor="w")
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=20)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        self.accounts_panel = CollapsiblePanel(body, self.store, "accounts_panel", "PLAYERS & ACCOUNTS", 320)
        self.accounts_panel.grid(row=0, column=0, sticky="ns", padx=(0, 6))
        sidebar_outer = self.accounts_panel.content
        sidebar_canvas = tk.Canvas(sidebar_outer, width=305, bg=BG, highlightthickness=0)
        sidebar_scroll = ttk.Scrollbar(sidebar_outer, orient="vertical", command=sidebar_canvas.yview)
        sidebar_scroll.pack(side="right", fill="y")
        sidebar_canvas.pack(side="left", fill="both", expand=True)
        sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
        sidebar = ttk.Frame(sidebar_canvas, padding=(0, 0, 8, 0))
        sidebar_window = sidebar_canvas.create_window((0, 0), window=sidebar, anchor="nw")
        sidebar.bind("<Configure>", lambda event: sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all")))
        sidebar_canvas.bind("<Configure>", lambda event: sidebar_canvas.itemconfigure(sidebar_window, width=event.width))
        sidebar_canvas.bind("<MouseWheel>", lambda event: sidebar_canvas.yview_scroll(int(-event.delta / 120), "units"))
        content = ttk.Frame(body)
        content.grid(row=0, column=1, sticky="nsew")
        self.chat_panel = CollapsiblePanel(body, self.store, "chat_panel", "CHAT LOG", 360, side="right")
        self.chat_panel.grid(row=0, column=2, sticky="ns", padx=(6, 0))
        ttk.Label(sidebar, text="TRACKED ACCOUNTS", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.account_tree = self.small_tree(sidebar, ("filter", "name", "count"), ("Filter", "Nickname / name", "Games"), (46, 180, 48), height=4)
        self.account_tree.bind("<<TreeviewSelect>>", lambda event: self.account_selection(self.account_tree))
        self.account_tree.bind("<Button-1>", self.account_click)
        self.account_tree.bind("<Double-1>", lambda event: self.nickname())
        actions = ttk.Frame(sidebar)
        actions.pack(fill="x", pady=7)
        for index, (text, command) in enumerate((("Add ID", self.add_account), ("Nickname", self.nickname), ("Unpin", self.unpin))):
            actions.columnconfigure(index, weight=1)
            ttk.Button(actions, text=text, command=command, style="Compact.TButton").grid(
                row=0, column=index, sticky="ew", padx=(0, 4 if index < 2 else 0))
        self.tracked_filter = tk.BooleanVar(value=self.store.get_pref("tracked_filter", False))
        tracked_row = ttk.Frame(sidebar)
        tracked_row.pack(fill="x", pady=(2, 12))
        ttk.Checkbutton(tracked_row, variable=self.tracked_filter, command=self.filter_changed).pack(side="left")
        tracked_label = ttk.Label(tracked_row, text="Only games with enabled accounts", wraplength=175)
        tracked_label.pack(side="left", fill="x", expand=True)
        def toggle_tracked(event):
            self.tracked_filter.set(not self.tracked_filter.get())
            self.filter_changed()
        tracked_label.bind("<Button-1>", toggle_tracked)
        ttk.Label(sidebar, text="FREQUENT PLAYERS  > 5%", style="Section.TLabel").pack(anchor="w", pady=(10, 8))
        self.suggestion_tree = self.small_tree(sidebar, ("name", "count", "percent"), ("Replay name", "Games", "%"), (172, 48, 45), height=5)
        self.suggestion_tree.bind("<<TreeviewSelect>>", lambda event: self.account_selection(self.suggestion_tree))
        self.suggestion_tree.bind("<Double-1>", lambda event: self.pin_selected())
        ttk.Button(sidebar, text="Pin selected player", command=self.pin_selected).pack(fill="x", pady=7)
        ttk.Label(sidebar, text="Presence counts unique library entries.\nUnknown recordings remain in the total.", style="Muted.TLabel", wraplength=190).pack(anchor="w")
        ttk.Separator(sidebar).pack(fill="x", pady=14)
        self.profile_label = tk.StringVar(value="Select a player to inspect their account.")
        ttk.Label(sidebar, textvariable=self.profile_label, wraplength=190).pack(anchor="w")
        ttk.Button(sidebar, text="Look up account on OpenDota", command=self.lookup_account).pack(fill="x", pady=(10, 6))
        self.avatar_button = ttk.Button(sidebar, text="Open cached avatar", command=lambda: self.open_url(self.avatar_url), state="disabled")
        self.avatar_button.pack(fill="x")
        ttk.Label(sidebar, text="Network reads happen only when requested.\nProfiles and match metadata stay cached locally.", style="Muted.TLabel", wraplength=190).pack(anchor="w", pady=12)
        controls = ttk.Frame(content)
        controls.pack(fill="x", pady=(0, 5))
        ttk.Label(controls, text="Search").pack(side="left", padx=(0, 5))
        self.search = tk.StringVar()
        self.search_entry = ttk.Entry(controls, textvariable=self.search, width=1)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search.trace_add("write", self.search_changed)
        HoverTip(self.search_entry, 'All terms must match. Separate terms with spaces or commas; use "quotes" for phrases. Search names, nicknames, heroes, notes and parsed chat.')
        self.league_only = tk.BooleanVar(value=self.store.get_pref("league_only", False))
        league = ttk.Checkbutton(controls, text="League", variable=self.league_only, command=self.filter_changed)
        league.pack(side="left", padx=5)
        HoverTip(league, "Show league-detected matches only.")
        self.hide_unknown = tk.BooleanVar(value=self.store.get_pref("hide_unknown", True))
        unknown = ttk.Checkbutton(controls, text="Hide unknown", variable=self.hide_unknown, command=self.filter_changed)
        unknown.pack(side="left")
        HoverTip(unknown, "Hide recordings without usable match or player information.")
        self.category_filter = tk.StringVar(value=self.store.get_pref("category_filter", "All categories"))
        if self.category_filter.get() not in ("All categories", *CATEGORIES):
            self.category_filter.set("All categories")
        self.category_choice = ttk.Combobox(controls, textvariable=self.category_filter,
                                          values=("All categories", *CATEGORIES), state="readonly", width=15)
        self.category_choice.pack(side="left", padx=(5, 0))
        self.category_choice.bind("<<ComboboxSelected>>", lambda event: self.filter_changed())
        HoverTip(self.category_choice, "Gold first, XP fallback; independent of win estimates.\nComeback: 10% deficit for 2 minutes, then victory.\nStomp: 7.5% lead sustained by minute 10, then continued dominance.\nClose Game: 60% of the ending window within +/-5%, excluding the final minute.")
        self.selection_summary = tk.StringVar(value="0 matches selected | Ctrl-click / Shift-click to select more")
        self.parse_toolbar = HorizontalToolbar(content)
        self.parse_toolbar.pack(fill="x", pady=(0, 5))
        parse_controls = self.parse_toolbar.content
        self.parse_button = ttk.Button(parse_controls, text="Parse All", command=self.parse_all, style="Compact.TButton")
        self.parse_button.pack(side="left")
        self.parse_selected_button = ttk.Button(parse_controls, text="Parse Selected", command=self.parse_selected, style="Compact.TButton")
        self.parse_selected_button.pack(side="left", padx=(4, 0))
        self.stop_parse_button = ttk.Button(parse_controls, text="Stop", command=self.local_parser.stop, state="disabled", style="Compact.TButton")
        self.stop_parse_button.pack(side="left", padx=4)
        HoverTip(self.stop_parse_button, "Stop Parsing; completed matches remain cached.")
        self.parse_details_button = ttk.Button(parse_controls, text="Parse details", command=self.parse_details, style="Compact.TButton")
        self.parse_details_button.pack(side="left")
        self.enrich_button = ttk.Button(parse_controls, text="Enrich 1", command=self.enrich_selected, style="Compact.TButton")
        self.enrich_button.pack(side="left", padx=(6, 0))
        HoverTip(self.enrich_button, "Fetch selected match metadata from OpenDota (explicit network request).")
        self.enrich_next_button = ttk.Button(parse_controls, text="Next 20", command=self.enrich_batch, style="Compact.TButton")
        self.enrich_next_button.pack(side="left", padx=4)
        HoverTip(self.enrich_next_button, "Enrich the next 20 visible uncached matches from OpenDota.")
        self.parse_fraction = tk.DoubleVar(value=0)
        ttk.Progressbar(parse_controls, variable=self.parse_fraction, maximum=1, length=90).pack(side="left", padx=6)
        self.delete_button = ttk.Button(parse_controls, text="Delete selected files...", style="CompactDanger.TButton", command=self.confirm_delete, state="disabled")
        self.delete_button.pack(side="left", padx=(6, 0))
        HoverTip(self.delete_button, lambda: self.selection_summary.get() + "\nReview selected physical files before confirming permanent deletion.")
        panes = ttk.Panedwindow(content, orient="vertical")
        panes.pack(fill="both", expand=True)
        list_frame = ttk.Frame(panes)
        panes.add(list_frame, weight=3)
        columns = ("match", "rating", "date", "patch", "duration", "radiant", "dire", "winner", "size", "score", "lobby", "tracked", "notes", "league", "category")
        self.match_tree = ReplayGrid(list_frame, columns=columns)
        for column, title, width in zip(columns, ("MATCH / FILE", "RATING", "DATE", "PATCH", "DURATION", "RADIANT HEROES", "DIRE HEROES", "WINNER", "SIZE TOTAL", "R : D", "LOBBY", "PINNED PLAYERS", "NOTES", "LEAGUE", "CATEGORY"), (100, 95, 85, 68, 78, 158, 140, 65, 85, 65, 80, 110, 140, 110, 110)):
            self.match_tree.heading(column, text=title, command=lambda key=column: self.sort(key))
            self.match_tree.column(column, width=width)
        self.match_tree.restore_widths(self.store.get_pref("column_widths", {}))
        self.match_tree.on_column_resize = self.save_column_width
        self.match_tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(list_frame, orient="vertical", command=self.match_tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(list_frame, orient="horizontal", command=self.match_tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.match_tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.match_tree.tag_configure("league", foreground="#70d9c6")
        self.match_tree.tag_configure("unknown", foreground="#d4ad76")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        self.match_tree.bind("<<TreeviewSelect>>", self.select_match)
        self.match_tree.on_rating = self.rate_match
        self.match_tree.body.bind("<Delete>", self.confirm_delete)
        details = ttk.Frame(panes, padding=(0, 5, 0, 0))
        panes.add(details, weight=2)
        detail_header = ttk.Frame(details)
        detail_header.pack(fill="x", pady=(0, 2))
        detail_header.columnconfigure(0, weight=1)
        self.match_toolbar = HorizontalToolbar(detail_header)
        self.match_toolbar.grid(row=0, column=0, sticky="ew")
        match_controls = self.match_toolbar.content
        self.detail_title = tk.StringVar(value="Select a replay")
        ttk.Label(match_controls, textvariable=self.detail_title, style="Section.TLabel", width=24).pack(side="left")
        self.copy_match_id_button = ttk.Button(match_controls, text="Copy ID", command=self.copy_match_id, state="disabled", style="Compact.TButton")
        self.copy_match_id_button.pack(side="left", padx=(4, 2))
        HoverTip(self.copy_match_id_button, "Copy Match ID")
        self.link_buttons = {}
        for service, title in (("opendota", "OpenDota"), ("dotabuff", "Dotabuff")):
            button = ttk.Button(match_controls, text=title, command=lambda name=service: self.match_link(name),
                                style="Compact.TButton", state="disabled")
            button.pack(side="left", padx=2)
            self.link_buttons[service] = button
            HoverTip(button, f"Open this match on {title}")
        self.copy_choice = ttk.Combobox(match_controls, state="readonly", width=17)
        self.copy_choice.pack(side="left", padx=(5, 4))
        self.copy_choice.bind("<<ComboboxSelected>>", self.copy_changed)
        HoverTip(self.copy_choice, "Replay copy to watch")
        self.client_choice = tk.StringVar(value=AUTOMATIC_CLIENT)
        self.client_combo = ttk.Combobox(match_controls, textvariable=self.client_choice, values=(AUTOMATIC_CLIENT, *self.store.client_paths()), state="readonly", width=12)
        self.client_combo.pack(side="left", padx=(0, 4))
        self.client_combo.bind("<<ComboboxSelected>>", self.override_client)
        HoverTip(self.client_combo, "Automatic routing uses the patch and then the folder's client. Select a client here to override it.")
        self.copy_size = tk.StringVar()
        self.match_tools = ttk.Menubutton(match_controls, text="Match tools", style="Compact.TMenubutton")
        self.match_tools.pack(side="left", padx=4)
        self.match_tools_menu = tk.Menu(self.match_tools, tearoff=False, bg=PANEL, fg=FG, activebackground="#36516a", activeforeground=FG)
        self.match_tools.configure(menu=self.match_tools_menu)
        self.match_tools_menu.add_command(label="Stop network batch", command=self.cancel.set)
        self.watch_button = ttk.Button(detail_header, text="Watch Replay", style="CompactAccent.TButton", command=self.watch)
        self.watch_button.grid(row=0, column=2, sticky="ne", padx=(3, 0))
        self.launch_options = {}
        self.simulate_gc_down = tk.BooleanVar(master=self.root)
        self.skip_player_info = tk.BooleanVar(master=self.root)
        self.launch_options_button = ttk.Menubutton(detail_header, text="Launch options", style="Compact.TMenubutton")
        self.launch_options_button.grid(row=0, column=1, sticky="ne", padx=(5, 0))
        self.launch_options_menu = tk.Menu(self.launch_options_button, tearoff=False, bg=PANEL, fg=FG,
                                           activebackground="#36516a", activeforeground=FG,
                                           postcommand=self.prepare_launch_menu)
        self.launch_options_button.configure(menu=self.launch_options_menu)
        self.launch_options_menu.add_checkbutton(label="Simulate Game Coordinator outage", variable=self.simulate_gc_down,
                                                 command=self.save_launch_options)
        self.launch_options_menu.add_checkbutton(label="Skip pro player info download", variable=self.skip_player_info,
                                                 command=self.save_launch_options)
        self.launch_options_menu.add_separator()
        self.launch_options_menu.add_command(label="Launch client to main menu",
                                             command=lambda: self.watch(main_menu=True))
        self.launch_options_menu.add_command(label="Startup console commands\u2026",
                                             command=self.edit_startup_commands)
        self.detail_meta = tk.StringVar()
        self.copy_build = tk.StringVar()
        metadata = ttk.Frame(details)
        metadata.pack(fill="x", pady=(2, 3))
        ttk.Label(metadata, textvariable=self.copy_build, style="Muted.TLabel").pack(side="right", padx=(8, 0))
        ttk.Label(metadata, textvariable=self.detail_meta, style="Muted.TLabel", width=1).pack(side="left", fill="x", expand=True)
        lower = ttk.Frame(details)
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=1)
        lower.columnconfigure(1, weight=1)
        lower.columnconfigure(2, weight=2)
        lower.rowconfigure(1, weight=1)
        self.player_heading = ttk.Label(lower, text="PLAYERS / HEROES")
        self.player_heading.grid(row=0, column=0, sticky="w", pady=4)
        self.notes_heading = ttk.Label(lower, text="NOTES · autosaved")
        self.notes_heading.grid(row=0, column=1, sticky="w", pady=4, padx=(14, 0))
        player_frame = ttk.Frame(lower)
        player_frame.grid(row=1, column=0, sticky="nsew")
        self.players_text = self.text_widget(player_frame, width=1, height=6, state="disabled")
        player_scroll = ttk.Scrollbar(player_frame, orient="vertical", command=self.players_text.yview)
        player_scroll.pack(side="right", fill="y")
        self.players_text.pack(fill="both", expand=True)
        self.players_text.configure(yscrollcommand=player_scroll.set)
        note_frame = ttk.Frame(lower)
        note_frame.grid(row=1, column=1, sticky="nsew", padx=(14, 0))
        self.notes = self.text_widget(note_frame, width=1, height=6, undo=True)
        note_scroll = ttk.Scrollbar(note_frame, orient="vertical", command=self.notes.yview)
        note_scroll.pack(side="right", fill="y")
        self.notes.pack(fill="both", expand=True)
        self.notes.configure(yscrollcommand=note_scroll.set)
        self.notes.bind("<FocusOut>", lambda event: self.save_notes())
        self.notes.bind("<KeyRelease>", self.note_changed)
        self.notes_timer = None
        self.graph_heading = ttk.Label(lower, text="MATCH GRAPH")
        self.graph_heading.grid(row=0, column=2, sticky="w", pady=4, padx=(14, 0))
        self.graph_view = ReplayGraph(lower, self.match_tree.icons)
        self.graph_view.grid(row=1, column=2, sticky="nsew", padx=(14, 0))
        self.graph_selection = None
        self.lower_width_mode = None
        def lower_layout(event):
            narrow = event.width < 820
            if narrow == self.lower_width_mode:
                return
            self.lower_width_mode = narrow
            if narrow:
                lower.columnconfigure(0, weight=1)
                lower.columnconfigure(1, weight=2)
                lower.columnconfigure(2, weight=0)
                lower.rowconfigure(3, weight=1)
                self.notes_heading.grid_configure(row=2, column=0, padx=0)
                note_frame.grid_configure(row=3, column=0, padx=0)
                self.graph_heading.grid_configure(row=0, column=1)
                self.graph_view.grid_configure(row=1, column=1, rowspan=3)
            else:
                lower.columnconfigure(0, weight=1)
                lower.columnconfigure(1, weight=1)
                lower.columnconfigure(2, weight=2)
                lower.rowconfigure(3, weight=0)
                self.notes_heading.grid_configure(row=0, column=1, padx=(14, 0))
                note_frame.grid_configure(row=1, column=1, padx=(14, 0))
                self.graph_heading.grid_configure(row=0, column=2)
                self.graph_view.grid_configure(row=1, column=2, rowspan=1)
        lower.bind("<Configure>", lower_layout)
        chat_frame = ttk.Frame(self.chat_panel.content)
        chat_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.chat_text = self.text_widget(chat_frame, width=1, height=6, state="disabled")
        chat_scroll = ttk.Scrollbar(chat_frame, orient="vertical", command=self.chat_text.yview)
        chat_scroll.pack(side="right", fill="y")
        self.chat_text.pack(fill="both", expand=True)
        self.chat_text.configure(yscrollcommand=chat_scroll.set)
        footer = ttk.Frame(self.root, padding=(22, 6))
        footer.pack(side="bottom", fill="x", before=body)
        self.status = tk.StringVar(value="Ready · offline library")
        ttk.Label(footer, textvariable=self.status, style="Muted.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="Scan details", command=self.scan_details).pack(side="right")
        ttk.Label(footer, textvariable=self.selection_summary, style="Muted.TLabel").pack(side="right", padx=10)
        self.last_report = None
        self.detail_panes = panes
        self.sidebar_canvas = sidebar_canvas
        fraction = self.store.get_pref("detail_split", .52)
        self.split_fraction = fraction if type(fraction) in (int, float) and .15 <= fraction <= .85 else .52
        self.pane_height = 0
        panes.bind("<Configure>", self.layout_details)
        panes.bind("<ButtonRelease-1>", self.save_detail_split, add=True)

    def layout_details(self, event):
        if event.height != self.pane_height:
            self.pane_height = event.height
            height = event.height
            self.detail_panes.sashpos(0, max(90, min(height-290, int(height*self.split_fraction))))

    def save_detail_split(self, event=None):
        height = self.detail_panes.winfo_height()
        if height > 0:
            self.split_fraction = max(.15, min(.85, self.detail_panes.sashpos(0)/height))
            self.store.set_pref("detail_split", self.split_fraction)

    def text_widget(self, parent, **kwargs):
        return tk.Text(parent, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", padx=10, pady=7, font=("Segoe UI", 10), wrap="word", **kwargs)

    def small_tree(self, parent, columns, labels, widths, height):
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse", height=height)
        for key, label, width in zip(columns, labels, widths):
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=35, stretch=key == "name")
        tree.pack(fill="x")
        return tree

    def reload(self):
        self.save_notes()
        self.catalog = self.store.catalog()
        self.account_rows = self.store.accounts()
        self.search_index = SearchIndex(self.catalog, self.account_rows)
        self.suggestions = presence(self.catalog)
        counts = {row["id"]: row["count"] for row in self.suggestions}
        all_counts = {}
        for match in self.catalog:
            for account in {p.get("account_id") for p in match.get("players", []) if p.get("account_id")}:
                all_counts[account] = all_counts.get(account, 0) + 1
        names = {p["account_id"]: p.get("name", "") for m in self.catalog for p in m.get("players", []) if p.get("account_id")}
        self.account_labels = {}
        self.account_tree.delete(*self.account_tree.get_children())
        for account in self.account_rows:
            cached = self.store.cached(f"players/{account['id']}", include_stale=True)
            profile = (cached or {}).get("data") or {}
            label = account["nickname"] or (profile.get("profile") or {}).get("personaname") or names.get(account["id"]) or str(account["id"])
            self.account_labels[account["id"]] = label
            self.account_tree.insert("", "end", iid=str(account["id"]), values=("☑" if account["enabled"] else "☐", label, all_counts.get(account["id"], 0)))
        self.suggestion_tree.delete(*self.suggestion_tree.get_children())
        for account in self.suggestions:
            self.suggestion_tree.insert("", "end", iid=str(account["id"]), values=(account["name"] or str(account["id"]), counts[account["id"]], f"{100 * account['fraction']:.1f}"))
        self.render_matches(save_pending=False)
        self.show_account()

    def match_values(self, match):
        pinned = pinned_teams(match, self.account_labels)
        heroes = {team: ", ".join(hero_name(p.get("hero")) for p in match.get("players", []) if p.get("team") == team) for team in (2, 3)}
        patch = ("" if match.get("patch_verified") else "~") + match["patch"] if match.get("patch") else "—"
        return (match.get("match_id") or Path(match["copies"][0]["path"]).name, match.get("rating", 0), when(match), patch, duration(match), heroes[2], heroes[3], winner(match), format_size(match["total_size"]), score(match),
                LOBBIES.get(match.get("lobby_type"), "Unknown"), pinned, note_preview(match.get("notes", "")),
                match.get("league_name") or (f"League {match['league_id']}" if match.get("league_id") else "—"), match.get("category", "Not parsed"))

    def search_changed(self, *args):
        self.cancel_search_timer()
        self.search_timer = self.root.after(150, self.render_matches)

    def cancel_search_timer(self):
        if self.search_timer is not None:
            self.root.after_cancel(self.search_timer)
            self.search_timer = None

    def render_matches(self, save_pending=True, refresh_details=True):
        self.cancel_search_timer()
        if not hasattr(self, "match_tree"):
            return
        if save_pending:
            self.save_notes()
        self.visible = filter_matches(self.catalog, getattr(self, "account_rows", []), self.tracked_filter.get(), self.search.get(), self.league_only.get(), self.hide_unknown.get(), self.search_index, self.category_filter.get())
        index = list(self.match_tree["columns"]).index(self.sort_column)
        def sort_value(match):
            if self.sort_column == "match":
                return int(match.get("match_id") or 0)
            if self.sort_column == "size":
                return match["total_size"]
            if self.sort_column == "rating":
                return match.get("rating", 0)
            return str(self.match_values(match)[index]).casefold()
        if self.sort_column == "duration":
            self.visible = sort_durations(self.visible, reverse=self.sort_reverse)
        elif self.sort_column == "patch":
            known = [match for match in self.visible if match.get("patch")]
            self.visible = sorted(known, key=lambda match: match["patch"], reverse=self.sort_reverse) + [
                match for match in self.visible if not match.get("patch")]
        else:
            self.visible.sort(key=sort_value, reverse=self.sort_reverse)
        selected = self.match_tree.selection()
        focused = self.match_tree.focus() or self.current_key
        self.match_tree.delete(*self.match_tree.get_children())
        for match in self.visible:
            teams = {team: [player.get("hero", "") for player in match.get("players", []) if player.get("team") == team] for team in (2, 3)}
            self.match_tree.insert("", "end", iid=match["key"], values=self.match_values(match), heroes=teams, tags=("unknown",) if not match.get("players") else (("league",) if match.get("league_id") else ()))
        self.summary.set(f"{len(self.catalog):,} library entries  ·  {sum(len(m['copies']) for m in self.catalog):,} files  ·  {sum(bool(m.get('league_id')) for m in self.catalog):,} league matches  ·  {len(self.visible):,} shown")
        remaining = [key for key in selected if self.match_tree.exists(key)]
        focused = focused if focused and self.match_tree.exists(focused) else next(iter(remaining), None)
        self.match_tree.selection_set(remaining, focus=focused)
        if focused:
            changed = focused != self.current_key
            self.current_key = focused
            if refresh_details or changed:
                self.show_match(next(m for m in self.visible if m["key"] == focused))
        else:
            self.current_key = None
            self.clear_match()
        self.update_selection_status()

    def sort(self, column):
        self.sort_reverse = not self.sort_reverse if self.sort_column == column else False
        self.sort_column = column
        self.render_matches()

    def save_column_width(self, column, width):
        self.store.set_pref("column_widths", {key: self.match_tree.definitions[key]["width"] for key in ("tracked", "notes", "league") if key in self.match_tree.explicit_widths})

    def filter_changed(self):
        self.store.set_pref("tracked_filter", self.tracked_filter.get())
        self.store.set_pref("league_only", self.league_only.get())
        self.store.set_pref("hide_unknown", self.hide_unknown.get())
        self.store.set_pref("category_filter", self.category_filter.get())
        self.render_matches()

    def current_match(self):
        return next((match for match in self.catalog if match["key"] == self.current_key), None)

    def select_match(self, event=None):
        self.update_selection_status()
        focused = self.match_tree.focus()
        if not focused or focused == self.current_key:
            return
        self.save_notes()
        match = next((m for m in self.catalog if m["key"] == focused), None)
        if match:
            self.current_key = match["key"]
            self.show_match(match)

    def show_match(self, match):
        for button in self.link_buttons.values():
            button.configure(state="normal" if match.get("match_id") else "disabled")
        self.copy_match_id_button.configure(state="normal" if match.get("match_id") else "disabled")
        self.detail_title.set(f"Match {match.get('match_id') or 'unknown'}   ·   {winner(match)} victory" if match.get("winner") in (2, 3) else f"Replay {Path(match['copies'][0]['path']).name}   ·   outcome unknown")
        self.detail_meta.set(f"{when(match)}  ·  {duration(match)}  ·  {MODES.get(match.get('game_mode'), 'Mode unknown')}  ·  Score {score(match)}  ·  {len(match['copies'])} local {'copy' if len(match['copies']) == 1 else 'copies'} ({format_size(match['total_size'])} total)  ·  {'Full local parse' if match.get('local_complete') else 'Replay + cached API' if match.get('api_cached') else 'Replay summary only'}" + ("\n" + "; ".join(dict.fromkeys(match["errors"])) if match["errors"] else ""))
        lines = []
        for team in (2, 3, None):
            players = [p for p in match.get("players", []) if (p.get("team") if p.get("team") in (2, 3) else None) == team]
            if players:
                lines.append({2: "RADIANT", 3: "DIRE", None: "OTHER / UNKNOWN TEAM"}[team])
                for player in players:
                    name = self.account_labels.get(player.get("account_id"), player.get("name") or "Unknown")
                    pin = "★ " if player.get("account_id") in self.account_labels else ""
                    lines.append(f"{pin}{hero_name(player.get('hero'))}  ·  {name}  ·  ID {player.get('account_id') or 'hidden / bot'}")
                lines.append("")
        self.players_text.configure(state="normal")
        self.players_text.delete("1.0", "end")
        self.players_text.insert("1.0", "\n".join(lines) or "No players available in replay summary.\nIf this file has a known match ID, request API metadata.")
        self.players_text.configure(state="disabled")
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", match.get("notes", ""))
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", "end")
        self.chat_text.insert("1.0", chat_lines(match))
        self.chat_text.yview_moveto(0)
        self.chat_text.configure(state="disabled")
        self.copy_options = match["copies"]
        self.copy_choice["values"] = [f"{copy['client']} · {Path(copy['path']).name} · {format_size(copy['size'])} [{index + 1}]" for index, copy in enumerate(self.copy_options)]
        self.copy_choice.current(0)
        self.copy_changed()
        self.client_choice.set(match.get("client_override") or AUTOMATIC_CLIENT)

    def clear_match(self):
        for button in self.link_buttons.values():
            button.configure(state="disabled")
        self.copy_match_id_button.configure(state="disabled")
        self.detail_title.set("Select a replay")
        self.detail_meta.set("")
        self.players_text.configure(state="normal")
        self.players_text.delete("1.0", "end")
        self.players_text.configure(state="disabled")
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.configure(state="disabled")
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", "end")
        self.chat_text.configure(state="disabled")
        self.copy_options = []
        self.graph_selection = None
        self.graph_view.set_graph(None)
        self.copy_choice.set("")
        self.copy_size.set("")
        self.copy_build.set("")

    def copy_changed(self, event=None):
        index = self.copy_choice.current()
        copy = self.copy_options[index] if 0 <= index < len(self.copy_options) else None
        self.copy_size.set(f"Selected: {format_size(copy['size'])}" if copy else "")
        versions = []
        if copy and copy.get("dota_version"):
            versions.append(f"Dota v{copy['dota_version']}")
        if copy and copy.get("replay_build"):
            versions.append(f"Replay build {copy['replay_build']}")
        self.copy_build.set("  ·  ".join(versions))
        match = self.current_match()
        if match:
            path = copy["path"] if copy else None
            summary = match.get("graph_summary", {})
            selection = (match["key"], path, summary.get("updated"))
            if selection != self.graph_selection:
                graph = self.store.graph_for_match(match, path)
                explanation = summary.get("category", {}).get("explanation", "")
                self.graph_view.set_graph(graph, explanation)
                self.graph_selection = selection

    def update_selection_status(self):
        count = len(self.match_tree.selection())
        self.selection_summary.set(f"{count} {'match' if count == 1 else 'matches'} selected · Ctrl-click / Shift-click to select more")
        self.delete_button.configure(state="normal" if count and not self.busy else "disabled")

    def rate_match(self, key, rating):
        self.save_notes()
        self.store.save_match(key, rating=rating)
        match = next((match for match in self.catalog if match["key"] == key), None)
        if match:
            match["rating"] = rating
            self.match_tree.update_values(key, self.match_values(match))
        if self.sort_column == "rating":
            self.render_matches()
        self.status.set(f"Personal rating saved: {rating}/5 · press 0–5 while the replay grid is focused to rate")

    def confirm_delete(self, event=None):
        if self.busy:
            self.status.set("Wait for the current operation before deleting replay files.")
            return "break"
        keys = self.match_tree.selection()
        if not keys:
            return "break"
        self.save_notes()
        plan = make_delete_plan(self.store, keys)
        approved = DeleteDialog(self.root, plan).show()
        if approved is None:
            self.status.set("Replay deletion cancelled; no files were changed.")
            return "break"
        self.run_job("Deleting only the confirmed replay files…", lambda: delete_files(self.store, approved, confirmed=True), self.deletion_complete)
        return "break"

    def deletion_complete(self, report):
        self.status.set(f"Deleted {len(report['deleted'])} files · {len(report['missing'])} already missing · {len(report['failed'])} failures · notes and ratings retained")
        if report["failed"]:
            dialog = tk.Toplevel(self.root)
            dialog.title("Replay deletion results")
            dialog.geometry("850x480")
            text = self.text_widget(dialog)
            text.pack(fill="both", expand=True, padx=12, pady=12)
            text.insert("1.0", json.dumps(report, indent=2))
            text.configure(state="disabled")

    def note_changed(self, event=None):
        if self.notes_timer:
            self.root.after_cancel(self.notes_timer)
        self.notes_timer = self.root.after(500, self.save_notes)

    def save_notes(self):
        if not self.current_key or not hasattr(self, "notes"):
            return
        match = self.current_match()
        if match:
            notes = self.notes.get("1.0", "end-1c")
            if notes != match.get("notes", ""):
                self.store.save_match(self.current_key, notes=notes)
                match["notes"] = notes
                self.match_tree.update_values(self.current_key, self.match_values(match))

    def override_client(self, event=None):
        if self.current_key:
            value = self.client_choice.get()
            override = "" if value == AUTOMATIC_CLIENT else value
            self.store.save_match(self.current_key, client=override)
            self.current_match()["client_override"] = override

    def account_click(self, event):
        if self.account_tree.identify_column(event.x) == "#1":
            iid = self.account_tree.identify_row(event.y)
            if iid:
                account = next(a for a in self.account_rows if a["id"] == int(iid))
                self.store.pin(account["id"], account["nickname"], not account["enabled"])
                self.selected_account = account["id"]
                self.reload()
                return "break"

    def account_selection(self, tree):
        selection = tree.selection()
        if selection:
            self.selected_account = int(selection[0])
            self.show_account()

    def show_account(self):
        self.avatar_url = ""
        if self.selected_account:
            cached = self.store.cached(f"players/{self.selected_account}", include_stale=True)
            profile = (((cached or {}).get("data") or {}).get("profile") or {})
            self.avatar_url = profile.get("avatarfull") or profile.get("avatar") or ""
            self.profile_label.set(f"Account {self.selected_account}\n{profile.get('personaname') or self.account_labels.get(self.selected_account, 'No cached profile')}" + ("\nAvatar metadata cached" if self.avatar_url else ""))
        self.avatar_button.configure(state="normal" if self.avatar_url else "disabled")

    def add_account(self):
        value = simpledialog.askstring("Track account", "Dota account ID (32-bit numeric ID):", parent=self.root)
        if value:
            try:
                self.store.pin(value)
                self.selected_account = int(value)
                self.reload()
            except ValueError as exc:
                messagebox.showerror("Invalid account", str(exc), parent=self.root)

    def pin_selected(self):
        if self.selected_account:
            if self.selected_account not in {a["id"] for a in self.account_rows}:
                self.store.pin(self.selected_account)
                self.reload()
        else:
            self.status.set("Select a frequent player or use Add ID.")

    def nickname(self):
        if not self.selected_account:
            return
        account = next((a for a in self.account_rows if a["id"] == self.selected_account), None)
        value = simpledialog.askstring("Player nickname", f"Local nickname for account {self.selected_account}:", initialvalue=account["nickname"] if account else "", parent=self.root)
        if value is not None:
            self.store.pin(self.selected_account, value, account["enabled"] if account else True)
            self.reload()

    def unpin(self):
        if self.selected_account:
            self.store.unpin(self.selected_account)
            self.reload()

    def run_job(self, title, function, callback):
        if self.busy:
            self.status.set("Wait for the current scan or lookup, or stop the network batch.")
            return
        self.busy = True
        self.parse_button.configure(state="disabled")
        self.parse_selected_button.configure(state="disabled")
        self.update_selection_status()
        self.cancel.clear()
        self.scan_button.configure(state="disabled")
        self.status.set(title)
        def worker():
            try:
                self.events.put(("done", (callback, function())))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        parsed_paths = set()
        catalog_changed = False
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(payload)
                elif kind == "parse_progress":
                    self.parse_progress.update(payload)
                    self.refresh_parse_window()
                    if payload.get("phase") == "batch":
                        catalog_changed = True
                    if payload.get("status") in ("completed", "cached", "failed", "incomplete"):
                        catalog_changed = True
                        parsed_paths.add(payload.get("path"))
                    if payload.get("phase") == "scan":
                        self.status.set("Preparing offline parse · " + payload["path"])
                        continue
                    self.parse_fraction.set(self.parse_progress.fraction)
                    self.status.set(f"{self.parse_progress.fraction:.0%} batch · {payload['completed']} parsed · {payload['cached']} cached · {payload['failed']} unsuccessful · {self.parse_progress.message}")
                elif kind == "error":
                    catalog_changed = False  # The full reload below includes queued results.
                    self.busy = False
                    self.parse_button.configure(state="normal")
                    self.parse_selected_button.configure(state="normal")
                    self.stop_parse_button.configure(state="disabled")
                    self.scan_button.configure(state="normal")
                    self.reload()
                    self.status.set(payload)
                    if self.parse_progress.active:
                        self.parse_progress.finish(error=payload)
                        self.refresh_parse_window()
                    messagebox.showerror("Operation stopped", payload, parent=self.root)
                else:
                    catalog_changed = False
                    self.busy = False
                    self.parse_button.configure(state="normal")
                    self.parse_selected_button.configure(state="normal")
                    self.stop_parse_button.configure(state="disabled")
                    self.scan_button.configure(state="normal")
                    callback, value = payload
                    self.reload()
                    callback(value)
        except queue.Empty:
            pass
        if catalog_changed:
            self.refresh_parsed_matches(parsed_paths)
        if not self.closed:
            self.root.after(100, self.poll)

    def refresh_parsed_matches(self, paths):
        """Publish committed results once per UI poll, never on helper progress ticks."""
        self.save_notes()
        match = self.current_match()
        selected_path = next((copy["path"] for index, copy in enumerate(self.copy_options)
                              if index == self.copy_choice.current()), None)
        refresh_details = bool(match and any(copy["path"] in paths for copy in match["copies"]))
        previous = {match["key"]: match for match in self.catalog}
        self.catalog = [previous[match["key"]] if previous.get(match["key"]) == match else match
                        for match in self.store.catalog()]
        self.search_index.refresh(self.catalog)
        if refresh_details:
            self.graph_selection = None
        self.render_matches(save_pending=False, refresh_details=refresh_details)
        if refresh_details and selected_path:
            for index, copy in enumerate(self.copy_options):
                if copy["path"] == selected_path:
                    self.copy_choice.current(index)
                    self.copy_changed()
                    break

    def scan(self):
        def complete(report):
            self.last_report = report
            self.status.set(f"Scan complete · {report['files']:,} files · {report['cached']:,} unchanged · {report.get('recovered', 0):,} parse caches recovered · {len(report['errors']):,} notices (Scan details)")
        self.run_job("Scanning replay folders locally…", lambda: self.store.scan(lambda text: self.events.put(("progress", text)), self.cancel.is_set), complete)

    def parse_all(self):
        self.start_parse()

    def parse_selected(self):
        keys = set(self.match_tree.selection())
        matches = [match for match in self.catalog if match["key"] in keys]
        if not matches:
            self.status.set("Select one or more matches in the grid, then click Parse Selected.")
            return
        self.start_parse(matches)

    def start_parse(self, matches=None):
        if self.busy:
            self.status.set("Wait for the current operation before parsing.")
            return
        self.local_parser.reset()  # Clear before thread start; an immediate Stop must survive.
        self.parse_fraction.set(0)
        self.parse_progress.start(matches)
        self.refresh_parse_window()
        self.stop_parse_button.configure(state="normal")
        def complete(report):
            self.parse_progress.finish(report)
            self.parse_fraction.set(self.parse_progress.fraction)
            self.refresh_parse_window()
            self.status.set(f"Parsing {'stopped' if report['cancelled'] else 'complete'} · {report['completed']} completed · {report['cached']} cached · {report['failed']} failed · completed results saved locally")
        title = "Parsing all library recordings offline…" if matches is None else f"Parsing {len(matches)} selected matches offline…"
        self.run_job(title, lambda: self.local_parser.parse_all(self.store, lambda event: self.events.put(("parse_progress", event)), matches=matches), complete)

    def parse_details(self):
        if self.parse_window and self.parse_window.winfo_exists():
            self.parse_window.lift()
            return
        if not self.parse_progress.session:
            self.parse_progress.load_history(self.store.catalog())
        self.parse_window = ParseProgressWindow(self.root, self.parse_progress, self.local_parser.stop)

    def refresh_parse_window(self):
        if self.parse_window and self.parse_window.winfo_exists():
            self.parse_window.refresh()

    def scan_details(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Scan details")
        dialog.configure(bg=BG)
        dialog.geometry("820x500")
        content = self.text_widget(dialog)
        content.pack(fill="both", expand=True, padx=14, pady=14)
        content.insert("1.0", json.dumps(self.last_report, indent=2) if self.last_report else "No scan completed this session.")
        content.configure(state="disabled")

    def lookup_account(self):
        if not self.selected_account:
            self.status.set("Select an account first.")
            return
        account = self.selected_account
        self.run_job(f"Looking up account {account}…", lambda: self.api.fetch(f"players/{account}"), lambda data: self.status.set(f"Profile cached for account {account}; avatar metadata available in the sidebar."))

    def import_match_notes(self):
        if self.busy:
            self.status.set("Wait for the current operation before importing notes.")
            return
        path = filedialog.askopenfilename(parent=self.root, title="Import per-match notes from a local text/Markdown file", initialdir=str(DEFAULT_NOTES.parent), filetypes=[("Notes files", "*.md *.txt"), ("All files", "*.*")])
        if path:
            self.save_notes()
            def complete(report):
                self.status.set(f"Imported {report['changed']} match notes · {report['empty']} bare links skipped · {report['already_imported']} already imported" + (" · database backup saved" if report["backup"] else ""))
            self.run_job("Importing local match notes…", lambda: import_notes(self.store, path, apply=True), complete)

    def enrich_selected(self):
        match = self.current_match()
        if not match or not match.get("match_id"):
            self.status.set("Select a replay with a known match ID.")
            return
        match_id = match["match_id"]
        self.run_job(f"Fetching match {match_id}…", lambda: self.api.fetch(f"matches/{match_id}"), lambda data: self.status.set(f"Match {match_id} metadata cached locally."))

    def enrich_batch(self):
        targets = [match["match_id"] for match in self.visible if match.get("match_id") and not self.store.cached(f"matches/{match['match_id']}")][:20]
        if not targets:
            self.status.set("All visible known matches already have cached API results.")
            return
        def work():
            return self.api.enrich(targets, self.cancel.is_set, lambda done, total, match_id: self.events.put(("progress", f"Enriching {done + 1}/{total} · match {match_id} (maximum 20 per batch)…")))
        self.run_job(f"Enriching up to {len(targets)} visible matches…", work, lambda result: self.status.set(f"Enriched {result['completed']} matches; {result['unavailable']} unavailable. Results cached locally."))

    def copy_match_id(self):
        match = self.current_match()
        if not match or not match.get("match_id"):
            self.status.set("Select a replay with a known match ID to copy.")
            return
        match_id = str(match["match_id"])
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(match_id)
        except tk.TclError:
            self.status.set("Could not access the clipboard. Try Copy Match ID again.")
            return
        self.status.set(f"Match ID {match_id} copied to clipboard.")

    def match_link(self, site):
        match = self.current_match()
        if match and match.get("match_id"):
            self.open_url(f"https://www.{site}.com/matches/{match['match_id']}")

    def open_url(self, url):
        if url.startswith(("https://", "http://")):
            webbrowser.open(url)

    def selected_replay_client(self):
        match = self.current_match()
        index = self.copy_choice.current()
        if match and 0 <= index < len(self.copy_options):
            copy = self.copy_options[index]
            return client_for_replay(match, copy, self.store.client_routes()), copy
        return None

    def options_for_client(self, client):
        return self.launch_options.get(client, (client != "modern", client in ("7.31d", "7.32e")))

    def prepare_launch_menu(self):
        selected = self.selected_replay_client()
        for index in (0, 1, 3, 4):
            self.launch_options_menu.entryconfigure(index, state="normal" if selected else "disabled")
        simulate_gc_down, skip_player_info = self.options_for_client(selected[0]) if selected else (False, False)
        self.simulate_gc_down.set(simulate_gc_down)
        self.skip_player_info.set(skip_player_info)

    def save_launch_options(self):
        selected = self.selected_replay_client()
        if selected:
            self.launch_options[selected[0]] = self.simulate_gc_down.get(), self.skip_player_info.get()

    def edit_startup_commands(self):
        selected = self.selected_replay_client()
        if not selected:
            return
        client, _ = selected
        open_startup_commands(self.root, self.store, client)

    def watch(self, *, main_menu=False):
        selected = self.selected_replay_client()
        if not selected:
            self.status.set("Select a replay copy to choose a client." if main_menu else "Select a replay copy to watch.")
            return
        client, copy = selected
        try:
            executable = self.store.client_paths().get(client)
            if not executable or not Path(executable).is_file():
                raise ValueError(f"Configure the {client} executable in Libraries & clients, or select a different client for this match.")
            previous = getattr(self, "replay_process", None)
            if previous is not None and previous.poll() is None:
                raise ValueError("Close the running replay client before launching another client.")
            simulate_gc_down, skip_player_info = self.options_for_client(client)
            self.replay_process = launch(executable, None if main_menu else copy["path"],
                                         pinned=client not in ("modern", "classic", "6.88f"),
                                         skip_player_info=skip_player_info, simulate_gc_down=simulate_gc_down,
                                         console_commands=commands_for_client(self.store, client))
            if main_menu:
                self.status.set(f"Started {client} client at the main menu.")
            else:
                self.status.set(f"Started {client} client for {Path(copy['path']).name}.")
            self.root.after(4000, self.check_replay_start, self.replay_process, client, main_menu)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Cannot launch client" if main_menu else "Cannot launch replay", str(exc), parent=self.root)

    def check_replay_start(self, process, client, main_menu=False):
        code = process.poll()
        if self.replay_process is process and code is not None:
            startup = "startup" if main_menu else "replay startup"
            self.status.set(f"{client} exited during {startup} (exit code {code}). Check the client console log.")

    def settings(self):
        if self.busy:
            self.status.set("Wait for the current operation before changing libraries or clients.")
            return
        LibraryDialog(self)

    def install_client_dialog(self, parent, on_installed):
        dialog = tk.Toplevel(parent)
        dialog.title("Install pinned Dota client")
        dialog.transient(parent)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        try:
            catalog = load_catalog()
            catalog_error = ""
        except (OSError, ValueError) as exc:
            catalog = {"recipes": {}, "series": {}}
            catalog_error = f"Catalog unavailable. Import or create a recipe. {exc}"
        versions = (*sorted(catalog["recipes"], reverse=True), *(f"{key} series" for key in sorted(catalog["series"], reverse=True)))
        patch = tk.StringVar(value="7.20e" if "7.20e" in versions else (versions[0] if versions else ""))
        recipe_info = tk.StringVar()
        custom = None
        ttk.Label(frame, text="Gameplay patch").grid(row=0, column=0, sticky="w")
        patch_box = ttk.Combobox(frame, textvariable=patch, values=versions, width=18)
        patch_box.grid(row=0, column=1, sticky="w", padx=7)
        ttk.Label(frame, textvariable=recipe_info, wraplength=520).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 8))

        def describe(recipe):
            recipe_info.set(f"{recipe['patch']} · Steam build {recipe.get('steam_build', 'unspecified')} · Dota version {recipe['server_version']}")

        def select_patch(*args):
            nonlocal custom
            custom = None
            recipe = recipe_for_patch(catalog, patch.get())
            if recipe:
                describe(recipe)
            else:
                recipe_info.set(catalog_error or "No catalog entry for that patch. Import or create a recipe.")

        patch.trace_add("write", select_patch)
        select_patch()

        def select_file(path):
            nonlocal custom
            try:
                recipe = load_recipe(path)
            except (OSError, ValueError) as exc:
                patch.set("")
                recipe_info.set(str(exc))
                return
            patch.set(recipe["patch"])
            custom = recipe
            describe(recipe)

        def import_recipe():
            path = filedialog.askopenfilename(parent=dialog, filetypes=[("JSON recipe", "*.json")])
            if path:
                select_file(path)

        import_button = ttk.Button(frame, text="Import recipe…", command=import_recipe)
        import_button.grid(row=0, column=2, sticky="e")
        location = tk.StringVar(value=str(self.store.pinned_client_parent()))
        downloader = tk.StringVar(value=self.store.get_pref("depot_downloader", "") or shutil.which("DepotDownloader") or "")
        qr = tk.BooleanVar(value=False)
        suppress_prompt = tk.BooleanVar(value=True)
        for row, (label, variable, filetypes) in enumerate((
                ("Install parent folder", location, None),
                ("DepotDownloader executable", downloader, [("Executable", "*.exe")])), 2):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Entry(frame, textvariable=variable, width=55).grid(row=row, column=1, sticky="ew", padx=7)

            def choose(value=variable, kinds=filetypes):
                selected = (filedialog.askopenfilename(parent=dialog, filetypes=kinds) if kinds else
                            filedialog.askdirectory(parent=dialog, initialdir=value.get()))
                if selected:
                    value.set(selected)

            ttk.Button(frame, text="Browse…", command=choose).grid(row=row, column=2)
        ttk.Checkbutton(frame, text="Sign in to Steam with QR code", variable=qr).grid(row=4, column=1, sticky="w")
        create_button = ttk.Button(frame, text="Create recipe…", command=lambda: create_recipe_dialog(dialog, select_file))
        create_button.grid(row=4, column=0, sticky="w")
        ttk.Button(frame, text="Get DepotDownloader", command=lambda: webbrowser.open("https://github.com/SteamRE/DepotDownloader/releases")).grid(row=4, column=2, sticky="e")
        ttk.Checkbutton(frame, text="Suppress the pinned client's update prompt", variable=suppress_prompt).grid(row=5, column=1, sticky="w")
        status = tk.StringVar(value="The recipe installs into its own versioned subfolder. The download may take several minutes.")
        ttk.Label(frame, textvariable=status, wraplength=520).grid(row=6, column=0, columnspan=3, sticky="w", pady=10)
        results = queue.Queue()
        running = False

        def finish():
            nonlocal running
            try:
                path, error = results.get_nowait()
            except queue.Empty:
                dialog.after(200, finish)
                return
            running = False
            if error:
                status.set(error)
                set_running(False)
                return
            self.store.set_pref("pinned_client_parent", str(path.parents[4]))
            on_installed(path)
            dialog.destroy()

        def set_running(value):
            nonlocal running
            running = value
            for control in (button, patch_box, import_button, create_button):
                control.configure(state="disabled" if value else "normal")

        def start():
            recipe = custom or recipe_for_patch(catalog, patch.get())
            values = (location.get().strip(), downloader.get().strip())
            if not recipe or not all(values):
                status.set("Choose a recipe, install folder and DepotDownloader executable.")
                return
            use_qr = qr.get()
            hide_prompt = suppress_prompt.get()
            self.store.set_pref("depot_downloader", str(Path(values[1]).resolve()))
            set_running(True)
            status.set("Downloading pinned client…" + (" Scan the QR code in the Steam console." if use_qr else ""))

            def worker():
                try:
                    results.put((install_client(recipe, *values, qr=use_qr, suppress_update_prompt=hide_prompt), None))
                except (OSError, ValueError) as exc:
                    results.put((None, str(exc)))

            threading.Thread(target=worker).start()
            dialog.after(200, finish)

        dialog.protocol("WM_DELETE_WINDOW", lambda: None if running else dialog.destroy())
        button = ttk.Button(frame, text="Install client", style="Accent.TButton", command=start)
        button.grid(row=7, column=2, sticky="e")
        return dialog

    def open_about(self):
        if self.about_window is None or not self.about_window.winfo_exists():
            self.about_window = show_about(self.root)
        else:
            self.about_window.lift()
        return self.about_window

    def close(self):
        self.cancel_search_timer()
        self.save_notes()
        self.store.set_pref("geometry", self.root.geometry())
        self.cancel.set()
        self.local_parser.close()
        self.closed = True
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Browse local Dota 2 replays")
    parser.add_argument("--database", type=Path, help="Override the local SQLite database path")
    parser.add_argument("--smoke", action="store_true", help="Open, scan and close after five seconds for UI verification")
    parser.add_argument("--smoke-model", action="store_true", help="Developer-only offline bundled inference verification")
    args = parser.parse_args()
    if args.smoke_model:
        from replay_app.graphs import Micro19
        probabilities = Micro19().predict([[10000]*10+[50000, 50000, 0, 0, 0, 0, 0, 0, 0]])
        if not math.isclose(probabilities[0], .5222032224852916, abs_tol=1e-12):
            raise RuntimeError("Bundled inference failed golden prediction verification")
        return
    set_windows_identity()
    root = tk.Tk()
    app = ReplayApp(root, Store(args.database))
    if args.smoke:
        about = app.open_about()
        root.update_idletasks()
        about.destroy()
        root.after(5000, app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
