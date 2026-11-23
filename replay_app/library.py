"""Durable catalog. Scanning/parsing is read-only; deletion is separately confirmed."""
from collections import Counter
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
import json
import os
import re
import sqlite3
import subprocess
import time
import zlib

from replay_app.client_install import EXECUTABLE, RECEIPT
from replay_app.patches import patch_at, patch_for_version
from replay_app.replay_parser import SUMMARY_VERSION, ReplayError, parse_replay, filename_match_id
from replay_app.search import SearchIndex, compile_terms, query_terms

DEFAULT_LIBRARIES = [
    {"path": r"G:\STEAM\steamapps\common\dota 2 beta\game\dota\replays", "client": "modern"},
    {"path": r"G:\Dota2Classic\Dota2_6.88f\game\dota\replays", "client": "6.88f"},
]
DEFAULT_CLIENTS = {
    "modern": r"G:\STEAM\steamapps\common\dota 2 beta\game\bin\win64\dota2.exe",
    "6.88f": r"G:\Dota2Classic\Dota2_6.88f\game\bin\win64\dota2.exe",
}
COMPATIBILITY_CLIENT = "7.20e"
DEFAULT_ROUTES = {"7.20": COMPATIBILITY_CLIENT}
LIBRARY_TYPES = {"replays": "Replay folder", "storage": "Long-term storage"}


class LibraryInMigrationRule(ValueError):
    pass


def read_pref(db, key, default):
    row = db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def write_pref(db, key, value):
    db.execute("INSERT OR REPLACE INTO preferences VALUES (?,?)", (key, json.dumps(value)))


def client_for_replay(match, copy, routes):
    patch = patch_for_version(copy.get("dota_version")) or match.get("patch") or ""
    series = patch.rstrip("abcdefghijklmnopqrstuvwxyz")
    return match.get("client_override") or routes.get(series) or copy["client"]


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
            db.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(matches)")}
            if "rating" not in columns:
                db.execute("ALTER TABLE matches ADD COLUMN rating INTEGER NOT NULL DEFAULT 0 CHECK(rating BETWEEN 0 AND 5)")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(libraries)")}
            if "kind" not in columns:
                db.execute("ALTER TABLE libraries ADD COLUMN kind TEXT NOT NULL DEFAULT 'replays'")
            if not read_pref(db, "initialized", False):
                for item in DEFAULT_LIBRARIES:
                    db.execute("INSERT OR IGNORE INTO libraries(path,client) VALUES (?,?)",
                               (str(Path(item["path"]).resolve()), item["client"]))
                write_pref(db, "initialized", True)
            if not read_pref(db, "library_management_initialized", False):
                self.migrate_library_management(db)

    def migrate_library_management(self, db):
        clients = read_pref(db, "clients", {})
        routes = read_pref(db, "client_routes", DEFAULT_ROUTES.copy())
        rules = read_pref(db, "migration_rules", {})
        legacy = clients.get("classic")
        if legacy and "dota2_6.88f" in {part.casefold() for part in PureWindowsPath(legacy).parts}:
            existing = clients.get("6.88f")
            if not existing or PureWindowsPath(existing) == PureWindowsPath(legacy):
                clients["6.88f"] = clients.pop("classic")
                db.execute("UPDATE libraries SET client='6.88f' WHERE client='classic'")
                db.execute("UPDATE matches SET client='6.88f' WHERE client='classic'")
                routes = {series: "6.88f" if client == "classic" else client for series, client in routes.items()}
                old_rule = rules.pop("classic", None)
                if old_rule:
                    rules.setdefault("6.88f", {**old_rule, "client": "6.88f"})
        for rule in rules.values():
            db.execute("""INSERT INTO libraries(path,client,kind) VALUES (?,?,'storage') ON CONFLICT(path)
                          DO UPDATE SET kind='storage' WHERE client=excluded.client""",
                       (rule["storage"], rule["client"]))
        write_pref(db, "clients", {**DEFAULT_CLIENTS, COMPATIBILITY_CLIENT: "", **clients})
        write_pref(db, "client_routes", routes)
        write_pref(db, "migration_rules", rules)
        write_pref(db, "library_management_initialized", True)

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
            return read_pref(db, key, default)

    def set_pref(self, key, value):
        with self.connect() as db:
            write_pref(db, key, value)

    def libraries(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM libraries ORDER BY id")]

    def client_paths(self):
        clients = self.get_pref("clients", {})
        parent = self.pinned_client_parent(clients)
        install = parent / f"Dota2_{COMPATIBILITY_CLIENT}"
        if clients.get(COMPATIBILITY_CLIENT) == "" and (install / RECEIPT).is_file() and (install / EXECUTABLE).is_file():
            clients[COMPATIBILITY_CLIENT] = str(install / EXECUTABLE)
        return clients

    def pinned_client_parent(self, clients=None):
        configured = self.get_pref("pinned_client_parent", "")
        if configured:
            return Path(configured)
        profiles = clients if clients is not None else self.get_pref("clients", DEFAULT_CLIENTS)
        classic = profiles.get("6.88f") or profiles.get("classic")
        if classic:
            for path in Path(classic).parents:
                if path.name.casefold() == "dota2_6.88f" and path.is_dir():
                    return path.parent
        return self.path.parent

    def client_routes(self):
        return self.get_pref("client_routes", DEFAULT_ROUTES)

    def save_client(self, name, path, series):
        if any(not re.fullmatch(r"[0-9]+\.[0-9]{2}", item) for item in series):
            raise ValueError("Use patch series such as 7.20, separated by commas.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            clients = read_pref(db, "clients", {})
            routes = read_pref(db, "client_routes", {})
            clients[name] = str(path)
            routes = {key: value for key, value in routes.items() if value != name}
            routes.update(dict.fromkeys(series, name))
            write_pref(db, "clients", clients)
            write_pref(db, "client_routes", routes)

    def remove_client(self, name):
        if name == "modern":
            raise ValueError("The modern client is built in.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            assigned = db.execute("SELECT 1 FROM libraries WHERE client=? UNION ALL SELECT 1 FROM matches WHERE client=? LIMIT 1",
                                  (name, name)).fetchone()
            if assigned or name in read_pref(db, "migration_rules", {}):
                raise ValueError("Reassign this client's libraries and replay overrides and remove its migration rule before removing the client.")
            clients = read_pref(db, "clients", {})
            clients.pop(name, None)
            write_pref(db, "clients", clients)
            routes = read_pref(db, "client_routes", {})
            write_pref(db, "client_routes", {key: value for key, value in routes.items() if value != name})

    def add_library(self, path, client, kind=None, *, library_id=None, discard_rules=False):
        if client not in self.client_paths():
            raise ValueError("Choose a configured replay client")
        if kind is not None and kind not in LIBRARY_TYPES:
            raise ValueError("Choose a library type")
        path = str(Path(path).expanduser().resolve())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = (db.execute("SELECT * FROM libraries WHERE id=?", (library_id,)).fetchone() if library_id is not None
                   else db.execute("SELECT * FROM libraries WHERE path=?", (path,)).fetchone())
            if old:
                kind = kind or old["kind"]
                if old["path"] != path and db.execute("SELECT 1 FROM libraries WHERE path=?", (path,)).fetchone():
                    raise ValueError("That folder is already registered.")
                if (old["path"], old["client"], old["kind"]) != (path, client, kind):
                    self.update_library_rules(db, old, path, client, kind, discard_rules=discard_rules)
                    if old["path"] != path:
                        db.execute("DELETE FROM files WHERE library_id=?", (old["id"],))
                    db.execute("UPDATE libraries SET path=?,client=?,kind=? WHERE id=?", (path, client, kind, old["id"]))
                return old["id"]
            if library_id is not None:
                raise ValueError("That library is no longer registered.")
            return db.execute("INSERT INTO libraries(path,client,kind) VALUES (?,?,?)",
                              (path, client, kind or "replays")).lastrowid

    @staticmethod
    def update_library_rules(db, old, path=None, client=None, kind=None, *, discard_rules=False):
        rules = read_pref(db, "migration_rules", {})
        affected = []
        for name, rule in rules.items():
            source = Path(rule["source"]) == Path(old["path"])
            storage = Path(rule["storage"]) == Path(old["path"])
            if (source or storage) and (old["path"] != path or old["client"] != client or (storage and kind != "storage")):
                affected.append(name)
        if not affected:
            return
        if not discard_rules:
            raise LibraryInMigrationRule("This change would remove the saved migration rules for " + ", ".join(affected) + ".")
        for name in affected:
            del rules[name]
        write_pref(db, "migration_rules", rules)

    def remove_library(self, library_id, *, discard_rules=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM libraries WHERE id=?", (library_id,)).fetchone()
            if old:
                self.update_library_rules(db, old, discard_rules=discard_rules)
            db.execute("DELETE FROM files WHERE library_id=?", (library_id,))
            db.execute("DELETE FROM libraries WHERE id=?", (library_id,))

    def save_migration_rule(self, rule):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for key in ("source", "storage"):
                item = db.execute("SELECT client FROM libraries WHERE path=?", (rule[key],)).fetchone()
                if (key == "source" and not item) or (item and item["client"] != rule["client"]):
                    raise ValueError("The folder assignment changed. Review the migration rule and try again.")
            rules = read_pref(db, "migration_rules", {})
            rules[rule["client"]] = rule
            db.execute("""INSERT INTO libraries(path,client,kind) VALUES (?,?,'storage') ON CONFLICT(path)
                          DO UPDATE SET kind='storage' WHERE client=excluded.client""",
                       (rule["storage"], rule["client"]))
            write_pref(db, "migration_rules", rules)

    def scan(self, progress=lambda message: None, cancelled=lambda: False):
        report = {"files": 0, "parsed": 0, "cached": 0, "recovered": 0, "errors": [], "folders": []}
        # Removed libraries retain their expensive parse caches. Index only metadata;
        # compressed timelines stay in SQLite until an actual relocation is found.
        with self.connect() as db:
            parsed_by_stat = {}
            for cached in db.execute("SELECT * FROM full_parse"):
                parsed_by_stat.setdefault((cached["size"], cached["mtime"]), []).append(dict(cached))
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
                        if (old and old["size"] == stat.st_size and old["mtime"] == stat.st_mtime_ns
                                and json.loads(old["metadata"]).get("summary_version") == SUMMARY_VERSION):
                            metadata, error = old["metadata"], old["error"]
                            report["cached"] += 1
                        else:
                            try:
                                metadata = {**parse_replay(path), "summary_version": SUMMARY_VERSION}
                                error = None
                                report["parsed"] += 1
                            except (ValueError, OSError, TypeError) as exc:
                                header = exc.metadata if isinstance(exc, ReplayError) else {}
                                metadata = {**header, "match_id": filename_match_id(path), "players": [],
                                            "summary_version": SUMMARY_VERSION}
                                error = str(exc)
                            metadata = json.dumps(metadata)
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
                for row in rows:
                    report["recovered"] += self._recover_relocated_cache(db, row, parsed_by_stat)
            report["errors"].extend(walk_errors)
            report["folders"].append({"path": str(root), "files": len(rows)})
        return report

    def _recover_relocated_cache(self, db, row, parsed_by_stat):
        """Reattach unchanged, identified replays after an external folder move.

        Match IDs alone are insufficient: different recordings of one match must
        never share caches. Require the same nanosecond mtime and byte size too,
        just as ordinary cache validation does, and refuse conflicting candidates.
        Keep original cache entries so recovery never consumes another copy's data.
        """
        path, _, size, mtime, metadata, _, _ = row
        candidates = parsed_by_stat.get((size, mtime), ())
        current = next((item for item in candidates if item["path"] == path), None)
        if current:
            return 0
        match_id = json.loads(metadata).get("match_id")
        if not match_id:
            return 0
        compatible = []
        for cached in candidates:
            try:
                data = json.loads(cached["data"])
                recorded_id = data.get("fields", {}).get("match_id")
                # Older successful helpers sometimes omitted match_id. Their
                # numeric replay filename is the same identity fallback used by
                # the summary scanner. An explicit conflicting ID always wins.
                identity = recorded_id or filename_match_id(cached["path"])
                if (data.get("complete") and data.get("schema_version") == 1
                        and str(identity) == str(match_id)):
                    compatible.append((cached, data))
            except (ValueError, AttributeError, TypeError):
                continue
        if not compatible:
            return 0
        cached, data = compatible[0]
        if any(other["version"] != cached["version"] or other_data != data
               for other, other_data in compatible[1:]):
            return 0
        # Equivalent caches can result from earlier in-app migrations. Retain
        # their timestamps/versions; moving a file must not upgrade its parser.
        source_paths = [item["path"] for item, _ in compatible]
        graph = None
        for source in source_paths:
            candidate = db.execute("SELECT * FROM replay_graphs WHERE path=? AND size=? AND mtime=?",
                                   (source, size, mtime)).fetchone()
            if candidate:
                if graph and any(candidate[key] != graph[key] for key in ("extractor", "summary", "payload")):
                    return 0
                graph = candidate
        db.execute("INSERT OR REPLACE INTO full_parse VALUES (?,?,?,?,?,?)",
                   (path, size, mtime, cached["version"], cached["data"], cached["updated"]))
        if graph:
            db.execute("INSERT OR REPLACE INTO replay_graphs VALUES (?,?,?,?,?,?,?)",
                       (path, size, mtime, graph["extractor"], graph["summary"], graph["payload"], graph["updated"]))
        # A successful recovered result supersedes any failed attempt at this path.
        db.execute("DELETE FROM parse_attempts WHERE path=?", (path,))
        return 1

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
            match["copies"].append({"path": row["path"], "client": row["client"], "library_id": row["library_id"], "library_path": row["library_path"], "size": row["size"], "mtime": row["mtime"],
                                    "replay_build": local.get("replay_build"), "dota_version": local.get("dota_version"), "end_time": local.get("end_time")})
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
            from replay_app.local_parser import PARSER_VERSION
            for full in sorted(match["local_results"], key=lambda item: (item.get("helper_version") == PARSER_VERSION, item.get("updated", 0))):
                for field in ("radiant_score", "dire_score", "duration", "lobby_type", "players", "match_id", "league_id", "game_mode", "winner", "end_time"):
                    value = full.get("fields", {}).get(field)
                    if field in ("players", "match_id", "league_id", "game_mode", "winner", "end_time") and not value:
                        continue
                    if value is not None:
                        match[field] = value
                        match["provenance"][field] = full.get("provenance", {}).get(field, "Complete local parser")
            match["local_complete"] = bool(match["local_results"])
            verified = {patch for copy in match["copies"] if (patch := patch_for_version(copy["dota_version"]))}
            match["patch_verified"] = len(verified) == 1
            match["patch"] = (verified.pop() if match["patch_verified"] else
                              patch_at(match.get("start_time")) or patch_at(match.get("end_time"))
                              or next((patch for copy in match["copies"] if (patch := patch_at(copy["end_time"]))), None))
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
        from replay_app.graphs import graph_summary
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
        from replay_app.local_parser import PARSER_VERSION
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


def startup_console_args(commands):
    args = []
    for command in commands.split(";"):
        words = command.split()
        if not words:
            continue
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", words[0]):
            raise ValueError(f"Enter a console command without a + or - prefix: {words[0]}")
        if any(token.startswith(("+", "-")) or any(char in token for char in '"\x00') for token in words[1:]):
            raise ValueError(f"Use plain arguments without quotes or launch flags for {words[0]}.")
        args.extend(("+" + words[0], *words[1:]))
    return args


def launch_command(executable, replay=None, *, pinned=False, skip_player_info=False, simulate_gc_down=False,
                   console_commands=""):
    executable = Path(executable)
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise ValueError("Select an existing Dota client .exe in Libraries & clients first")
    flags = ["-insecure", "-condebug"] if pinned else []
    if skip_player_info:
        flags.append("-skip_download_player_info")
    if simulate_gc_down:
        flags.extend(("+dev_simulate_gcdown", "1"))
    args = [str(executable.resolve()), "-console", "-novid", "-gamestateintegration", *flags,
            *startup_console_args(console_commands)]
    if replay is None:
        return args
    replay = Path(replay)
    if not replay.is_file() or replay.suffix.lower() != ".dem":
        raise ValueError("Replay file is no longer available")
    # +playdemo enters the engine command parser, so reject its control characters.
    if any(character in str(replay) for character in ('"', ';', '\n', '\r')):
        raise ValueError("Replay path contains an engine command separator")
    return [*args, "+playdemo", str(replay.resolve()).replace("\\", "/")]


def launch(executable, replay=None, *, pinned=False, skip_player_info=False, simulate_gc_down=False,
           console_commands=""):
    args = launch_command(executable, replay, pinned=pinned, skip_player_info=skip_player_info,
                          simulate_gc_down=simulate_gc_down, console_commands=console_commands)
    return subprocess.Popen(args, cwd=str(Path(executable).parent), shell=False)
