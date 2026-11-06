"""User-confirmed replay storage rules. Preview and scans never move files."""
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import os
from pathlib import Path
import sqlite3
import stat

from deletion import DeleteTarget, check_location, identity, revalidate, unlink_verified


def directory(path):
    if not str(path).strip():
        raise ValueError("Choose a folder")
    path = Path(path).expanduser().absolute()
    if ".." in path.parts:
        raise ValueError("Folder paths cannot contain '..'")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or current.is_symlink():
            raise ValueError(f"Use ordinary folders, without symlinks/junctions: {current}")
    return path


def validate_rule(store, rule):
    if rule.get("client") not in ("modern", "classic"):
        raise ValueError("Choose modern or classic")
    cutoff = date.fromisoformat(rule["before"])
    source, storage = directory(rule["source"]), directory(rule["storage"])
    if source.is_relative_to(storage) or storage.is_relative_to(source):
        raise ValueError("Source and storage must be separate, non-overlapping folders")
    libraries = store.libraries()
    library = next((item for item in libraries if Path(item["path"]) == source), None)
    if not library or library["client"] != rule["client"]:
        raise ValueError("Source must be a registered replay folder assigned to this client")
    for item in libraries:
        root = Path(item["path"])
        if (root.is_relative_to(storage) or storage.is_relative_to(root)) and item["client"] != rule["client"]:
            raise ValueError("Storage overlaps a replay library assigned to another client")
    return {"client": rule["client"], "source": str(source), "storage": str(storage), "before": cutoff.isoformat()}


def save_rule(store, rule):
    rule = validate_rule(store, rule)
    rules = store.get_pref("migration_rules", {})
    rules[rule["client"]] = rule
    store.set_pref("migration_rules", rules)
    return rule


@dataclass(frozen=True)
class MigrationTarget:
    source: DeleteTarget
    destination: str


@dataclass(frozen=True)
class MigrationPlan:
    client: str
    source: str
    storage: str
    before: str
    files: tuple
    errors: tuple


def make_plan(store, rule):
    rule = validate_rule(store, rule)
    cutoff = datetime.combine(date.fromisoformat(rule["before"]), datetime.min.time()).timestamp()
    targets, errors = [], []
    for match in store.catalog():
        for copy in match["copies"]:
            if copy["library_path"] != rule["source"] or copy["mtime"] / 1e9 >= cutoff:
                continue
            destination = Path(rule["storage"]) / Path(copy["path"]).relative_to(rule["source"])
            try:
                info = check_location(rule["source"], copy["path"])
                if (info.st_size, info.st_mtime_ns) != (copy["size"], copy["mtime"]):
                    raise ValueError("Replay changed since scan; rescan first")
                if destination.exists() or destination.is_symlink():
                    raise ValueError(f"Destination already exists (never overwritten): {destination}")
                targets.append(MigrationTarget(DeleteTarget(copy["path"], rule["source"], copy["library_id"], match["key"], copy["size"], copy["mtime"], identity(info)), str(destination)))
            except (OSError, ValueError) as exc:
                errors.append(f"{copy['path']}: {exc}")
    return MigrationPlan(rule["client"], rule["source"], rule["storage"], rule["before"], tuple(targets), tuple(errors))


def copy_verified(target, storage):
    """Exclusive creation, verified bytes and preserved timestamps, across volumes."""
    source, destination = target.source, Path(target.destination)
    if not destination.is_relative_to(Path(storage)) or destination == Path(storage) or destination.suffix.lower() != ".dem" or ".." in destination.parts:
        raise ValueError("Destination must be a replay inside the storage folder")
    revalidate(source)
    directory(storage)
    relative = destination.relative_to(storage)
    parent = Path(storage)
    for part in relative.parts[:-1]:
        parent /= part
        parent.mkdir(exist_ok=True)
        directory(parent)
    created = None
    try:
        digest = hashlib.sha256()
        with open(source.path, "rb") as original, destination.open("xb") as output:
            created = identity(os.fstat(output.fileno()))[:2]
            if identity(os.fstat(original.fileno())) != source.identity:
                raise ValueError("Source changed after confirmation")
            while chunk := original.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        revalidate(source)
        check_location(storage, destination)
        with destination.open("rb") as output:
            if hashlib.file_digest(output, "sha256").digest() != digest.digest():
                raise ValueError("Storage copy failed content verification")
        os.utime(destination, ns=(source.mtime, source.mtime))
        return destination.stat()
    except Exception:
        # Only remove our own incomplete copy. Never replace an existing file.
        if created and destination.exists() and identity(destination.lstat())[:2] == created:
            destination.unlink()
        raise


def publish_copy(store, target, plan, info):
    """Commit recovery data before removing the original physical replay."""
    source = target.source
    with store.connect() as db:
        library = db.execute("SELECT * FROM libraries WHERE id=?", (source.library_id,)).fetchone()
        row = db.execute("SELECT * FROM files WHERE path=? AND present=1", (source.path,)).fetchone()
        if not library or library["path"] != plan.source or library["client"] != plan.client or not row or row["library_id"] != source.library_id or (row["size"], row["mtime"]) != (source.size, source.mtime):
            raise ValueError("Source catalog or client assignment changed; original kept")
        dest_library = db.execute("SELECT * FROM libraries WHERE path=?", (plan.storage,)).fetchone()
        if not dest_library or dest_library["client"] != plan.client:
            raise ValueError("Storage library assignment changed; original kept")
        db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,1)", (target.destination, dest_library["id"], info.st_size, info.st_mtime_ns, row["metadata"], row["error"]))
        for table in ("full_parse", "replay_graphs", "parse_attempts"):
            cached = db.execute(f"SELECT * FROM {table} WHERE path=?", (source.path,)).fetchone()
            if cached and (cached["size"], cached["mtime"]) == (source.size, source.mtime):
                values = dict(cached)
                values.update(path=target.destination, size=info.st_size, mtime=info.st_mtime_ns)
                db.execute(f"INSERT OR REPLACE INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
        if source.match_key == "file:" + source.path:
            new_key = "file:" + target.destination
            db.execute("INSERT OR IGNORE INTO matches(id,notes,client,rating) SELECT ?,notes,client,rating FROM matches WHERE id=?", (new_key, source.match_key))
            db.execute("UPDATE note_imports SET match_id=? WHERE match_id=?", (new_key, source.match_key))


def migrate(store, plan, confirmed=False, cancelled=lambda: False, progress=lambda text: None):
    report = {"cancelled": not confirmed, "moved": [], "copied": [], "failed": []}
    if not confirmed:
        return report
    validate_rule(store, {"client": plan.client, "source": plan.source, "storage": plan.storage, "before": plan.before})
    store.add_library(plan.storage, plan.client)
    for index, target in enumerate(plan.files):
        if cancelled():
            report["cancelled"] = True
            break
        progress(f"Moving replay {index + 1}/{len(plan.files)}: {Path(target.source.path).name}")
        stage = "copy"
        try:
            info = copy_verified(target, plan.storage)
            stage = "catalog update (verified storage copy retained)"
            publish_copy(store, target, plan, info)
            report["copied"].append(target.destination)
            stage = "source removal (verified storage copy retained)"
            stored = check_location(plan.storage, target.destination)
            if identity(stored) != identity(info):
                raise ValueError("Storage copy changed after verification; original kept")
            unlink_verified(target.source)
            with store.connect() as db:
                db.execute("UPDATE files SET present=0 WHERE path=?", (target.source.path,))
            report["moved"].append(target.source.path)
        except (OSError, ValueError, sqlite3.Error) as exc:
            report["failed"].append({"path": target.source.path, "destination": target.destination, "stage": stage, "error": str(exc)})
    return report
