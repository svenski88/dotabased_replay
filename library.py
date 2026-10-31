"""Durable catalog. Scanning/parsing is read-only; deletion is separately confirmed."""
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import time
import zlib

from replay_parser import parse_replay, filename_match_id
from search import SearchIndex, compile_terms, query_terms

DEFAULT_LIBRARIES = [
    {"path": r"G:\STEAM\steamapps\common\dota 2 beta\game\dota\replays", "client": "modern"},
    {"path": r"G:\Dota2Classic\Dota2_6.88f\game\dota\replays", "client": "classic"},
]
DEFAULT_CLIENTS = {
    "modern": r"G:\STEAM\steamapps\common\dota 2 beta\game\bin\win64\dota2.exe",
    "classic": r"G:\Dota2Classic\Dota2_6.88f\game\bin\win64\dota2.exe",
}


def data_directory():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DotaBasedReplay"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "dotabased-replay"


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_directory() / "library.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS libraries (id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, client TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, library_id INTEGER, size INTEGER, mtime INTEGER,
              metadata TEXT, error TEXT, present INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS matches (id TEXT PRIMARY KEY, notes TEXT DEFAULT '', client TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY, nickname TEXT DEFAULT '', enabled INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, data TEXT, expires REAL, status INTEGER);
            CREATE TABLE IF NOT EXISTS note_imports (source TEXT, fingerprint TEXT, match_id TEXT, note TEXT,
              source_line TEXT, line_number INTEGER, imported_at REAL, PRIMARY KEY(source, fingerprint));
            CREATE TABLE IF NOT EXISTS full_parse (path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER,
              version TEXT, data TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS replay_graphs (path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER,
              extractor TEXT, summary TEXT NOT NULL, payload BLOB NOT NULL, updated REAL);
            CREATE TABLE IF NOT EXISTS parse_attempts (path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER,
              version TEXT, status TEXT, error TEXT, updated REAL);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(matches)")}
            if "rating" not in columns:
                db.execute("ALTER TABLE matches ADD COLUMN rating INTEGER NOT NULL DEFAULT 0 CHECK(rating BETWEEN 0 AND 5)")
        if not self.get_pref("initialized", False):
            for item in DEFAULT_LIBRARIES:
                self.add_library(item["path"], item["client"])
            self.set_pref("clients", DEFAULT_CLIENTS)
            self.set_pref("initialized", True)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get_pref(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_pref(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO preferences VALUES (?,?)", (key, json.dumps(value)))

    def libraries(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM libraries ORDER BY id")]

    def add_library(self, path, client):
        if client not in DEFAULT_CLIENTS:
            raise ValueError("Client must be modern or classic")
        path = str(Path(path).expanduser().resolve())
        with self.connect() as db:
            db.execute("INSERT INTO libraries(path, client) VALUES (?,?) ON CONFLICT(path) DO UPDATE SET client=excluded.client", (path, client))

    def remove_library(self, library_id):
        with self.connect() as db:
            db.execute("DELETE FROM files WHERE library_id=?", (library_id,))
            db.execute("DELETE FROM libraries WHERE id=?", (library_id,))

    def scan(self, progress=lambda message: None, cancelled=lambda: False):
        report = {"files": 0, "parsed": 0, "cached": 0, "errors": [], "folders": []}
        for library in self.libraries():
            if cancelled():
                break
            root = Path(library["path"])
            if not root.is_dir():
                report["errors"].append(f"Folder unavailable: {root}")
                continue
            with self.connect() as db:
                known = {r["path"]: dict(r) for r in db.execute("SELECT * FROM files WHERE library_id=?", (library["id"],))}
            rows = []
            walk_errors = []
            for directory, dirs, names in os.walk(root, followlinks=False, onerror=lambda error: walk_errors.append(str(error))):
                dirs[:] = [name for name in dirs if not Path(directory, name).is_symlink()]
                for name in names:
                    if not name.lower().endswith(".dem"):
                        continue
                    if cancelled():
                        return report
                    path = Path(directory, name)
                    if path.is_symlink():
                        continue
                    key = str(path.resolve())
                    report["files"] += 1
                    if report["files"] % 25 == 0:
                        progress(f"Scanning {report['files']:,} replay files…")
                    try:
                        stat = path.stat()
                        old = known.get(key)
                        if old and old["size"] == stat.st_size and old["mtime"] == stat.st_mtime_ns:
                            metadata, error = old["metadata"], old["error"]
                            report["cached"] += 1
                        else:
                            try:
                                metadata = json.dumps(parse_replay(path))
                                error = None
                                report["parsed"] += 1
                            except (ValueError, OSError, TypeError) as exc:
                                metadata = json.dumps({"match_id": filename_match_id(path), "players": []})
                                error = str(exc)
                        rows.append((key, library["id"], stat.st_size, stat.st_mtime_ns, metadata, error, 1))
                        if error:
                            report["errors"].append(f"{path.name}: {error}")
                    except OSError as exc:
                        walk_errors.append(f"{path}: {exc}")
            with self.connect() as db:
                # Preserve previous presence if any subtree was inaccessible.
                if not walk_errors:
                    db.execute("UPDATE files SET present=0 WHERE library_id=?", (library["id"],))
                db.executemany("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)", rows)
            report["errors"].extend(walk_errors)
            report["folders"].append({"path": str(root), "files": len(rows)})
        return report

    def catalog(self):
        with self.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT f.*, l.client, l.path AS library_path FROM files f JOIN libraries l ON f.library_id=l.id WHERE present=1 ORDER BY f.path")]
            notes = {r["id"]: dict(r) for r in db.execute("SELECT * FROM matches")}
            api = {r["key"].removeprefix("matches/"): json.loads(r["data"]) for r in db.execute("SELECT * FROM cache WHERE key LIKE 'matches/%' AND status=200")}
            parsed = {r["path"]: dict(r) for r in db.execute("SELECT * FROM full_parse")}
            attempts = {r["path"]: dict(r) for r in db.execute("SELECT * FROM parse_attempts")}
            graphs = {r["path"]: dict(r) for r in db.execute("SELECT path,size,mtime,extractor,summary,updated FROM replay_graphs")}
        grouped = {}
        for row in rows:
            local = json.loads(row["metadata"])
            full = parsed.get(row["path"])
            full_data = None
            if full and full["size"] == row["size"] and full["mtime"] == row["mtime"]:
                candidate = json.loads(full["data"])
                if candidate.get("complete") and candidate.get("schema_version") == 1:
                    identity = candidate.get("fields", {})
                    if local.get("match_id") and identity.get("match_id") and str(local["match_id"]) != str(identity["match_id"]):
                        row["error"] = "Local parser identity conflicts with replay summary/filename; result not applied"
                    else:
                        full_data = candidate
                        for field in ("match_id", "players", "league_id", "winner", "end_time", "game_mode"):
                            if not local.get(field) and identity.get(field):
                                local[field] = identity[field]
            key = local.get("match_id") or "file:" + row["path"]
            if key not in grouped:
                grouped[key] = {**local, "key": key, "copies": [], "errors": [], "notes": notes.get(key, {}).get("notes", ""), "client_override": notes.get(key, {}).get("client", ""), "rating": notes.get(key, {}).get("rating", 0)}
            match = grouped[key]
            if not match.get("players") and local.get("players"):
                match.update(local)
            match["copies"].append({"path": row["path"], "client": row["client"], "library_id": row["library_id"], "library_path": row["library_path"], "size": row["size"], "mtime": row["mtime"]})
            match.setdefault("local_results", [])
            match.setdefault("parse_attempts", [])
            cached_graph = graphs.get(row["path"])
            if full_data and cached_graph and (cached_graph["size"], cached_graph["mtime"]) == (row["size"], row["mtime"]):
                summary = json.loads(cached_graph["summary"])
                match.setdefault("graph_summaries", []).append({"path": row["path"], "updated": cached_graph["updated"], "extractor_version": cached_graph["extractor"], **summary})
            if full_data:
                match["local_results"].append({"path": row["path"], "version": full["version"], "updated": full["updated"], **full_data})
            attempt = attempts.get(row["path"])
            if attempt and attempt["size"] == row["size"] and attempt["mtime"] == row["mtime"]:
                match["parse_attempts"].append(attempt)
            if row["error"]:
                match["errors"].append(row["error"])
        for key, match in grouped.items():
            match["total_size"] = sum(copy["size"] for copy in match["copies"])
            remote = api.get(key) or {}
            match["api_cached"] = bool(remote)
            match["provenance"] = {field: "Replay summary" for field in ("match_id", "players", "league_id", "winner", "end_time", "game_mode") if match.get(field) is not None}
            if match.get("duration") is not None:
                match["provenance"]["duration"] = "Replay summary playback time (not game clock)"
            for field in ("lobby_type", "radiant_score", "dire_score"):
                match[field] = remote.get(field)
                if match[field] is not None:
                    match["provenance"][field] = "Cached OpenDota"
            # Older API responses often use 0:0 placeholders even with recorded
            # player combat. Keep the raw cache unchanged, but do not show a false final.
            suspicious_zero = remote.get("radiant_score") == 0 and remote.get("dire_score") == 0 and any((p.get("kills") or 0) > 0 or (p.get("deaths") or 0) > 0 for p in remote.get("players", []))
            if suspicious_zero:
                match["radiant_score"] = match["dire_score"] = None
                match["score_notice"] = "Cached API 0:0 is unverified despite player combat; parse locally to recover the final score"
            if not match.get("league_id") and remote.get("leagueid"):
                match["league_id"] = remote["leagueid"]
            match["league_name"] = (remote.get("league") or {}).get("name", "")
            match["start_time"] = remote.get("start_time")
            if match.get("winner") not in (2, 3) and isinstance(remote.get("radiant_win"), bool):
                match["winner"] = 2 if remote["radiant_win"] else 3
            if match.get("duration") is None:
                match["duration"] = remote.get("duration")
                if match["duration"] is not None:
                    match["provenance"]["duration"] = "Cached OpenDota game duration"
            if not match.get("players"):
                match["players"] = [{"account_id": p.get("account_id"), "name": p.get("personaname", ""), "hero": f"Hero #{p.get('hero_id', '?')}", "team": 3 if p.get("player_slot", 0) >= 128 else 2} for p in remote.get("players", [])]
            # Complete entity-stream results upgrade only fields actually present.
            # Never take relative game clock times as epoch start_time/end_time.
            from local_parser import PARSER_VERSION
            for full in sorted(match["local_results"], key=lambda item: (item.get("helper_version") == PARSER_VERSION, item.get("updated", 0))):
                for field in ("radiant_score", "dire_score", "duration", "lobby_type", "players", "match_id", "league_id", "game_mode", "winner", "end_time"):
                    value = full.get("fields", {}).get(field)
                    if field in ("players", "match_id", "league_id", "game_mode", "winner", "end_time") and not value:
                        continue
                    if value is not None:
                        match[field] = value
                        match["provenance"][field] = full.get("provenance", {}).get(field, "Complete local parser")
            match["local_complete"] = bool(match["local_results"])
            graph_summaries = match.get("graph_summaries", [])
            if graph_summaries:
                match["graph_summary"] = max(graph_summaries, key=lambda g: (g.get("extractor_version") == PARSER_VERSION and g.get("schema_version") == 1, g.get("complete", False), g.get("sample_count", 0), g["updated"]))
                match["category"] = match["graph_summary"].get("category", {}).get("label", "Insufficient data")
            else:
                match["category"] = "Not parsed"
            chat_results = [item for item in match["local_results"] if item.get("chat_complete") is True and isinstance(item.get("chat"), list)]
            if chat_results:
                chat_result = max(chat_results, key=lambda item: (item.get("helper_version") == PARSER_VERSION, item.get("updated", 0)))
                match["chat"] = chat_result["chat"]
                match["chat_complete"] = True
            if match["local_complete"]:
                match.pop("score_notice", None)
        return sorted(grouped.values(), key=lambda match: int(match.get("match_id") or 0), reverse=True)

    def save_match(self, key, notes=None, client=None, rating=None):
        if rating is not None and (type(rating) is not int or not 0 <= rating <= 5):
            raise ValueError("Rating must be an integer from 0 to 5")
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO matches(id) VALUES (?)", (key,))
            if notes is not None:
                db.execute("UPDATE matches SET notes=? WHERE id=?", (notes, key))
            if client is not None:
                db.execute("UPDATE matches SET client=? WHERE id=?", (client, key))
            if rating is not None:
                db.execute("UPDATE matches SET rating=? WHERE id=?", (rating, key))

    def accounts(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM accounts ORDER BY id")]

    def pin(self, account, nickname="", enabled=True):
        account = int(account)
        if not 0 < account < 2**32:
            raise ValueError("Account ID must be between 1 and 4294967295")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO accounts VALUES (?,?,?)", (account, nickname.strip(), int(enabled)))

    def unpin(self, account):
        with self.connect() as db:
            db.execute("DELETE FROM accounts WHERE id=?", (int(account),))

    def cached(self, key, now=None, include_stale=False):
        with self.connect() as db:
            row = db.execute("SELECT * FROM cache WHERE key=?", (key,)).fetchone()
        if row and (include_stale or row["expires"] > (time.time() if now is None else now)):
            return {**dict(row), "data": json.loads(row["data"])}
        return None

    def cache(self, key, data, ttl, status=200, now=None):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?,?)", (key, json.dumps(data), (time.time() if now is None else now) + ttl, status))

    def full_cached(self, copy, version):
        with self.connect() as db:
            row = db.execute("SELECT * FROM full_parse WHERE path=? AND size=? AND mtime=? AND version=?", (copy["path"], copy["size"], copy["mtime"], version)).fetchone()
        return json.loads(row["data"]) if row else None

    def save_full_parse(self, copy, version, result):
        if not result.get("complete"):
            raise ValueError("Only complete local results may replace a successful parse")
        graph = result.get("graph")
        metadata = {key: value for key, value in result.items() if key != "graph"}
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO full_parse VALUES (?,?,?,?,?,?)", (copy["path"], copy["size"], copy["mtime"], version, json.dumps(metadata), time.time()))
            if graph is not None:
                self._write_graph(db, copy, version, graph)
            db.execute("DELETE FROM parse_attempts WHERE path=?", (copy["path"],))

    def _write_graph(self, db, copy, version, graph):
        from graphs import graph_summary
        summary = json.dumps(graph_summary(graph), allow_nan=False)
        payload = zlib.compress(json.dumps(graph, separators=(",", ":"), allow_nan=False).encode("utf-8"))
        db.execute("INSERT OR REPLACE INTO replay_graphs VALUES (?,?,?,?,?,?,?)",
                   (copy["path"], copy["size"], copy["mtime"], version, summary, payload, time.time()))

    def save_graph(self, copy, version, graph):
        with self.connect() as db:
            self._write_graph(db, copy, version, graph)

    def graph_cached(self, copy, version=None):
        with self.connect() as db:
            row = db.execute("SELECT extractor,payload FROM replay_graphs WHERE path=? AND size=? AND mtime=?",
                             (copy["path"], copy["size"], copy["mtime"])).fetchone()
        if not row or (version is not None and row["extractor"] != version):
            return None
        try:
            return json.loads(zlib.decompress(row["payload"]))
        except (ValueError, zlib.error):
            return None

    def graph_for_match(self, match, preferred_path=None):
        copies = list(match.get("copies", []))
        from local_parser import PARSER_VERSION
        preferred = preferred_path or match.get("graph_summary", {}).get("path")
        summaries = {summary["path"]: summary for summary in match.get("graph_summaries", [])}
        def priority(copy):
            summary = summaries.get(copy["path"], {})
            current = summary.get("extractor_version") == PARSER_VERSION and summary.get("schema_version") == 1
            return (not current, copy["path"] != preferred)
        copies.sort(key=priority)
        for copy in copies:
            graph = self.graph_cached(copy)
            if graph is not None:
                return graph
        return None

    def save_parse_attempt(self, copy, version, status, error):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO parse_attempts VALUES (?,?,?,?,?,?,?)", (copy["path"], copy["size"], copy["mtime"], version, status, error, time.time()))


def presence(catalog):
    counts = Counter()
    names = {}
    for match in catalog:
        for player in match.get("players", []):
            if player.get("account_id") and player.get("name"):
                names.setdefault(player["account_id"], player["name"])
        counts.update({p["account_id"] for p in match.get("players", []) if p.get("account_id") and p["account_id"] != 4294967295})
    total = len(catalog)
    return [{"id": account, "count": count, "fraction": count / total, "name": names.get(account, "")} for account, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])) if total and count / total > .05]


def is_unknown(match):
    return not (match.get("match_id") and (match.get("start_time") or match.get("end_time")) and match.get("players"))


def format_size(size):
    return f"{size / (1024 * 1024):,.1f} MiB"


def note_preview(notes, limit=80):
    first_line = notes.splitlines()[0].strip() if notes.splitlines() else ""
    return first_line if len(first_line) <= limit else first_line[:max(0, limit - 3)].rstrip() + "..."


def filter_matches(catalog, accounts, enabled=False, search="", league_only=False, hide_unknown=False, search_index=None, category="All categories"):
    wanted = {a["id"] for a in accounts if a["enabled"]}
    terms = compile_terms(query_terms(search)) if search.strip() else ()
    index = search_index if search_index is not None else (SearchIndex(catalog, accounts) if terms else None)
    return [m for m in catalog if (not enabled or bool(wanted & {p.get("account_id") for p in m.get("players", [])}))
            and (category == "All categories" or m.get("category", "Not parsed") == category)
            and (not league_only or bool(m.get("league_id")))
            and (not hide_unknown or not is_unknown(m))
            and (not terms or index.matches(m, terms))]


def launch_command(executable, replay):
    executable, replay = Path(executable), Path(replay)
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise ValueError("Select an existing Dota client .exe in Libraries & clients first")
    if not replay.is_file() or replay.suffix.lower() != ".dem":
        raise ValueError("Replay file is no longer available")
    # +playdemo enters the engine command parser, so reject its control characters.
    if any(character in str(replay) for character in ('"', ';', '\n', '\r')):
        raise ValueError("Replay path contains an engine command separator")
    return [str(executable.resolve()), "-console", "-novid", "-gamestateintegration",
            "+playdemo", str(replay.resolve()).replace("\\", "/")]


def launch(executable, replay):
    args = launch_command(executable, replay)
    return subprocess.Popen(args, cwd=str(Path(executable).parent), shell=False)
