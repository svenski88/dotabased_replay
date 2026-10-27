"""Windows UI integration smoke with a disposable database and optional screenshot.

No API requests or Dota client launches. Reads the default replay folders.
"""
import argparse
import ctypes
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ReplayApp
from library import Store, is_unknown
from notes_import import DEFAULT_NOTES, import_notes


def screenshot(hwnd, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    # PrintWindow captures just this application window, without unrelated desktop content.
    code = """
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class ReplayCapture {
  [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);
}
'@
$bounds = New-Object ReplayCapture+Rect
[ReplayCapture]::GetWindowRect([IntPtr]HWND_VALUE, [ref]$bounds) | Out-Null
$bitmap = New-Object System.Drawing.Bitmap(($bounds.Right - $bounds.Left), ($bounds.Bottom - $bounds.Top))
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$dc = $graphics.GetHdc()
try { [ReplayCapture]::PrintWindow([IntPtr]HWND_VALUE, $dc, 2) | Out-Null } finally { $graphics.ReleaseHdc($dc) }
$bitmap.Save('TARGET_VALUE', [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
""".replace("HWND_VALUE", str(hwnd)).replace("TARGET_VALUE", str(target.resolve()).replace("'", "''"))
    subprocess.run(["powershell", "-NoProfile", "-Command", code], check=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--geometry", help="Override window size, e.g. 1100x720")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        app = ReplayApp(root, Store(Path(directory) / "ui.sqlite3"))
        if args.geometry:
            root.geometry(args.geometry)
        failures = []
        root.after(15000, app.close)
        capture_done = threading.Event()
        def finish_capture():
            if capture_done.is_set():
                app.close()
            else:
                root.after(100, finish_capture)
        def exercise():
            if app.busy or not app.last_report:
                root.after(200, exercise)
                return
            try:
                assert app.catalog, "No replay entries found in default folders"
                assert len(app.visible) == sum(not is_unknown(match) for match in app.catalog)
                if DEFAULT_NOTES.is_file():
                    imported = import_notes(app.store, DEFAULT_NOTES, apply=True)
                    assert imported["changed"] > 0
                    assert import_notes(app.store, DEFAULT_NOTES)["changed"] == 0
                    app.reload()
                first = app.visible[0]
                app.match_tree.selection_set(first["key"])
                app.select_match()
                app.notes.insert("1.0", "UI smoke: saved on selection and filtering.")
                app.search.set("axe")
                app.render_matches()
                assert next(m for m in app.store.catalog() if m["key"] == first["key"])["notes"].startswith("UI smoke")
                app.search.set("")
                app.render_matches()
                suggestion = app.suggestions[0]
                app.store.pin(suggestion["id"], "Svenge")
                app.selected_account = suggestion["id"]
                app.reload()
                app.tracked_filter.set(True)
                app.filter_changed()
                assert len(app.visible) == suggestion["count"]
                app.league_only.set(True)
                app.filter_changed()
                assert all(m.get("league_id") for m in app.visible)
                app.league_only.set(False)
                app.tracked_filter.set(False)
                app.filter_changed()
                assert len(app.visible) == sum(not is_unknown(match) for match in app.catalog)
                app.hide_unknown.set(False)
                app.filter_changed()
                assert len(app.visible) == len(app.catalog)
                app.hide_unknown.set(True)
                app.filter_changed()
                league = next(m for m in app.visible if m.get("league_id"))
                app.match_tree.selection_set(league["key"])
                app.match_tree.see(league["key"])
                app.select_match()
                app.notes.insert("1.0", "League replay · local league ID detected automatically.\n\nNotes stay on this machine. Fetch match metadata to fill lobby and score.")
                app.save_notes()
                root.update_idletasks()
                assert len(app.match_tree.body.find_withtag("hero_icon")) > 0, "Grid icons must be real canvas images"
                app.match_tree.yview("scroll", 3, "units")
                app.match_tree.xview("scroll", 2, "units")
                root.update_idletasks()
                assert len(app.match_tree.body.find_withtag("hero_icon")) > 0, "Icons must survive scrolling"
                app.match_tree.xview("moveto", 0)
                app.match_tree.see(league["key"])
                app.sort("date")
                root.update_idletasks()
                assert app.match_tree.selection() == (league["key"],)
                app.match_tree.see(league["key"])
                app.status.set("UI validation passed · offline scan, notes, tracked accounts, league filter and selection")
                root.lift()
                root.update()
                if args.screenshot:
                    hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
                    def capture():
                        try:
                            screenshot(hwnd, args.screenshot)
                        except Exception as exc:
                            failures.append(exc)
                        finally:
                            capture_done.set()
                    threading.Thread(target=capture, daemon=True).start()
                    root.after(100, finish_capture)
                print(f"UI smoke passed: {len(app.catalog)} entries; account filter {suggestion['count']} matches; {len(app.match_tree.icons.images)} bundled hero images")
            except Exception as exc:
                failures.append(exc)
            finally:
                if not args.screenshot or failures:
                    app.close()
        root.after(1000, exercise)
        root.mainloop()
        if failures:
            raise failures[0]


if __name__ == "__main__":
    main()
