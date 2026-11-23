"""Offline application/window identity shared with the DotaBASED website mark."""
import sys
import tkinter as tk

from replay_app.resources import ASSETS


def brand_root():
    return ASSETS / "brand"


def set_windows_identity():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DotaBASED.Replay.Desktop")


def apply_window_icon(root):
    # A default applies to subsequent Toplevels, including parser/settings dialogs.
    icons = [tk.PhotoImage(master=root, file=str(brand_root() / f"replay-mark-{size}.png"))
             for size in (16, 32, 48, 64, 128, 256)]
    root.iconphoto(True, *icons)
    return icons
