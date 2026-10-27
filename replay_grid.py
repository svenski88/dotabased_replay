"""Virtualized native Tk replay table with inline team hero images.

Only visible rows are painted; all assets are loaded from the offline bundle.
The small Treeview-compatible surface keeps selection and keyboard behavior
consistent with the account lists and existing application workflows.
"""
import json
import math
from pathlib import Path
import sys
import tkinter as tk
from tkinter import font as tkfont, ttk

BG = "#18212c"
FG = "#e6edf5"
ROW_HEIGHT = 34


def rating_hit_test(x):
    """Local rating-cell x: five 17px stars, with no numeric clear region."""
    if 5 <= x < 90:
        return 1 + int((x - 5) // 17)
    return None


def resize_boundary(columns, widths, x, tolerance=5):
    edge = 0
    for column, width in zip(columns, widths):
        edge += width
        if column in ("tracked", "notes", "league") and abs(x - edge) <= tolerance:
            return column
    return None


def clamp_column_width(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Column width must be finite and numeric")
    return max(70, min(2000, int(value)))


def selection_click(order, selected, anchor, key, control=False, shift=False):
    """Pure selection transition, used by pointer and keyboard navigation."""
    selected = set(selected) & set(order)
    if key not in order:
        return selected, anchor
    if shift and anchor in order:
        first, last = sorted((order.index(anchor), order.index(key)))
        ranged = set(order[first:last + 1])
        return (selected | ranged if control else ranged), anchor
    if control:
        selected.symmetric_difference_update({key})
        return selected, key
    return {key}, key


def asset_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"


class HeroIcons:
    def __init__(self, master):
        self.images = {}
        self.metadata = {}
        try:
            self.metadata = json.loads((asset_root() / "heroes.json").read_text(encoding="utf-8"))["heroes"]
        except (OSError, ValueError, KeyError):
            pass
        self.by_id = {str(value["id"]): name for name, value in self.metadata.items()}
        for name in self.metadata:
            try:
                source = tk.PhotoImage(master=master, file=str(asset_root() / "heroes" / f"{name}.png"))
                self.images[name] = source.zoom(3).subsample(4)  # Steam's 32px icons -> 24px.
            except (tk.TclError, OSError):
                continue

    def key(self, hero):
        value = str(hero or "").removeprefix("npc_dota_hero_")
        if value.startswith("Hero #"):
            return self.by_id.get(value.removeprefix("Hero #"), value)
        return value

    def name(self, hero):
        key = self.key(hero)
        return self.metadata.get(key, {}).get("name") or key.replace("_", " ").title() or "Unknown hero"

    def image(self, hero):
        return self.images.get(self.key(hero))


class ReplayGrid(ttk.Frame):
    def __init__(self, master, columns, **kwargs):
        super().__init__(master)
        self.columns = tuple(columns)
        self.definitions = {key: {"text": key, "width": 100, "command": None} for key in self.columns}
        self.rows = {}
        self.order = []
        self.selected = None
        self.selected_keys = set()
        self.anchor = None
        self.on_rating = None
        self.on_column_resize = None
        self.explicit_widths = set()
        self.resizing = None
        self.pressed_column = None
        self.pending = None
        self.tooltip = None
        self.tooltip_text = ""
        self.icon_hits = []
        self.xcommand = None
        self.ycommand = None
        self.icons = HeroIcons(self)
        self.text_font = tkfont.Font(self, family="Segoe UI", size=9)
        self.header_font = tkfont.Font(self, family="Segoe UI", size=9, weight="bold")
        self.star_font = tkfont.Font(self, family="Segoe UI Symbol", size=12)
        self.header = tk.Canvas(self, height=34, bg="#233040", highlightthickness=0)
        self.header.pack(fill="x")
        self.body = tk.Canvas(self, bg=BG, highlightthickness=0, takefocus=True, height=9 * ROW_HEIGHT)
        self.body.pack(fill="both", expand=True)
        self.body.configure(xscrollcommand=self.on_xscroll, yscrollcommand=self.on_yscroll)
        self.body.bind("<Configure>", lambda event: self.invalidate())
        self.header.bind("<Button-1>", self.header_press)
        self.header.bind("<B1-Motion>", self.header_drag)
        self.header.bind("<ButtonRelease-1>", self.header_release)
        self.header.bind("<Motion>", self.header_motion)
        self.header.bind("<Leave>", lambda event: self.header.configure(cursor="") if not self.resizing else None)
        self.body.bind("<Button-1>", self.click)
        self.body.bind("<MouseWheel>", self.wheel)
        self.body.bind("<Shift-MouseWheel>", self.horizontal_wheel)
        self.body.bind("<Button-4>", lambda event: self.yview("scroll", -1, "units"))
        self.body.bind("<Button-5>", lambda event: self.yview("scroll", 1, "units"))
        self.body.bind("<Motion>", self.hover)
        self.body.bind("<Leave>", lambda event: self.hide_tooltip())
        for sequence, delta in (("<Up>", -1), ("<Down>", 1), ("<Prior>", -8), ("<Next>", 8)):
            self.body.bind(sequence, lambda event, amount=delta: self.move_selection(amount, bool(event.state & 1)))
        self.body.bind("<Home>", lambda event: self.choose(0))
        self.body.bind("<End>", lambda event: self.choose(len(self.order) - 1))
        self.body.bind("<Control-a>", self.select_all)
        if sys.platform == "darwin":
            self.body.bind("<Command-a>", self.select_all)
        for rating in range(6):
            self.body.bind(str(rating), lambda event, value=rating: self.rate_focused(value))

    def __getitem__(self, key):
        return self.columns if key == "columns" else super().__getitem__(key)

    def configure(self, cnf=None, **kwargs):
        if "xscrollcommand" in kwargs:
            self.xcommand = kwargs.pop("xscrollcommand")
        if "yscrollcommand" in kwargs:
            self.ycommand = kwargs.pop("yscrollcommand")
        if cnf is not None or kwargs:
            return super().configure(cnf, **kwargs)

    config = configure

    def heading(self, key, **kwargs):
        self.definitions[key].update(kwargs)
        self.invalidate()

    def column(self, key, **kwargs):
        self.definitions[key].update(kwargs)
        self.invalidate()

    def restore_widths(self, saved):
        if not isinstance(saved, dict):
            return
        for key in ("tracked", "notes", "league"):
            if key in saved and key in self.definitions:
                try:
                    self.definitions[key]["width"] = clamp_column_width(saved[key])
                    self.explicit_widths.add(key)
                except ValueError:
                    continue
        self.invalidate()

    def tag_configure(self, *args, **kwargs):
        pass  # Fixed palette below matches the original Treeview row tags.

    def get_children(self):
        return tuple(self.order)

    def exists(self, key):
        return key in self.rows

    def insert(self, parent, index, iid, values, tags=(), heroes=None):
        self.rows[iid] = {"values": tuple(values), "tags": tags, "heroes": heroes or {}}
        self.order.append(iid)
        self.invalidate()

    def update_values(self, key, values):
        if key in self.rows:
            self.rows[key]["values"] = tuple(values)
            self.invalidate()

    def delete(self, *keys):
        removed = set(keys)
        for key in removed:
            self.rows.pop(key, None)
        self.order = [key for key in self.order if key not in removed]
        if self.selected in removed:
            self.selected = None
        self.selected_keys.difference_update(removed)
        self.invalidate()

    def selection(self):
        return tuple(key for key in self.order if key in self.selected_keys)

    def focus(self):
        return self.selected if self.selected in self.rows else None

    def selection_set(self, keys, focus=None):
        keys = [keys] if isinstance(keys, str) else list(keys)
        selected = {key for key in keys if key in self.rows}
        focused = focus if focus in self.rows else next((key for key in keys if key in self.rows), None)
        changed = selected != self.selected_keys or focused != self.selected
        self.selected_keys = selected
        self.selected = focused
        self.anchor = focused
        self.invalidate()
        if changed:
            self.event_generate("<<TreeviewSelect>>", when="tail")

    def see(self, key):
        if key not in self.rows:
            return
        top = self.order.index(key) * ROW_HEIGHT
        current = self.body.canvasy(0)
        height = self.body.winfo_height()
        total = max(height, len(self.order) * ROW_HEIGHT)
        if top < current:
            self.body.yview_moveto(top / total)
        elif top + ROW_HEIGHT > current + height:
            self.body.yview_moveto((top + ROW_HEIGHT - height) / total)
        self.invalidate()

    def xview(self, *args):
        result = self.body.xview(*args)
        self.hide_tooltip()
        self.invalidate()
        return result

    def yview(self, *args):
        result = self.body.yview(*args)
        self.hide_tooltip()
        self.invalidate()
        return result

    def on_xscroll(self, first, last):
        self.header.xview_moveto(float(first))
        if self.xcommand:
            self.xcommand(first, last)
        self.invalidate()

    def on_yscroll(self, first, last):
        if self.ycommand:
            self.ycommand(first, last)
        self.invalidate()

    def invalidate(self):
        if self.pending is None:
            self.pending = self.after_idle(self.paint)

    def widths(self):
        widths = [self.definitions[key]["width"] for key in self.columns]
        if "notes" in self.columns and "notes" not in self.explicit_widths:
            widths[self.columns.index("notes")] += max(0, self.body.winfo_width() - sum(widths))
        return widths

    def clipped(self, text, width, font=None):
        font = font or self.text_font
        text = str(text)
        if font.measure(text) <= width:
            return text
        left, right = 0, len(text)
        while left < right:
            middle = (left + right + 1) // 2
            if font.measure(text[:middle] + "...") <= width:
                left = middle
            else:
                right = middle - 1
        return text[:left] + "..."

    def paint(self):
        self.pending = None
        if not self.winfo_exists():
            return
        widths = self.widths()
        total_width = sum(widths)
        height = max(self.body.winfo_height(), len(self.order) * ROW_HEIGHT)
        region = (0, 0, total_width, height)
        if tuple(map(float, self.body.cget("scrollregion").split())) != tuple(map(float, region)):
            self.body.configure(scrollregion=region, yscrollincrement=ROW_HEIGHT)
        self.header.configure(scrollregion=(0, 0, total_width, 34))
        self.header.delete("all")
        x = 0
        for key, width in zip(self.columns, widths):
            color = "#70d9c6" if key == "radiant" else "#e6a0a0" if key == "dire" else "#a8b9cd"
            self.header.create_text(x + 6, 17, anchor="w", text=self.clipped(self.definitions[key]["text"], width - 10, self.header_font), fill=color, font=self.header_font)
            self.header.create_line(x + width, 5, x + width, 30, fill="#3a4a5c")
            x += width
        self.header.xview_moveto(self.body.xview()[0])
        self.body.delete("all")
        self.icon_hits = []
        first = max(0, math.floor(self.body.canvasy(0) / ROW_HEIGHT))
        last = min(len(self.order), first + math.ceil(self.body.winfo_height() / ROW_HEIGHT) + 2)
        for index in range(first, last):
            key = self.order[index]
            row = self.rows[key]
            y = index * ROW_HEIGHT
            selected = key in self.selected_keys
            color = "#244c59" if selected else BG if index % 2 == 0 else "#1b2633"
            self.body.create_rectangle(0, y, total_width, y + ROW_HEIGHT, fill=color, outline="")
            text_color = "#d4ad76" if "unknown" in row["tags"] else "#70d9c6" if "league" in row["tags"] else FG
            x = 0
            for position, (column, width) in enumerate(zip(self.columns, widths)):
                if column == "rating":
                    rating = int(row["values"][position])
                    for value in range(1, 6):
                        self.body.create_text(x + 5 + (value - 1) * 17 + 8, y + 17, text="★" if value <= rating else "☆", fill="#f4c665" if value <= rating else "#8294a9", font=self.star_font, tags=("rating_star",))
                elif column in ("radiant", "dire"):
                    heroes = row["heroes"].get(2 if column == "radiant" else 3, [])[:5]
                    for slot in range(5):
                        icon_x = x + 5 + slot * 25
                        if slot < len(heroes):
                            hero = heroes[slot]
                            image = self.icons.image(hero)
                            if image:
                                self.body.create_image(icon_x, y + 5, anchor="nw", image=image, tags=("hero_icon",))
                            else:
                                self.body.create_rectangle(icon_x, y + 5, icon_x + 23, y + 29, fill="#304358", outline="")
                                self.body.create_text(icon_x + 11, y + 17, text=self.icons.name(hero)[:2], fill=FG, font=self.text_font)
                            self.icon_hits.append((icon_x, y + 5, icon_x + 24, y + 29, self.icons.name(hero)))
                        else:
                            self.body.create_text(icon_x + 11, y + 17, text="·", fill="#536479", font=self.text_font)
                    if column == "radiant" and width >= 152:
                        self.body.create_text(x + width - 13, y + 17, text="vs", fill="#96a7ba", font=self.text_font, tags=("hero_vs",))
                elif column == "tracked":
                    value = str(row["values"][position])
                    lines = [line for line in value.split("\n") if line]
                    for line_number, line in enumerate(lines[:2]):
                        color = "#70d9a0" if line.startswith("(Win) ") else "#ee9696" if line.startswith("(Loss) ") else FG
                        self.body.create_text(x + 6, y + (17 if len(lines) == 1 else 9 + line_number * 16), anchor="w", text=self.clipped(line, width - 12), fill=color, font=self.text_font, tags=("pinned_team",))
                    if value:
                        self.icon_hits.append((x, y, x + width, y + ROW_HEIGHT, value))
                else:
                    value = row["values"][position] if position < len(row["values"]) else ""
                    color = {"Radiant": "#70d9a0", "Dire": "#ee9696"}.get(value, text_color) if column == "winner" else text_color
                    self.body.create_text(x + 6, y + 17, anchor="w", text=self.clipped(value, width - 12), fill=color, font=self.text_font, tags=("winner_text",) if column == "winner" else ())
                x += width

    def header_column(self, x):
        for key, width in zip(self.columns, self.widths()):
            if x < width:
                return key
            x -= width
        return None

    def header_motion(self, event):
        if self.resizing:
            return
        edge = resize_boundary(self.columns, self.widths(), self.header.canvasx(event.x))
        self.header.configure(cursor="sb_h_double_arrow" if edge else "")

    def header_press(self, event):
        content_x = self.header.canvasx(event.x)
        key = resize_boundary(self.columns, self.widths(), content_x)
        self.pressed_column = None
        if key:
            width = self.widths()[self.columns.index(key)]
            self.resizing = (key, event.x_root, width)
            self.explicit_widths.add(key)
            self.definitions[key]["width"] = width
            self.header.configure(cursor="sb_h_double_arrow")
        else:
            self.pressed_column = self.header_column(content_x)
        return "break"

    def header_drag(self, event):
        if self.resizing:
            key, start, width = self.resizing
            self.definitions[key]["width"] = clamp_column_width(width + event.x_root - start)
            self.invalidate()
        return "break"

    def header_release(self, event):
        if self.resizing:
            self.header_drag(event)
            key = self.resizing[0]
            self.resizing = None
            if self.on_column_resize:
                self.on_column_resize(key, self.definitions[key]["width"])
        elif self.pressed_column and self.header_column(self.header.canvasx(event.x)) == self.pressed_column:
            command = self.definitions[self.pressed_column].get("command")
            if command:
                command()
        self.pressed_column = None
        self.header_motion(event)
        return "break"

    def click(self, event):
        self.body.focus_set()
        index = int(self.body.canvasy(event.y) // ROW_HEIGHT)
        if 0 <= index < len(self.order):
            key = self.order[index]
            x = self.body.canvasx(event.x)
            for column, width in zip(self.columns, self.widths()):
                if x < width:
                    if column == "rating":
                        value = rating_hit_test(x)
                        if value is not None:
                            # A rating acts on one row and retains the current multi-selection.
                            self.selection_set(self.selected_keys | {key}, focus=key)
                            if self.on_rating:
                                current = int(self.rows[key]["values"][self.columns.index("rating")])
                                self.on_rating(key, 0 if current == value else value)
                            return
                    break
                x -= width
            control = bool(event.state & (0x8 if sys.platform == "darwin" else 0x4))
            selected, anchor = selection_click(self.order, self.selected_keys, self.anchor, key, control, bool(event.state & 1))
            self.selection_set(selected, focus=key)
            self.anchor = anchor

    def choose(self, index, extend=False):
        if self.order:
            key = self.order[max(0, min(len(self.order) - 1, index))]
            selected, anchor = selection_click(self.order, self.selected_keys, self.anchor, key, shift=extend)
            self.selection_set(selected, focus=key)
            self.anchor = anchor
            self.see(key)
        return "break"

    def move_selection(self, amount, extend=False):
        index = self.order.index(self.selected) if self.selected in self.rows else -1
        return self.choose(index + amount, extend)

    def select_all(self, event=None):
        self.selection_set(self.order, focus=self.selected)
        return "break"

    def rate_focused(self, rating):
        if self.selected in self.rows and self.on_rating:
            self.on_rating(self.selected, rating)
        return "break"

    def wheel(self, event):
        self.yview("scroll", int(-event.delta / 120) * 3, "units")
        return "break"

    def horizontal_wheel(self, event):
        self.xview("scroll", int(-event.delta / 120) * 3, "units")
        return "break"

    def hover(self, event):
        x, y = self.body.canvasx(event.x), self.body.canvasy(event.y)
        text = next((name for left, top, right, bottom, name in self.icon_hits if left <= x < right and top <= y < bottom), "")
        if not text and 0 <= y < len(self.order) * ROW_HEIGHT:
            remaining_x = x
            for column, width in zip(self.columns, self.widths()):
                if remaining_x < width:
                    if column == "rating":
                        text = "Click a star to rate; click the same star again to clear. Keyboard: 0–5."
                    break
                remaining_x -= width
        if text == self.tooltip_text:
            return
        self.hide_tooltip()
        if text:
            self.tooltip_text = text
            self.tooltip = tk.Toplevel(self)
            self.tooltip.wm_overrideredirect(True)
            self.tooltip.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 18}")
            tk.Label(self.tooltip, text=text, bg="#34485e", fg=FG, padx=8, pady=4, font=self.text_font).pack()

    def hide_tooltip(self):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None
        self.tooltip_text = ""
