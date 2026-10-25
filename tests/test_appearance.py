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
