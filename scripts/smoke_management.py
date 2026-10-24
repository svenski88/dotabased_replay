"""Exercise ratings/multi-select/delete-cancel using ONLY synthetic temp replays."""
import argparse
import ctypes
from pathlib import Path
import sys
import tempfile
import threading
import tkinter as tk
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from app import ReplayApp
from delete_dialog import DeleteDialog
from deletion import make_delete_plan
from library import Store
from replay_grid import ROW_HEIGHT
from smoke_ui import screenshot
from test_replays import write_replay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--modal-screenshot", type=Path)
    parser.add_argument("--geometry", default="1540x920")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        fixture_root = Path(directory).resolve()
        store = Store(fixture_root / "fixture.sqlite3")
        for library in store.libraries():
            store.remove_library(library["id"])
        files = []
        for client in ("modern", "classic"):
            folder = fixture_root / client
            folder.mkdir()
            store.add_library(folder, client)
            for identifier in ([901, 902, 903] if client == "modern" else [901]):
                path = folder / f"{identifier}.dem"
                write_replay(path, match_id=identifier)
                with path.open("ab") as stream:
                    stream.write(b"\0" * ((512 * 1024 if identifier == 901 else (identifier - 900) * 1024 * 1024) - path.stat().st_size))
                files.append(path)
        store.set_pref("hide_unknown", False)
        store.save_match("901", notes="Disposable duplicate replay · both copies total 1 MiB", rating=4)
        store.save_match("903", notes="Keep this fixture note", rating=2)
        root = tk.Tk()
        app = ReplayApp(root, store)
        root.geometry(args.geometry)
        failures = []
        root.after(15000, app.close)

        def capture_then(window, target, callback):
            if not target:
                callback()
                return
            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
            done = threading.Event()
            def worker():
                try:
                    screenshot(hwnd, target)
                except Exception as exc:
                    failures.append(exc)
                finally:
                    done.set()
            threading.Thread(target=worker, daemon=True).start()
            def poll():
                if done.is_set():
                    callback()
                else:
                    root.after(80, poll)
            root.after(80, poll)

        def modal():
            plan = make_delete_plan(store, app.match_tree.selection())
            dialog = DeleteDialog(root, plan)
            assert len(dialog.selected_paths()) == 3
            assert "3 / 3 files" in dialog.total.get()
            first_path = plan.files[0].path
            dialog.choices[first_path].set(False)
            dialog.update_total()
            assert len(dialog.selected_paths()) == 2
            def cancel():
                dialog.cancel()
                assert dialog.result is None
                assert all(path.is_file() for path in files), "Cancelling must not remove a fixture"
                print("Management UI smoke passed: sizes, stars/clear/keyboard, multi-select, numeric sort, notes and delete cancel", flush=True)
                app.close()
            capture_then(dialog, args.modal_screenshot, cancel)

        def exercise():
            if app.busy or not app.last_report:
                root.after(100, exercise)
                return
            try:
                grid = app.match_tree
                grid.selection_set(["901", "903"], focus="903")
                root.update()
                app.notes.insert("end", " · pending edit retained")
                row = grid.order.index("901")
                x = grid.widths()[0] + 22 + 4 * 17 + 8
                grid.click(SimpleNamespace(x=x, y=row * ROW_HEIGHT + 17, state=0))
                root.update()
                assert set(grid.selection()) == {"901", "903"}
                assert app.current_key == "901"
                assert next(m for m in store.catalog() if m["key"] == "901")["rating"] == 5
                assert next(m for m in store.catalog() if m["key"] == "903")["notes"].endswith("pending edit retained")
                grid.click(SimpleNamespace(x=grid.widths()[0] + 12, y=row * ROW_HEIGHT + 17, state=0))
                assert next(m for m in store.catalog() if m["key"] == "901")["rating"] == 0
                grid.rate_focused(4)
                app.sort("size")
                root.update()
                assert grid.order == ["901", "902", "903"]
                assert set(grid.selection()) == {"901", "903"}
                assert app.current_key == "901"
                assert "Selected: 0.5 MiB" == app.copy_size.get()
                assert "2 matches selected" in app.selection_summary.get()
                app.status.set("Management validation · synthetic temp fixtures only · original replay libraries never selected")
                capture_then(root, args.screenshot, modal)
            except Exception as exc:
                failures.append(exc)
                app.close()
        root.after(600, exercise)
        root.mainloop()
        if failures:
            raise failures[0]


if __name__ == "__main__":
    main()
