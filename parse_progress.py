"""Session progress and friendly per-recording results for offline parsing."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk

BG, FG, MUTED = "#18212c", "#e6edf5", "#96a7ba"
LOBBIES = {0: "Normal", 1: "Practice", 2: "Tournament", 3: "Tutorial", 4: "Co-op bots", 5: "Ranked team", 6: "Ranked solo", 7: "Ranked", 8: "Solo mid", 9: "Battle Cup", 10: "Local bots"}


def elapsed(value):
    if value is None:
        return "Unknown"
    return f"{int(value) // 60}:{int(value) % 60:02}"


def final_score(fields):
    radiant, dire = fields.get("radiant_score"), fields.get("dire_score")
    return f"{radiant} : {dire}" if radiant is not None and dire is not None else "Unknown"


class ParseProgress:
    def __init__(self):
        self.session = False
        self.active = False
        self.rows = {}
        self.counts = dict(total=0, completed=0, cached=0, failed=0)
        self.message = "No full parses yet. Select matches and use Parse Selected, or use Parse All."
        self.fraction = 0

    def queue(self, matches):
        self.rows = {str(match["key"]): {"match": match.get("match_id") or Path(match["copies"][0]["path"]).name,
                     "path": match["copies"][0]["path"], "status": "queued", "fraction": 0,
                     "fields": {}, "provenance": {}, "attempts": []} for match in matches}
        self.counts["total"] = len(self.rows)

    def start(self, matches=None):
        self.session = self.active = True
        self.rows = {}
        self.counts = dict(total=0, completed=0, cached=0, failed=0)
        self.fraction = 0
        self.message = "Refreshing local catalog…" if matches is None else "Preparing selected matches…"
        if matches is not None:
            self.queue(matches)

    def update(self, event):
        for key in self.counts:
            if key in event:
                self.counts[key] = event[key]
        if event.get("phase") == "scan":
            self.message = event["path"]
            return
        if event.get("phase") == "batch":
            self.queue(event["matches"])
            self.message = f"Parsing {len(self.rows)} matches offline"
            return
        row = self.rows.get(str(event.get("key")))
        if row is not None:
            if event.get("path"):
                row["path"] = event["path"]
            if "status" in event:
                row["status"] = event["status"]
            if "fraction" in event:
                row["fraction"] = max(0, min(1, event["fraction"]))
            if "error" in event:
                row["attempts"].append((event["path"], event["status"], event["error"]))
            result = event.get("result")
            if result:
                row.update(fields=result.get("fields", {}), provenance=result.get("provenance", {}), version=result.get("helper_version", ""))
            # Helper progress has no status, so it preserves the current copy state.
            self.message = f"Match {row['match']} · {row['status']} · {Path(row['path']).name}"
        done = sum(self.counts[key] for key in ("completed", "cached", "failed"))
        partial = row.get("fraction", 0) if row and row["status"] == "parsing" else 0
        self.fraction = min(1, (done + partial) / max(1, self.counts["total"]))

    def finish(self, report=None, error=None):
        self.active = False
        if report:
            self.counts.update({key: report[key] for key in self.counts})
        stopped = error or (report and report.get("cancelled"))
        self.message = str(error) if error else "Parsing stopped. Completed results remain saved." if stopped else "Parsing complete. Results saved locally."
        for row in self.rows.values():
            if row["status"] in ("queued", "parsing"):
                row["status"] = "not processed" if stopped else "unknown"
        done = sum(self.counts[key] for key in ("completed", "cached", "failed"))
        self.fraction = min(1, done / max(1, self.counts["total"]))

    def load_history(self, matches):
        self.rows = {}
        for match in matches:
            results, attempts = match.get("local_results", []), match.get("parse_attempts", [])
            if not results and not attempts:
                continue
            latest = max(results + attempts, key=lambda value: value.get("updated", 0))
            self.rows[str(match["key"])] = {"match": match.get("match_id") or Path(latest["path"]).name,
                "path": latest["path"], "status": "saved" if latest in results else latest["status"],
                "fraction": 1 if latest in results else 0, "fields": latest.get("fields", {}),
                "provenance": latest.get("provenance", {}), "version": latest.get("version", ""),
                "attempts": [(attempt["path"], attempt["status"], attempt["error"]) for attempt in attempts]}
        self.message = f"Saved local parse history · {len(self.rows)} matches" if self.rows else self.message


def match_details(row):
    fields = row.get("fields", {})
    lines = [f"Match {row['match']} · {row['status'].title()}", f"File: {row['path']}"]
    if row.get("version"):
        lines.append(f"Parser: {row['version']}")
    if fields:
        lines += ["", f"Score (Radiant : Dire): {final_score(fields)}", f"Game duration: {elapsed(fields.get('duration'))}",
                  f"Winner: { {2: 'Radiant', 3: 'Dire'}.get(fields.get('winner'), 'Unknown')}",
                  f"Lobby type: {LOBBIES.get(fields.get('lobby_type'), 'Unknown')}", f"League ID: {fields.get('league_id') or 'None recorded'}"]
        players = fields.get("players", [])
        for team, label in ((2, "Radiant"), (3, "Dire"), (None, "Unknown team")):
            team_players = [player for player in players if (player.get("team") if player.get("team") in (2, 3) else None) == team]
            if team_players:
                lines += ["", label + " players:"]
                for player in team_players:
                    lines.append(f"  {player.get('name') or player.get('account_id') or 'Unknown player'} · {player.get('hero') or 'Unknown hero'} · account {player.get('account_id') or 'unknown'}")
        if row.get("provenance"):
            lines += ["", "Recorded field sources:"] + [f"  {name.replace('_', ' ').title()}: {source}" for name, source in row["provenance"].items()]
    else:
        lines += ["", "No completed local metadata for this attempt yet."]
    if row.get("attempts"):
        lines += ["", "Copy attempts:"]
        lines += [f"  {Path(path).name} · {status}: {error}" for path, status, error in row["attempts"]]
    return "\n".join(lines)


class ParseProgressWindow(tk.Toplevel):
    def __init__(self, root, model, stop):
        super().__init__(root)
        self.model = model
        self.title("Parser progress and match details")
        self.geometry("1000x650")
        self.minsize(720, 480)
        self.configure(bg=BG)
        self.summary = tk.StringVar()
        self.message = tk.StringVar()
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, textvariable=self.summary).pack(anchor="w")
        ttk.Label(top, textvariable=self.message, wraplength=900).pack(anchor="w", pady=6)
        self.progress = ttk.Progressbar(top, maximum=1)
        self.progress.pack(fill="x", pady=4)
        self.stop_button = ttk.Button(top, text="Stop Parsing", command=stop)
        self.stop_button.pack(anchor="e")
        split = ttk.Panedwindow(self, orient="vertical")
        split.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        table = ttk.Frame(split)
        split.add(table, weight=1)
        self.tree = ttk.Treeview(table, columns=("match", "status", "progress", "score", "duration"), show="headings", height=7)
        for name, title, width in zip(self.tree["columns"], ("MATCH / FILE", "STATUS", "FILE PROGRESS", "R : D", "DURATION"), (180, 130, 130, 100, 100)):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=70)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(fill="both", expand=True)
        detail = ttk.Frame(split)
        split.add(detail, weight=2)
        ttk.Label(detail, text="Select a match above to inspect its parsed fields and copy attempts.").pack(anchor="w", pady=(8, 5))
        self.text = tk.Text(detail, bg=BG, fg=FG, wrap="word", height=12, font=("Segoe UI", 10), relief="flat")
        detail_scroll = ttk.Scrollbar(detail, orient="vertical", command=self.text.yview)
        detail_scroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=detail_scroll.set)
        self.text.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self.show_selected())
        self.last_detail = None
        self.refresh()

    def refresh(self):
        counts = self.model.counts
        self.summary.set(f"{counts['completed']} parsed · {counts['cached']} cached · {counts['failed']} unsuccessful · {counts['total']} in batch" if self.model.session else "Saved local parse history")
        self.message.set(self.model.message)
        self.progress["value"] = self.model.fraction
        self.stop_button.configure(state="normal" if self.model.active else "disabled")
        stale = set(self.tree.get_children()) - set(self.model.rows)
        for key in stale:
            self.tree.delete(key)
        for key, row in self.model.rows.items():
            values = (row["match"], row["status"].title(), f"{row['fraction']:.0%}" if row["status"] in ("parsing", "completed", "cached", "saved") else "—", final_score(row["fields"]), elapsed(row["fields"].get("duration")))
            if self.tree.exists(key):
                if tuple(self.tree.item(key, "values")) != tuple(str(value) for value in values):
                    self.tree.item(key, values=values)
            else:
                self.tree.insert("", "end", iid=key, values=values)
        if not self.tree.selection() and self.model.rows:
            self.tree.selection_set(next(iter(self.model.rows)))
        self.show_selected()

    def show_selected(self):
        selected = self.tree.selection()
        content = match_details(self.model.rows[selected[0]]) if selected and selected[0] in self.model.rows else "No local parses recorded yet."
        if content != self.last_detail:
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", content)
            self.text.configure(state="disabled")
            self.last_detail = content
