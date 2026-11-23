"""Small native UI helpers: monitor-aware tooltips and single-row toolbars."""
import sys
import tkinter as tk
from tkinter import ttk


def tooltip_coordinates(pointer, size, bounds):
    """Absolute desktop coordinates, including monitors left/above the primary."""
    px, py = pointer
    width, height = size
    left, top, right, bottom = bounds
    x = px + 12 if px + width + 18 <= right else px - width - 12
    y = py + 12 if py + height + 18 <= bottom else py - height - 12
    return (max(left + 6, min(x, right - width - 6)),
            max(top + 6, min(y, bottom - height - 6)))


def monitor_bounds(widget, pointer):
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        handle = user32.MonitorFromPoint(wintypes.POINT(*map(int, pointer)), 2)
        if handle and user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            rect = info.work
            return rect.left, rect.top, rect.right, rect.bottom
    left, top = widget.winfo_vrootx(), widget.winfo_vrooty()
    return left, top, left + widget.winfo_vrootwidth(), top + widget.winfo_vrootheight()


def position_tooltip(tooltip, owner, event):
    tooltip.update_idletasks()
    pointer = (event.x_root, event.y_root)
    size = (tooltip.winfo_reqwidth(), tooltip.winfo_reqheight())
    x, y = map(int, tooltip_coordinates(pointer, size, monitor_bounds(owner, pointer)))
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        handle = user32.GetParent(tooltip.winfo_id()) or tooltip.winfo_id()
        # Native absolute placement avoids Tk's negative geometry offsets and
        # primary-screen clamping on multi-monitor desktops. Don't steal focus.
        if user32.SetWindowPos(handle, None, x, y, 0, 0, 0x0015):
            return
    # '+-N' explicitly addresses a negative absolute origin in Tk geometry.
    tooltip.geometry(f"+{x}+{y}")


def make_tooltip(owner, text, event):
    tip = tk.Toplevel(owner)
    tip.withdraw()
    tip.wm_overrideredirect(True)
    tk.Label(tip, text=text, justify="left", bg="#263544", fg="#e6edf5",
             wraplength=450, padx=8, pady=6, font=("Segoe UI", 9)).pack()
    tip.update_idletasks()
    # Realize the native window before positioning, without an initial guessed
    # screen position that may be relative to a different monitor.
    tip.deiconify()
    position_tooltip(tip, owner, event)
    return tip


class HoverTip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.pending = self.tip = None
        widget.bind("<Enter>", self.enter, add=True)
        widget.bind("<Leave>", self.hide, add=True)
        widget.bind("<ButtonPress>", self.hide, add=True)
        widget.bind("<Destroy>", self.hide, add=True)

    def enter(self, event):
        self.hide()
        def show():
            self.pending = None
            text = self.text() if callable(self.text) else self.text
            self.tip = make_tooltip(self.widget, text, event)
        self.pending = self.widget.after(400, show)

    def hide(self, event=None):
        if self.pending is not None:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class HorizontalToolbar(ttk.Frame):
    """Keep controls in one row; expose a scrollbar only at narrow widths."""
    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, height=28, width=1, bg="#10151d", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="ew")
        self.scroll = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.scroll.set)
        self.content = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self.layout)
        self.content.bind("<Configure>", self.layout)
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(-int(e.delta / 120), "units"))

    def layout(self, event=None):
        requested = self.content.winfo_reqwidth()
        available = self.canvas.winfo_width()
        self.canvas.configure(height=self.content.winfo_reqheight(),
                              scrollregion=(0, 0, max(requested, available), self.content.winfo_reqheight()))
        self.canvas.itemconfigure(self.window, width=max(requested, available))
        if requested > available + 1:
            self.scroll.grid(row=1, column=0, sticky="ew")
        else:
            self.scroll.grid_remove()
            self.canvas.xview_moveto(0)
