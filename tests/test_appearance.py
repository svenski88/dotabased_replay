from pathlib import Path
import struct
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app import BG, ReplayApp
from branding import brand_root
from library import Store


class AppearanceTests(unittest.TestCase):
    def test_scrollbar_palette_for_full_active_and_pressed_states_and_icons(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory, patch.object(ReplayApp, "scan"):
            app = ReplayApp(root, Store(Path(directory) / "appearance.sqlite3"))
            style = ttk.Style(root)
            for orient in ("Horizontal", "Vertical"):
                name = orient + ".TScrollbar"
                bar = ttk.Scrollbar(root, orient=orient.lower())
                for state, expected in (("disabled", "#202b38"), ("active", "#3b536a"), ("pressed", "#4b6b87")):
                    self.assertEqual(style.lookup(name, "background", (state,)), expected)
                    self.assertEqual(style.lookup(name, "troughcolor", (state,)), BG)
                    self.assertEqual(style.lookup(name, "bordercolor", (state,)), BG)
                    for edge in ("lightcolor", "darkcolor"):
                        self.assertEqual(style.lookup(name, edge, (state,)), expected)
                bar.set(0, 1)
                self.assertIn("disabled", bar.state(), "Fully visible ranges must exercise the inactive style")
                self.assertEqual(style.lookup(name, "background", bar.state()), "#202b38")
                for pointer_state in ("active", "pressed"):
                    self.assertEqual(style.lookup(name, "background", ("disabled", pointer_state)), "#202b38")
                bar.set(0, .25)
                self.assertNotIn("disabled", bar.state())
                bar.destroy()
            self.assertEqual((app.brand_mark.width(), app.brand_mark.height()), (48, 48))
            self.assertEqual(len(app.window_icons), 6)
            dialog = tk.Toplevel(root)
            root.update()
            if sys.platform == "win32":
                import ctypes
                user32 = ctypes.windll.user32
                user32.SendMessageW.restype = ctypes.c_void_p
                user32.GetClassLongPtrW.restype = ctypes.c_void_p
                for window in (root, dialog):
                    hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
                    # Tk can install its default icon on the native window class.
                    handle = user32.SendMessageW(hwnd, 0x7F, 0, 0) or user32.GetClassLongPtrW(hwnd, -34)
                    self.assertTrue(handle, "Root and new dialogs must receive a native small icon")
            dialog.destroy()
            app.closed = True

    def test_launch_menu_uses_selected_client_and_reuses_watch_options(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(root.destroy)
        def cancel_pending_callbacks():
            for callback in root.tk.splitlist(root.tk.call("after", "info")):
                root.tk.call("after", "cancel", callback)

        self.addCleanup(cancel_pending_callbacks)
        with (tempfile.TemporaryDirectory() as directory, patch.object(ReplayApp, "scan"),
              patch("app.apply_window_icon"), patch("app.launch") as launch):
            path = Path(directory)
            executable = path / "dota2.exe"
            executable.touch()
            store = Store(path / "launch.sqlite3")
            store.save_client("7.32e", executable, ["7.32"])
            store.save_client("modern", executable, [])
            app = ReplayApp(root, store)
            self.addCleanup(setattr, app, "closed", True)
            app.prepare_launch_menu()
            self.assertEqual(app.launch_options_menu.entrycget(3, "state"), "disabled")

            replay = path / "example.dem"
            app.copy_options = [{"client": "modern", "path": str(replay)}]
            app.copy_choice.configure(values=("example.dem",))
            app.copy_choice.current(0)
            app.catalog = [{"key": "example", "patch": "7.32e"}]
            app.current_key = "example"
            app.prepare_launch_menu()
            self.assertTrue(app.simulate_gc_down.get())
            self.assertTrue(app.skip_player_info.get())
            self.assertEqual(app.launch_options_menu.entrycget(3, "state"), "normal")

            key = "client_startup_commands/7.32e"
            store.set_pref(key, "volume 0.07")
            app.launch_options_menu.invoke(4)
            dialog = next(child for child in root.winfo_children() if isinstance(child, tk.Toplevel))
            body = dialog.winfo_children()[0]
            editor = next(child for child in body.winfo_children() if isinstance(child, tk.Text))
            self.assertEqual(editor.get("1.0", "end-1c"), "volume 0.07")
            primary, secondary = [child for child in body.winfo_children() if isinstance(child, ttk.Checkbutton)]
            self.assertFalse(primary.instate(["selected"]))
            self.assertFalse(secondary.instate(["selected"]))
            primary.invoke()
            secondary.invoke()
            actions = body.winfo_children()[-1]
            next(button for button in actions.winfo_children() if button.cget("text") == "Save commands").invoke()
            self.assertEqual(Store(store.path).get_pref(key), {
                "commands": "volume 0.07", "presets": ["primary_chat_wheel", "secondary_chat_wheel"],
            })
            launch.return_value.poll.return_value = 0
            app.watch_button.invoke()
            commands = launch.call_args.kwargs["console_commands"]
            self.assertEqual(commands.split("; "), [
                *(f"chat_wheel_phrase_{slot} {value}" for slot, value in enumerate(
                    (8, 1, 2, 3, 4, 5, 6, 7, 65, 69, 79, 66, 80, 61, 62, 70))),
                "volume 0.07",
            ])
            launch.assert_called_with(str(executable), str(replay), pinned=True,
                                      skip_player_info=True, simulate_gc_down=True, console_commands=commands)
            app.launch_options_menu.invoke(0)
            app.launch_options_menu.invoke(3)
            launch.assert_called_with(str(executable), None, pinned=True,
                                      skip_player_info=True, simulate_gc_down=False, console_commands=commands)

            app.catalog[0]["client_override"] = "modern"
            app.prepare_launch_menu()
            self.assertFalse(app.simulate_gc_down.get())
            self.assertFalse(app.skip_player_info.get())
            app.launch_options_menu.invoke(3)
            launch.assert_called_with(str(executable), None, pinned=False,
                                      skip_player_info=False, simulate_gc_down=False, console_commands="")

    def test_windows_icon_contains_small_and_large_png_frames(self):
        data = (brand_root() / "replay.ico").read_bytes()
        self.assertEqual(struct.unpack_from("<HHH", data), (0, 1, 7))
        sizes = []
        for index in range(7):
            width, height, _, _, planes, bits, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + index * 16)
            self.assertEqual(width, height)
            sizes.append(width or 256)
            self.assertEqual((planes, bits), (1, 32))
            self.assertEqual(data[offset:offset + 8], b"\x89PNG\r\n\x1a\n")
            self.assertLessEqual(offset + length, len(data))
        self.assertEqual(sizes, [16, 24, 32, 48, 64, 128, 256])
