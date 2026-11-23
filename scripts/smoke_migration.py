"""Storage settings, preview/cancel and move smoke using temporary fixtures only."""
import ctypes
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from app import ReplayApp
from replay_app.library import Store
from replay_app.ui.migration_dialog import MigrationDialog
from smoke_ui import screenshot
from test_replays import write_replay


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def main():
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory).resolve()
        source, storage = fixture / "downloads", fixture / "storage"
        source.mkdir()
        storage.mkdir()
        old, recent = source / "123.dem", source / "124.dem"
        write_replay(old)
        write_replay(recent, match_id=124)
        for path, when in ((old, "2024-01-01"), (recent, "2026-01-01")):
            timestamp = datetime.fromisoformat(when).timestamp()
            os.utime(path, (timestamp, timestamp))
        store = Store(fixture / "test.sqlite3")
        for library in store.libraries():
            store.remove_library(library["id"])
        store.add_library(source, "modern")
        store.add_library(storage, "modern", "storage")
        store.save_match("123", notes="Synthetic migration note", rating=4)
        root = tk.Tk()
        app = ReplayApp(root, store)
        failures = []

        def fail(exc):
            failures.append(exc)
            if not app.closed:
                app.close()

        def guarded(callback):
            def run():
                try:
                    callback()
                except Exception as exc:
                    fail(exc)
            return run

        def later(callback):
            root.after(120, guarded(callback))

        def capture(window, name, callback):
            if "--screenshots" not in sys.argv:
                later(callback)
                return
            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
            done = threading.Event()
            def worker():
                try:
                    screenshot(hwnd, Path(".validation/migration-ui") / name)
                except Exception as exc:
                    failures.append(exc)
                finally:
                    done.set()
            threading.Thread(target=worker, daemon=True).start()
            def poll():
                if done.is_set():
                    later(callback)
                else:
                    later(poll)
            later(poll)

        def finish(dialog):
            if app.busy:
                later(lambda: finish(dialog))
                return
            assert not old.exists()
            assert recent.exists()
            assert (storage / old.name).exists()
            match = next(match for match in store.catalog() if match["key"] == "123")
            assert (match["notes"], match["rating"]) == ("Synthetic migration note", 4)
            assert "1 moved; 0 failed" in dialog.summary.get()
            dialog.close()
            print("Migration UI smoke passed: settings entry, per-client save/reload, exact preview, cancel, confirmed move, newer file retained and annotations preserved", flush=True)
            app.close()

        def execute(dialog):
            assert old.exists()
            assert len(dialog.plan.files) == 1
            assert str(old) in dialog.details.get("1.0", "end")
            assert str(storage / old.name) in dialog.details.get("1.0", "end")
            dialog.close()
            settings = next(child for child in root.winfo_children()
                            if isinstance(child, tk.Toplevel) and child.title() == "Libraries & clients")
            assert any(settings.libraries.item(row, "values") == (str(storage), "Long-term storage", "modern")
                       for row in settings.libraries.get_children())
            assert old.exists(), "Cancel must not move files"
            settings.open_rules()
            reopened = next(child for child in settings.winfo_children() if isinstance(child, MigrationDialog))
            assert reopened.storage.get() == str(storage)
            reopened.preview()
            def confirm():
                if app.busy:
                    later(confirm)
                    return
                reopened.confirm_button.invoke()
                later(lambda: finish(reopened))
            later(confirm)

        def preview_ready(dialog):
            if app.busy:
                later(lambda: preview_ready(dialog))
                return
            assert dialog.plan
            root.update_idletasks()
            assert dialog.confirm_button.winfo_ismapped(), "Confirmation must remain visible"
            assert dialog.confirm_button.winfo_rooty() + dialog.confirm_button.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()
            capture(dialog, "preview.png", lambda: execute(dialog))

        def storage_settings(settings):
            executable = fixture / "Dota2_7.30e" / "game" / "bin" / "win64" / "dota2.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch("replay_app.ui.library_dialog.filedialog.askopenfilename", return_value=str(executable)):
                next(child for child in descendants(settings) if isinstance(child, ttk.Button) and child.cget("text").startswith("Add installed client")).invoke()
            editor = next(child for child in settings.winfo_children() if isinstance(child, tk.Toplevel))
            next(child for child in descendants(editor) if isinstance(child, ttk.Button) and child.cget("text") == "Save client").invoke()
            assert settings.clients.item("7.30e", "values") == ("7.30e", "Pinned", "", str(executable))
            next(child for child in descendants(settings) if isinstance(child, ttk.Button) and child.cget("text").startswith("Configure new pinned client")).invoke()
            installer = next(child for child in settings.winfo_children() if isinstance(child, tk.Toplevel))
            patch_box = next(child for child in descendants(installer) if isinstance(child, ttk.Combobox))
            assert "7.30e" in patch_box["values"]
            patch_box.set("7.30")
            assert any("8248131" in installer.getvar(child.cget("textvariable"))
                       for child in descendants(installer) if isinstance(child, ttk.Label) and child.cget("textvariable"))
            next(child for child in descendants(installer) if isinstance(child, ttk.Button) and child.cget("text").startswith("Create recipe")).invoke()
            assert any(child.title() == "Create Windows Dota client recipe" for child in installer.winfo_children() if isinstance(child, tk.Toplevel))
            installer.destroy()
            settings.clients.selection_set("modern")
            button = next(child for child in descendants(settings) if isinstance(child, ttk.Button) and child.cget("text").startswith("Migration rules"))
            button.invoke()
            dialog = next(child for child in settings.winfo_children() if isinstance(child, MigrationDialog))
            dialog.source.set(str(source))
            dialog.storage.set(str(storage))
            dialog.before.set("2025-01-01")
            dialog.save()
            dialog.client.set("6.88f")
            dialog.load_rule()
            assert dialog.storage.get() == ""
            dialog.client.set("modern")
            dialog.load_rule()
            assert dialog.storage.get() == str(storage)
            def preview():
                dialog.preview()
                later(lambda: preview_ready(dialog))
            capture(dialog, "storage-rule.png", preview)

        def start():
            if app.busy or not app.last_report:
                later(start)
                return
            app.settings()
            settings = next(child for child in root.winfo_children() if isinstance(child, tk.Toplevel))
            capture(settings, "libraries-clients.png", lambda: storage_settings(settings))
        root.after(25000, lambda: fail(RuntimeError("Migration UI smoke timed out")))
        root.after(600, guarded(start))
        root.mainloop()
        if failures:
            raise failures[0]


if __name__ == "__main__":
    main()
