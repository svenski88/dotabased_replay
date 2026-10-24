"""Preview/import local per-link match notes without changing the source file."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from library import Store

DEFAULT_NOTES = Path(r"G:\Dota2Classic\Dota2_6.88f\game\dota\replays\matches.md")
MATCH_LINK = re.compile(r"(?:\[[^\]\r\n]*\]\()?https?://(?:www\.)?(?:dotabuff|opendota)\.com/matches/(\d+)(?:[/?#][^\s)]*)?\)?", re.I)


def decode_text(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def parse_notes(source):
    text = decode_text(Path(source).read_bytes())
    entries = []
    for line_number, line in enumerate(text.splitlines(), 1):
        links = list(MATCH_LINK.finditer(line))
        for index, link in enumerate(links):
            end = links[index + 1].start() if index + 1 < len(links) else len(line)
            annotation = re.sub(r"^[\s\-–—:]+", "", line[link.end():end]).strip()
            match_id = link.group(1)
            entries.append({"match_id": match_id, "note": annotation, "line": line_number,
                            "source_line": line, "fingerprint": hashlib.sha256((match_id + "\0" + annotation).encode("utf-8")).hexdigest()})
    return entries


def import_notes(store, source=DEFAULT_NOTES, apply=False, backup=True):
    """Return a dry-run report by default; applying backs up SQLite before one transaction.

    Annotation text is kept verbatim after stripping only the link delimiter.
    Each import records its original source line and a content fingerprint.
    Existing user notes are preserved; missing blocks append with provenance.
    """
    source = Path(source).expanduser().resolve()
    entries = parse_notes(source)
    report = {"source": str(source), "links": len(entries), "unique_matches": len({e['match_id'] for e in entries}),
              "annotated": sum(bool(e["note"]) for e in entries), "empty": sum(not e["note"] for e in entries),
              "duplicates": 0, "already_imported": 0, "already_present": 0, "changed": 0,
              "applied": apply, "backup": None, "preview": []}
    candidates = []
    seen = set()
    for entry in entries:
        if not entry["note"]:
            continue
        if entry["fingerprint"] in seen:
            report["duplicates"] += 1
            continue
        seen.add(entry["fingerprint"])
        candidates.append(entry)
    with store.connect() as db:
        imported = {r[0] for r in db.execute("SELECT fingerprint FROM note_imports WHERE source=?", (str(source),))}
        existing = {r["id"]: r["notes"] for r in db.execute("SELECT id, notes FROM matches")}
        for entry in candidates:
            if entry["fingerprint"] in imported:
                report["already_imported"] += 1
            else:
                previous = existing.get(entry["match_id"], "")
                present = entry["note"] == previous.strip() or entry["note"] in previous.split("\n\n") or previous.endswith("\n" + entry["note"])
                if present:
                    report["already_present"] += 1
                else:
                    report["changed"] += 1
                    report["preview"].append({"match_id": entry["match_id"], "line": entry["line"], "note": entry["note"], "action": "append" if previous.strip() else "set"})
                    existing[entry["match_id"]] = previous + "\n\n" + entry["note"] if previous.strip() else entry["note"]
    if not apply or not candidates or report["already_imported"] == len(candidates):
        return report
    if backup:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"-{time.time_ns() % 1000000000:09}"
        backup_path = store.path.with_name(store.path.stem + f".backup-{stamp}.sqlite3")
        with closing(sqlite3.connect(store.path)) as source_db, closing(sqlite3.connect(backup_path)) as destination:
            source_db.backup(destination)
        report["backup"] = str(backup_path)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        actual_changed = 0
        for entry in candidates:
            exists = db.execute("SELECT 1 FROM note_imports WHERE source=? AND fingerprint=?", (str(source), entry["fingerprint"])).fetchone()
            if exists:
                continue
            row = db.execute("SELECT notes FROM matches WHERE id=?", (entry["match_id"],)).fetchone()
            previous = row[0] if row else ""
            present = entry["note"] == previous.strip() or entry["note"] in previous.split("\n\n") or previous.endswith("\n" + entry["note"])
            if not present:
                addition = f"[Imported from {source.name}, line {entry['line']}]\n{entry['note']}"
                updated = previous + "\n\n" + addition if previous.strip() else entry["note"]
                db.execute("INSERT INTO matches(id, notes) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET notes=excluded.notes", (entry["match_id"], updated))
                actual_changed += 1
            db.execute("INSERT INTO note_imports VALUES (?,?,?,?,?,?,?)", (str(source), entry["fingerprint"], entry["match_id"], entry["note"], entry["source_line"], entry["line"], time.time()))
        report["changed"] = actual_changed
    return report


def main():
    parser = argparse.ArgumentParser(description="Preview or import match-link notes (dry run unless --apply)")
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_NOTES)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = import_notes(Store(args.database), args.source, apply=args.apply)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
