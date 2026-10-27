"""Exercise library search using only synthetic replays and a temporary database."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from app import ReplayApp
from library import Store
from search import SearchIndex
from benchmark_search import catalog_fixture
from test_replays import write_replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", default="1540x920")
    parser.add_argument("--large-catalog", type=int, default=1000)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        store = Store(folder / "search.sqlite3")
        for library in store.libraries():
            store.remove_library(library["id"])
        store.add_library(folder, "modern")
        for identifier in (901, 902):
            write_replay(folder / f"{identifier}.dem", match_id=identifier)
        store.scan()
        with store.connect() as db:
            row = db.execute("SELECT path, metadata FROM files WHERE path LIKE '%901.dem'").fetchone()
            metadata = json.loads(row["metadata"])
            metadata["players"][0]["hero"] = "nevermore"
            metadata["players"].append({"account_id": 99, "name": "Bob", "hero": "crystal_maiden", "team": 3})
            db.execute("UPDATE files SET metadata=? WHERE path=?", (json.dumps(metadata), row["path"]))
        store.pin(42, "Captain Sven", enabled=False)
        store.save_match("901", notes="Huge late comeback, excellent wards")
        store.save_match("902", notes="Early push")
        store.set_pref("hide_unknown", False)
        root = tk.Tk()
        app = ReplayApp(root, store)
        root.geometry(args.geometry)
        failures = []
        def timeout():
            failures.append(AssertionError("Search UI smoke timed out"))
            app.close()
        root.after(15000, timeout)

        def large_catalog():
            try:
                app.catalog = catalog_fixture(args.large_catalog)
                app.search_index = SearchIndex(app.catalog, app.account_rows)
                app.search.set("")
                app.render_matches()
                original_render = app.render_matches
                render_times, heartbeats = [], []
                def measured_render():
                    started = perf_counter()
                    original_render()
                    render_times.append(perf_counter() - started)
                app.render_matches = measured_render
                # A burst must not synchronously filter/rebuild the catalog.
                for query in ("C", "Ca", "Capt", "Captain", "Captain Sven", "Captain Sven Rylai"):
                    app.search.set(query)
                assert not render_times
                root.after(20, lambda: heartbeats.append(len(render_times)))
                def verify():
                    try:
                        assert heartbeats == [0], "Typing prevented the heartbeat before delayed rendering"
                        assert len(render_times) == 1, "Typing burst rendered more than once"
                        assert len(app.visible) == args.large_catalog
                        print(f"Large catalog UI: {args.large_catalog} matches; delayed filter/sort/grid rebuild {render_times[0]:.3f}s; heartbeat ran before render", flush=True)
                    except Exception as exc:
                        failures.append(exc)
                    app.close()
                root.after(400, verify)
            except Exception as exc:
                failures.append(exc)
                app.close()

        queries = iter([('SF, CM "late comeback"', ["901"]), ('"Captain Sven", Rylai', ["901"]), ("SF axe", []), ('SF "Crystal Mai', ["901"]), ("early push", ["902"]), ("", ["901", "902"])])

        def next_query():
            query, expected = next(queries, (None, None))
            if query is None:
                large_catalog()
                return
            app.search.set(query)
            def verify():
                try:
                    assert sorted(match["match_id"] for match in app.visible) == expected, query
                    next_query()
                except Exception as exc:
                    failures.append(exc)
                    app.close()
            root.after(190, verify)

        def exercise():
            if app.busy:
                root.after(100, exercise)
                return
            try:
                assert app.copy_match_id_button.instate(["disabled"])
                app.match_tree.selection_set(["901"], focus="901")
                app.select_match()
                assert not app.copy_match_id_button.instate(["disabled"])
                app.copy_match_id_button.invoke()
                assert root.clipboard_get() == "901"
                match = app.current_match()
                match_id = match.pop("match_id")
                app.show_match(match)
                assert app.copy_match_id_button.instate(["disabled"])
                match["match_id"] = match_id
                app.match_tree.selection_set([])
                app.current_key = None
                app.clear_match()
                assert app.copy_match_id_button.instate(["disabled"])
                next_query()
            except Exception as exc:
                failures.append(exc)
                app.close()
        root.after(600, exercise)
        root.mainloop()
        if failures:
            raise failures[0]
        print("Search UI smoke passed: AND terms, aliases, nicknames, notes, quotes and reset")


if __name__ == "__main__":
    main()
