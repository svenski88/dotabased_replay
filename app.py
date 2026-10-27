"""DotaBased Replay desktop application. Standard-library runtime only."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import webbrowser
from branding import apply_window_icon, brand_root, set_windows_identity

from library import DEFAULT_CLIENTS, Store, filter_matches, format_size, launch, note_preview, presence
from delete_dialog import DeleteDialog
from deletion import delete_files, make_delete_plan
from notes_import import DEFAULT_NOTES, import_notes
from opendota import OpenDota
from replay_grid import ReplayGrid
from local_parser import LocalParser
from parse_progress import ParseProgress, ParseProgressWindow
from search import SearchIndex

BG = "#10151d"
PANEL = "#18212c"
FG = "#e6edf5"
MUTED = "#96a7ba"
ACCENT = "#58d1bc"
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
        header = ttk.Frame(self.root, padding=(22, 16, 22, 10))
        header.pack(fill="x")
        self.brand_mark = tk.PhotoImage(master=self.root, file=str(brand_root() / "replay-mark-48.png"))
        ttk.Label(header, image=self.brand_mark).pack(side="left", padx=(0, 10))
        ttk.Label(header, text="DotaBased / Replay", style="Brand.TLabel").pack(side="left")
        ttk.Button(header, text="Libraries & clients", command=self.settings).pack(side="right", padx=(8, 0))
        self.scan_button = ttk.Button(header, text="Rescan library", style="Accent.TButton", command=self.scan)
        self.scan_button.pack(side="right")
        ttk.Button(header, text="Import notes…", command=self.import_match_notes).pack(side="right", padx=8)
        self.summary = tk.StringVar(value="Your replay collection, on your machine")
        ttk.Label(self.root, textvariable=self.summary, style="Muted.TLabel", padding=(24, 0, 24, 12)).pack(anchor="w")
        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=20)
        sidebar_outer = ttk.Frame(body, width=320)
        body.add(sidebar_outer, weight=0)
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
        body.add(content, weight=1)
        ttk.Label(sidebar, text="TRACKED ACCOUNTS", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.account_tree = self.small_tree(sidebar, ("filter", "name", "count"), ("Filter", "Nickname / name", "Games"), (46, 180, 48), height=4)
        self.account_tree.bind("<<TreeviewSelect>>", lambda event: self.account_selection(self.account_tree))
        self.account_tree.bind("<Button-1>", self.account_click)
        self.account_tree.bind("<Double-1>", lambda event: self.nickname())
        actions = ttk.Frame(sidebar)
        actions.pack(fill="x", pady=7)
        ttk.Button(actions, text="Add ID", command=self.add_account).pack(side="left")
        ttk.Button(actions, text="Nickname", command=self.nickname).pack(side="left", padx=5)
        ttk.Button(actions, text="Unpin", command=self.unpin).pack(side="left")
        self.tracked_filter = tk.BooleanVar(value=self.store.get_pref("tracked_filter", False))
        ttk.Checkbutton(sidebar, text="Only games with enabled accounts", variable=self.tracked_filter, command=self.filter_changed).pack(anchor="w", pady=(2, 12))
        ttk.Label(sidebar, text="FREQUENT PLAYERS  > 5%", style="Section.TLabel").pack(anchor="w", pady=(10, 8))
        self.suggestion_tree = self.small_tree(sidebar, ("name", "count", "percent"), ("Replay name", "Games", "%"), (172, 48, 45), height=5)
        self.suggestion_tree.bind("<<TreeviewSelect>>", lambda event: self.account_selection(self.suggestion_tree))
        self.suggestion_tree.bind("<Double-1>", lambda event: self.pin_selected())
        ttk.Button(sidebar, text="Pin selected player", command=self.pin_selected).pack(fill="x", pady=7)
        ttk.Label(sidebar, text="Presence counts unique library entries.\nUnknown recordings remain in the total.", style="Muted.TLabel", wraplength=290).pack(anchor="w")
        ttk.Separator(sidebar).pack(fill="x", pady=14)
        self.profile_label = tk.StringVar(value="Select a player to inspect their account.")
        ttk.Label(sidebar, textvariable=self.profile_label, wraplength=290).pack(anchor="w")
        ttk.Button(sidebar, text="Look up account on OpenDota", command=self.lookup_account).pack(fill="x", pady=(10, 6))
        self.avatar_button = ttk.Button(sidebar, text="Open cached avatar", command=lambda: self.open_url(self.avatar_url), state="disabled")
        self.avatar_button.pack(fill="x")
        ttk.Label(sidebar, text="Network reads happen only when requested.\nProfiles and match metadata stay cached locally.", style="Muted.TLabel", wraplength=290).pack(anchor="w", pady=12)
        controls = ttk.Frame(content)
        controls.pack(fill="x", pady=(0, 10))
        ttk.Label(controls, text="Search").pack(side="left", padx=(0, 8))
        self.search = tk.StringVar()
        entry = ttk.Entry(controls, textvariable=self.search)
        entry.pack(side="left", fill="x", expand=True)
        self.search.trace_add("write", self.search_changed)
        self.league_only = tk.BooleanVar(value=self.store.get_pref("league_only", False))
        ttk.Checkbutton(controls, text="League games", variable=self.league_only, command=self.filter_changed).pack(side="left", padx=12)
        self.hide_unknown = tk.BooleanVar(value=self.store.get_pref("hide_unknown", True))
        ttk.Checkbutton(controls, text="Hide unknown recordings", variable=self.hide_unknown, command=self.filter_changed).pack(side="left")
        ttk.Label(content, text='All terms must match · separate with spaces or commas · use "quotes" for phrases · names, nicknames, heroes and notes', style="Muted.TLabel", wraplength=800).pack(anchor="w", pady=(0, 8))
        manage = ttk.Frame(content)
        manage.pack(fill="x", pady=(0, 8))
        self.selection_summary = tk.StringVar(value="0 matches selected · Ctrl-click / Shift-click to select more")
        ttk.Label(manage, textvariable=self.selection_summary, style="Muted.TLabel").pack(side="left")
        self.delete_button = ttk.Button(manage, text="Delete selected files…", style="Danger.TButton", command=self.confirm_delete, state="disabled")
        self.delete_button.pack(side="right")
        parse_controls = ttk.Frame(content)
        parse_controls.pack(fill="x", pady=(0, 8))
        self.parse_button = ttk.Button(parse_controls, text="Parse All", command=self.parse_all)
        self.parse_button.pack(side="left")
        self.parse_selected_button = ttk.Button(parse_controls, text="Parse Selected", command=self.parse_selected)
        self.parse_selected_button.pack(side="left", padx=(6, 0))
        self.stop_parse_button = ttk.Button(parse_controls, text="Stop Parsing", command=self.local_parser.stop, state="disabled")
        self.stop_parse_button.pack(side="left", padx=6)
        ttk.Button(parse_controls, text="Parse details", command=self.parse_details).pack(side="left")
        self.parse_fraction = tk.DoubleVar(value=0)
        ttk.Progressbar(parse_controls, variable=self.parse_fraction, maximum=1, length=140).pack(side="right")
        panes = ttk.Panedwindow(content, orient="vertical")
        panes.pack(fill="both", expand=True)
        list_frame = ttk.Frame(panes)
        panes.add(list_frame, weight=3)
        columns = ("match", "rating", "date", "duration", "radiant", "dire", "winner", "size", "score", "lobby", "tracked", "notes", "league")
        self.match_tree = ReplayGrid(list_frame, columns=columns)
        for column, title, width in zip(columns, ("MATCH / FILE", "RATING", "DATE", "DURATION", "RADIANT HEROES", "DIRE HEROES", "WINNER", "SIZE TOTAL", "R : D", "LOBBY", "PINNED PLAYERS", "NOTES", "LEAGUE"), (100, 95, 85, 78, 158, 140, 65, 85, 65, 80, 110, 140, 110)):
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
        details = ttk.Frame(panes, padding=(0, 12, 0, 0))
        panes.add(details, weight=2)
        detail_header = ttk.Frame(details)
        detail_header.pack(fill="x")
        self.detail_title = tk.StringVar(value="Select a replay")
        ttk.Label(detail_header, textvariable=self.detail_title, style="Section.TLabel").pack(side="left")
        self.copy_match_id_button = ttk.Button(detail_header, text="Copy Match ID", command=self.copy_match_id, state="disabled")
        self.copy_match_id_button.pack(side="right")
        self.detail_meta = tk.StringVar()
        ttk.Label(details, textvariable=self.detail_meta, style="Muted.TLabel", wraplength=1000).pack(anchor="w", pady=5)
        lower = ttk.Frame(details)
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=1)
        lower.columnconfigure(1, weight=1)
        lower.rowconfigure(1, weight=1)
        ttk.Label(lower, text="PLAYERS / HEROES").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(lower, text="MATCH NOTES  ·  saved automatically").grid(row=0, column=1, sticky="w", pady=4, padx=(14, 0))
        player_frame = ttk.Frame(lower)
        player_frame.grid(row=1, column=0, sticky="nsew")
        self.players_text = self.text_widget(player_frame, height=6, state="disabled")
        player_scroll = ttk.Scrollbar(player_frame, orient="vertical", command=self.players_text.yview)
        player_scroll.pack(side="right", fill="y")
        self.players_text.pack(fill="both", expand=True)
        self.players_text.configure(yscrollcommand=player_scroll.set)
        note_frame = ttk.Frame(lower)
        note_frame.grid(row=1, column=1, sticky="nsew", padx=(14, 0))
        self.notes = self.text_widget(note_frame, height=6, undo=True)
        note_scroll = ttk.Scrollbar(note_frame, orient="vertical", command=self.notes.yview)
        note_scroll.pack(side="right", fill="y")
        self.notes.pack(fill="both", expand=True)
        self.notes.configure(yscrollcommand=note_scroll.set)
        self.notes.bind("<FocusOut>", lambda event: self.save_notes())
        self.notes.bind("<KeyRelease>", self.note_changed)
        self.notes_timer = None
        bottom = ttk.Frame(details)
        bottom.pack(side="bottom", fill="x", pady=10, before=lower)
        ttk.Label(bottom, text="Copy:").pack(side="left")
        self.copy_choice = ttk.Combobox(bottom, state="readonly", width=34)
        self.copy_choice.pack(side="left", padx=7)
        self.copy_choice.bind("<<ComboboxSelected>>", self.copy_changed)
        self.client_choice = tk.StringVar(value="Library default")
        self.client_combo = ttk.Combobox(bottom, textvariable=self.client_choice, values=("Library default", "modern", "classic"), state="readonly", width=14)
        self.client_combo.pack(side="left", padx=(0, 7))
        self.client_combo.bind("<<ComboboxSelected>>", self.override_client)
        ttk.Button(bottom, text="Watch replay", style="Accent.TButton", command=self.watch).pack(side="left")
        self.copy_size = tk.StringVar()
        ttk.Label(bottom, textvariable=self.copy_size, style="Muted.TLabel").pack(side="left", padx=9)
        links = ttk.Frame(details)
        links.pack(side="bottom", fill="x", pady=(0, 5), before=bottom)
        ttk.Button(links, text="OpenDota ↗", command=lambda: self.match_link("opendota")).pack(side="left")
        ttk.Button(links, text="Dotabuff ↗", command=lambda: self.match_link("dotabuff")).pack(side="left", padx=7)
        ttk.Button(links, text="Fetch selected metadata", command=self.enrich_selected).pack(side="left", padx=(8, 0))
        ttk.Button(links, text="Enrich next 20", command=self.enrich_batch).pack(side="left", padx=7)
        ttk.Button(links, text="Stop network batch", command=self.cancel.set).pack(side="left")
        footer = ttk.Frame(self.root, padding=(22, 10))
        footer.pack(side="bottom", fill="x", before=body)
        self.status = tk.StringVar(value="Ready · offline library")
        ttk.Label(footer, textvariable=self.status, style="Muted.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="Scan details", command=self.scan_details).pack(side="right")
        self.last_report = None
        self.detail_panes = panes
        self.sidebar_canvas = sidebar_canvas
        panes.bind("<Configure>", lambda event: panes.sashpos(0, max(90, event.height - 340)))

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
        return (match.get("match_id") or Path(match["copies"][0]["path"]).name, match.get("rating", 0), when(match), duration(match), heroes[2], heroes[3], winner(match), format_size(match["total_size"]), score(match),
                LOBBIES.get(match.get("lobby_type"), "Unknown"), pinned, note_preview(match.get("notes", "")),
                match.get("league_name") or (f"League {match['league_id']}" if match.get("league_id") else "—"))

    def search_changed(self, *args):
        self.cancel_search_timer()
        self.search_timer = self.root.after(150, self.render_matches)

    def cancel_search_timer(self):
        if self.search_timer is not None:
            self.root.after_cancel(self.search_timer)
            self.search_timer = None

    def render_matches(self, save_pending=True):
        self.cancel_search_timer()
        if not hasattr(self, "match_tree"):
            return
        if save_pending:
            self.save_notes()
        self.visible = filter_matches(self.catalog, getattr(self, "account_rows", []), self.tracked_filter.get(), self.search.get(), self.league_only.get(), self.hide_unknown.get(), self.search_index)
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
            self.current_key = focused
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
        self.copy_options = match["copies"]
        self.copy_choice["values"] = [f"{copy['client']} · {Path(copy['path']).name} · {format_size(copy['size'])} [{index + 1}]" for index, copy in enumerate(self.copy_options)]
        self.copy_choice.current(0)
        self.copy_changed()
        self.client_choice.set(match.get("client_override") or "Library default")

    def clear_match(self):
        self.copy_match_id_button.configure(state="disabled")
        self.detail_title.set("Select a replay")
        self.detail_meta.set("")
        self.players_text.configure(state="normal")
        self.players_text.delete("1.0", "end")
        self.players_text.configure(state="disabled")
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.configure(state="disabled")
        self.copy_options = []
        self.copy_choice.set("")
        self.copy_size.set("")

    def copy_changed(self, event=None):
        index = self.copy_choice.current()
        self.copy_size.set(f"Selected: {format_size(self.copy_options[index]['size'])}" if 0 <= index < len(self.copy_options) else "")

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
            self.store.save_match(self.current_key, client="" if value == "Library default" else value)
            self.current_match()["client_override"] = "" if value == "Library default" else value

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
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(payload)
                elif kind == "parse_progress":
                    self.parse_progress.update(payload)
                    self.refresh_parse_window()
                    if payload.get("phase") == "scan":
                        self.status.set("Preparing offline parse · " + payload["path"])
                        continue
                    self.parse_fraction.set(self.parse_progress.fraction)
                    self.status.set(f"{self.parse_progress.fraction:.0%} batch · {payload['completed']} parsed · {payload['cached']} cached · {payload['failed']} unsuccessful · {self.parse_progress.message}")
                elif kind == "error":
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
        if not self.closed:
            self.root.after(100, self.poll)

    def scan(self):
        def complete(report):
            self.last_report = report
            self.status.set(f"Scan complete · {report['files']:,} files · {report['cached']:,} unchanged · {len(report['errors']):,} notices (Scan details)")
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

    def watch(self):
        match = self.current_match()
        index = self.copy_choice.current()
        if not match or index < 0:
            self.status.set("Select a replay copy to watch.")
            return
        copy = self.copy_options[index]
        client = match.get("client_override") or copy["client"]
        try:
            launch(self.store.get_pref("clients", DEFAULT_CLIENTS).get(client, ""), copy["path"])
            self.status.set(f"Started {client} client for {Path(copy['path']).name}.")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Cannot launch replay", str(exc), parent=self.root)

    def settings(self):
        if self.busy:
            self.status.set("Wait for the current operation before changing library folders.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Libraries & clients")
        dialog.geometry("910x560")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        ttk.Label(dialog, text="Replay folders", style="Section.TLabel").pack(anchor="w", padx=18, pady=(18, 8))
        ttk.Label(dialog, text="Each folder chooses its client. Scanning is read-only; deleting files requires a separate confirmation.", style="Muted.TLabel").pack(anchor="w", padx=18, pady=(0, 8))
        frame = ttk.Frame(dialog, padding=(18, 0))
        frame.pack(fill="both", expand=True)
        tree = self.small_tree(frame, ("path", "client"), ("Folder", "Client"), (700, 100), height=8)
        def refresh():
            tree.delete(*tree.get_children())
            for item in self.store.libraries():
                tree.insert("", "end", iid=str(item["id"]), values=(item["path"], item["client"]))
        refresh()
        row = ttk.Frame(dialog, padding=(18, 8))
        row.pack(fill="x")
        mode = tk.StringVar(value="modern")
        ttk.Combobox(row, textvariable=mode, values=("modern", "classic"), state="readonly", width=12).pack(side="left")
        def add():
            path = filedialog.askdirectory(title="Select replay folder", parent=dialog)
            if path:
                self.store.add_library(path, mode.get())
                refresh()
        def update():
            if tree.selection():
                path = tree.item(tree.selection()[0], "values")[0]
                self.store.add_library(path, mode.get())
                refresh()
        def remove():
            if tree.selection():
                self.store.remove_library(int(tree.selection()[0]))
                refresh()
                self.reload()
        ttk.Button(row, text="Add folder…", command=add).pack(side="left", padx=7)
        ttk.Button(row, text="Apply client to selected", command=update).pack(side="left")
        ttk.Button(row, text="Remove selected", command=remove).pack(side="left", padx=7)
        ttk.Label(dialog, text="Dota client executables", style="Section.TLabel").pack(anchor="w", padx=18, pady=(10, 7))
        values = {}
        clients = self.store.get_pref("clients", DEFAULT_CLIENTS)
        for client in ("modern", "classic"):
            line = ttk.Frame(dialog, padding=(18, 4))
            line.pack(fill="x")
            ttk.Label(line, text=client.title(), width=9).pack(side="left")
            value = tk.StringVar(value=clients.get(client, ""))
            values[client] = value
            ttk.Entry(line, textvariable=value).pack(side="left", fill="x", expand=True, padx=7)
            def browse(variable=value):
                selected = filedialog.askopenfilename(parent=dialog, title="Select Dota executable", filetypes=[("Executable", "*.exe")])
                if selected:
                    variable.set(selected)
            ttk.Button(line, text="Browse…", command=browse).pack(side="right")
        ttk.Label(dialog, text="Client selection follows the library, with an optional per-match override. Old-client compatibility still depends on the replay build.", style="Muted.TLabel", wraplength=850).pack(anchor="w", padx=18, pady=10)
        def save():
            self.save_notes()
            self.store.set_pref("clients", {key: value.get().strip() for key, value in values.items()})
            dialog.destroy()
            self.reload()
            self.scan()
        ttk.Button(dialog, text="Save & scan", style="Accent.TButton", command=save).pack(anchor="e", padx=18, pady=(0, 16))

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
    args = parser.parse_args()
    set_windows_identity()
    root = tk.Tk()
    app = ReplayApp(root, Store(args.database))
    if args.smoke:
        root.after(5000, app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
