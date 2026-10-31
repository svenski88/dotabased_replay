"""One-at-a-time, cancellable local helper orchestration; no network calls."""
import argparse
import json
import math
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

PARSER_VERSION = "1.2.1+manta1.5.2"
MAX_CHAT_BYTES = 32 * 1024 * 1024
MAX_GRAPH_BYTES = 64 * 1024 * 1024


def validate_chat(entry):
    if not isinstance(entry, dict) or any(not isinstance(entry.get(key), str) for key in ("speaker", "text", "channel")):
        raise ParseError("Invalid chat entry from local helper")
    if type(entry.get("tick")) is not int or entry["tick"] < 0:
        raise ParseError("Invalid chat tick from local helper")
    value = entry.get("time")
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ParseError("Invalid chat time from local helper")
    return entry


def helper_path():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "bin" / ("replay-parser.exe" if sys.platform == "win32" else "replay-parser")


class ParseError(RuntimeError):
    def __init__(self, message, status="failed"):
        super().__init__(message)
        self.status = status


def validate_result(data, version=PARSER_VERSION):
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("helper_version") != version:
        raise ParseError("Local helper version/protocol mismatch")
    if data.get("complete") is not True:
        raise ParseError(data.get("error", "Recording has no final score"), data.get("status", "failed"))
    if data.get("final_state") not in (6, 7) or not isinstance(data.get("provenance"), dict):
        raise ParseError("Helper did not prove a recorded post-game state")
    fields = data.get("fields")
    if not isinstance(fields, dict):
        raise ParseError("Helper result has no fields")
    for name in ("radiant_score", "dire_score"):
        value = fields.get(name)
        if type(value) is not int or value < 0 or name not in data["provenance"]:
            raise ParseError("Helper final score is missing or unverified")
    for name in ("duration", "lobby_type"):
        value = fields.get(name)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ParseError(f"Invalid local {name}")
    return data


class LocalParser:
    def __init__(self, executable=None, timeout=600, version=PARSER_VERSION):
        self.executable = Path(executable) if executable else helper_path()
        self.timeout = timeout
        self.version = version
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.process = None
        self.active = False

    def stop(self):
        self.cancelled.set()
        with self.lock:
            process = self.process
            if process and process.poll() is None:
                process.kill()  # A single native process, no shell or grandchildren.

    def reset(self):
        if self.active:
            raise ParseError("Cannot reset an active parse queue")
        self.cancelled.clear()

    def close(self):
        self.stop()
        with self.lock:
            process = self.process
        if process:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()

    def parse_file(self, path, progress=lambda event: None):
        if self.cancelled.is_set():
            raise ParseError("Parsing stopped", "cancelled")
        events = queue.Queue()
        with self.lock:
            if self.cancelled.is_set():
                raise ParseError("Parsing stopped", "cancelled")
            if self.process is not None:
                raise ParseError("A local helper process is already active")
            process = subprocess.Popen([str(self.executable), str(path)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.process = process
        def read_output():
            try:
                while line := process.stdout.readline(131073):
                    if len(line) > 131072:
                        events.put(ParseError("Helper output line exceeds protocol limit"))
                        return
                    try:
                        event = json.loads(line)
                        events.put(event if isinstance(event, dict) else ParseError("Helper returned a non-object JSON record"))
                    except ValueError:
                        events.put(ParseError("Helper returned malformed JSON"))
                        return
            finally:
                events.put(None)
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        started, result, ended = time.monotonic(), None, False
        chat, chat_bytes = [], 0
        graph_samples, graph_events, graph_bytes = [], [], 0
        try:
            while not ended or process.poll() is None:
                if self.cancelled.is_set():
                    raise ParseError("Parsing stopped; current uncommitted result discarded", "cancelled")
                if time.monotonic() - started > self.timeout:
                    raise ParseError(f"Local parse exceeded {self.timeout:g} seconds", "timeout")
                try:
                    event = events.get(timeout=.05)
                except queue.Empty:
                    continue
                if event is None:
                    ended = True
                elif isinstance(event, Exception):
                    raise event
                elif event.get("event") == "progress":
                    progress(event)
                elif event.get("event") == "result":
                    result = event
                elif event.get("event") in ("graph_sample", "graph_event"):
                    from graphs import validate_sample, validate_event
                    try:
                        entry = (validate_sample if event["event"] == "graph_sample" else validate_event)(event.get("entry"))
                    except ValueError as exc:
                        raise ParseError(str(exc)) from exc
                    graph_bytes += len(json.dumps(entry).encode("utf-8"))
                    if graph_bytes > MAX_GRAPH_BYTES:
                        raise ParseError("Graph stream exceeds the 64 MiB safety limit")
                    if event["event"] == "graph_sample":
                        if graph_samples and entry["time"] <= graph_samples[-1]["time"]:
                            raise ParseError("Graph samples are not strictly ordered")
                        graph_samples.append(entry)
                    else:
                        graph_events.append(entry)
                elif event.get("event") == "chat":
                    entry = validate_chat(event.get("entry"))
                    chat_bytes += len(json.dumps(entry).encode("utf-8"))
                    if chat_bytes > MAX_CHAT_BYTES:
                        raise ParseError("Chat log exceeds the 32 MiB safety limit")
                    chat.append(entry)
            if self.cancelled.is_set():
                raise ParseError("Parsing stopped", "cancelled")
            if result is None:
                raise ParseError(f"Local helper exited {process.returncode} without a result")
            validated = validate_result(result, self.version)
            if result.get("chat_complete") is True:
                if type(result.get("chat_count")) is not int or result["chat_count"] != len(chat):
                    raise ParseError("Local helper chat stream is incomplete")
                validated["chat"] = chat
            if result.get("graph_schema_version") is not None:
                if result["graph_schema_version"] != 1 or type(result.get("graph_complete")) is not bool:
                    raise ParseError("Invalid graph protocol version/completion")
                if any(type(result.get(key)) is not int for key in ("graph_sample_count", "graph_event_count")) or result.get("graph_sample_count") != len(graph_samples) or result.get("graph_event_count") != len(graph_events):
                    raise ParseError("Local helper graph stream is incomplete")
                validated["graph"] = {"schema_version": 1, "complete": result["graph_complete"],
                                      "samples": graph_samples, "events": graph_events,
                                      "duration": result["fields"].get("duration"), "winner": result["fields"].get("winner"),
                                      "extractor_version": self.version, "clock_source": result.get("graph_clock_source")}
            elif graph_samples or graph_events:
                raise ParseError("Graph stream has no final counts")
            if process.returncode != 0:
                raise ParseError(f"Local helper exited {process.returncode}")
            return validated
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=1)
            reader.join(timeout=1)
            process.stdout.close()
            with self.lock:
                if self.process is process:
                    self.process = None

    def derive(self, graph):
        from graphs import derive_graph, GraphCancelled
        try:
            return derive_graph(graph, self.cancelled.is_set)
        except GraphCancelled as exc:
            self.cancelled.set()
            raise ParseError(str(exc), "cancelled") from exc

    def parse_all(self, store, progress=lambda event: None, matches=None):
        with self.lock:
            if self.active:
                raise ParseError("A local parse queue is already active")
            self.active = True
        report = {"total": 0, "completed": 0, "cached": 0, "failed": 0, "cancelled": False}
        try:
            if matches is None:
                progress({**report, "index": 0, "phase": "scan", "path": "Refreshing local file catalog"})
                store.scan(lambda message: progress({**report, "index": 0, "phase": "scan", "path": message}), self.cancelled.is_set)
            catalog = list(matches) if matches is not None else store.catalog()
            report["total"] = len(catalog)
            progress({**report, "index": 0, "phase": "batch", "matches": catalog})
            for index, match in enumerate(catalog):
                if self.cancelled.is_set():
                    break
                def announce(event=None, path=""):
                    progress({**report, "index": index + 1, "key": match["key"], "match_id": match.get("match_id"), "path": path, **(event or {})})
                copies = match["copies"]
                def unchanged(copy):
                    try:
                        stat = Path(copy["path"]).stat()
                        return (stat.st_size, stat.st_mtime_ns) == (copy["size"], copy["mtime"])
                    except OSError:
                        return False
                def cached_usable(copy):
                    if not unchanged(copy):
                        return False
                    metadata = store.full_cached(copy, self.version)
                    if not metadata:
                        return False
                    if metadata.get("graph_schema_version") is not None:
                        graph = store.graph_cached(copy, self.version)
                        return graph is not None and graph.get("schema_version") == 1
                    return True  # retain compatibility with metadata-only synthetic fixtures
                cached_copy = next((copy for copy in copies if cached_usable(copy)), None)
                if cached_copy:
                    cached = store.full_cached(cached_copy, self.version)
                    graph = store.graph_cached(cached_copy, self.version)
                    if graph is not None:
                        from graphs import needs_derivation
                        if needs_derivation(graph):
                            try:
                                self.derive(graph)
                            except ParseError:
                                report["cancelled"] = True
                                break
                            if not unchanged(cached_copy):
                                report["failed"] += 1
                                store.save_parse_attempt(cached_copy, self.version, "failed", "File changed during cached scoring; result discarded")
                                announce({"status": "failed", "error": "File changed during cached scoring; result discarded", "fraction": 0}, cached_copy["path"])
                                continue
                            store.save_graph(cached_copy, self.version, graph)
                    report["cached"] += 1
                    announce({"status": "cached", "fraction": 1, "result": store.full_cached(cached_copy, self.version)}, cached_copy["path"])
                    continue
                success = False
                for copy in copies:
                    if self.cancelled.is_set():
                        break
                    path = Path(copy["path"])
                    announce({"fraction": 0, "status": "parsing"}, str(path))
                    try:
                        before = path.stat()
                        if (before.st_size, before.st_mtime_ns) != (copy["size"], copy["mtime"]):
                            raise ParseError("File changed since scan; rescan before parsing")
                        result = self.parse_file(path, lambda event: announce(event, str(path)))
                        recovered_id = result.get("fields", {}).get("match_id")
                        if match.get("match_id") and recovered_id and str(match["match_id"]) != str(recovered_id):
                            raise ParseError("Local parser identity conflicts with catalog summary/filename; result discarded")
                        after = path.stat()
                        if (after.st_size, after.st_mtime_ns) != (copy["size"], copy["mtime"]):
                            raise ParseError("File changed during parsing; result discarded")
                        if self.cancelled.is_set():
                            raise ParseError("Parsing stopped", "cancelled")
                        if "graph" in result:
                            announce({"phase": "scoring", "fraction": 1}, str(path))
                            self.derive(result["graph"])
                        if self.cancelled.is_set():
                            raise ParseError("Parsing stopped", "cancelled")
                        final_stat = path.stat()
                        if (final_stat.st_size, final_stat.st_mtime_ns) != (copy["size"], copy["mtime"]):
                            raise ParseError("File changed during scoring; result discarded")
                        store.save_full_parse(copy, self.version, result)
                        success = True
                        report["completed"] += 1
                        announce({"fraction": 1, "status": "completed", "committed": True, "result": result}, str(path))
                        break
                    except (OSError, ParseError) as exc:
                        status = getattr(exc, "status", "failed")
                        store.save_parse_attempt(copy, self.version, status, str(exc))
                        announce({"status": status, "error": str(exc), "fraction": 0}, str(path))
                        if status == "cancelled":
                            self.cancelled.set()
                            break
                if not success and not self.cancelled.is_set():
                    report["failed"] += 1
                announce({"phase": "settled", "committed": success}, str(path))
            report["cancelled"] = self.cancelled.is_set()
            return report
        finally:
            self.active = False


def main():
    parser = argparse.ArgumentParser(description="Explicit offline full replay parsing")
    parser.add_argument("replay", nargs="?", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    runner = LocalParser()
    try:
        if args.all:
            from library import Store
            print(json.dumps(runner.parse_all(Store(args.database), lambda event: print(json.dumps(event), flush=True)), indent=2))
        elif args.replay:
            print(json.dumps(runner.parse_file(args.replay), indent=2))
        else:
            parser.error("Provide a replay path or --all")
    finally:
        runner.close()


if __name__ == "__main__":
    main()
