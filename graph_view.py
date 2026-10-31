"""Native Tk timeline drawing and compact independently collapsible side panels."""
import math
from bisect import bisect_left
import tkinter as tk
from tkinter import ttk
from graphs import smooth_signal
from ui_helpers import make_tooltip, position_tooltip

BG = "#10151d"
PANEL = "#18212c"
FG = "#e6edf5"
MUTED = "#96a7ba"
COLORS = {"net_worth_difference": "#ffd65b", "xp_difference": "#b8d5ff", "radiant_win_probability": "#a6d99a"}


def proportional_advantage(sample, resource):
    r, d = sample.get(f"radiant_{resource}"), sample.get(f"dire_{resource}")
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in (r, d)) or r + d <= 0:
        return None
    return (r - d) / (r + d)


def clock(value):
    sign = "−" if value < 0 else ""
    value = int(abs(value))
    return f"{sign}{value//60}:{value%60:02}"


class CollapsiblePanel(ttk.Frame):
    BAR = 28

    def __init__(self, parent, store, key, title, width, side="left"):
        super().__init__(parent, width=self.BAR)
        self.store, self.key, self.title, self.side = store, key, title, side
        self.expanded = bool(store.get_pref(f"{key}_expanded", False))
        saved = store.get_pref(f"{key}_width", width)
        self.expanded_width = max(200, min(700, int(saved))) if type(saved) in (int, float) and math.isfinite(saved) else width
        self.pack_propagate(False)
        self.bar = tk.Canvas(self, width=self.BAR, bg="#223040", highlightthickness=0,
                             cursor="hand2", takefocus=True)
        self.bar.pack(side=side, fill="y")
        self.content = ttk.Frame(self)
        self.grip = ttk.Frame(self, width=4, cursor="sb_h_double_arrow")
        self.bar.bind("<Configure>", lambda e: self.paint_bar())
        self.bar.bind("<Button-1>", lambda e: self.toggle())
        self.bar.bind("<Return>", lambda e: self.toggle())
        self.bar.bind("<space>", lambda e: self.toggle())
        self.grip.bind("<Button-1>", self.drag_start)
        self.grip.bind("<B1-Motion>", self.drag)
        self.grip.bind("<ButtonRelease-1>", lambda e: self.persist())
        parent.bind("<Configure>", lambda e: self.apply(), add=True)
        self.apply()

    def paint_bar(self):
        self.bar.delete("all")
        arrow = ("‹" if self.side == "left" else "›") if self.expanded else ("›" if self.side == "left" else "‹")
        self.bar.create_text(14, 17, text=arrow, fill=FG, font=("Segoe UI", 16, "bold"))
        self.bar.create_text(14, max(95, self.bar.winfo_height()/2), text=self.title,
                             angle=90, fill=FG, font=("Segoe UI", 9, "bold"))

    def apply(self):
        maximum = max(200, int(self.master.winfo_width() * .26))
        width = min(self.expanded_width, maximum) if self.expanded else self.BAR
        self.configure(width=width)
        if self.expanded:
            self.grip.pack(side="right" if self.side == "left" else "left", fill="y")
            self.content.pack(side="left", fill="both", expand=True)
        else:
            self.content.pack_forget()
            self.grip.pack_forget()
        self.paint_bar()

    def persist(self):
        self.store.set_pref(f"{self.key}_expanded", self.expanded)
        self.store.set_pref(f"{self.key}_width", self.expanded_width)

    def toggle(self):
        self.expanded = not self.expanded
        self.apply()
        self.persist()

    def drag_start(self, event):
        self.drag_origin = event.x_root
        self.drag_width = self.winfo_width()

    def drag(self, event):
        delta = event.x_root - self.drag_origin
        if self.side == "right":
            delta = -delta
        self.expanded_width = max(200, min(700, self.drag_width + delta))
        self.apply()


class ReplayGraph(ttk.Frame):
    def __init__(self, parent, icons=None):
        super().__init__(parent)
        self.icons = icons
        self.graph = None
        self.explanation = ""
        self.pending = None
        self.tooltip = None
        self.marker_hits = []
        self.marker_images = {}
        self.smoothed_percent = {}
        self.sample_times = []
        self.canvas_size = None
        legend = ttk.Frame(self)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        legend.grid(row=0, column=0, sticky="ew")
        self.visible = {}
        for field, title in (("net_worth_difference", "Gold"), ("xp_difference", "XP"),
                             ("radiant_win_probability", "Win estimate")):
            variable = tk.BooleanVar(value=True)
            self.visible[field] = variable
            style = f"Graph.{field}.TCheckbutton"
            ttk.Style(self).configure(style, foreground=COLORS[field], padding=0)
            ttk.Checkbutton(legend, text=title, variable=variable, command=self.draw,
                            style=style).pack(side="left", padx=(0, 6))
        self.canvas = tk.Canvas(self, bg="#0b1316", highlightthickness=0, height=160)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.inspection = tk.StringVar(value="Select a parsed match to view its timeline.")
        self.readout = ttk.Label(self, textvariable=self.inspection, foreground=MUTED,
                                 font=("Segoe UI", 8), width=1, anchor="w")
        self.readout.grid(row=2, column=0, sticky="ew", pady=(3, 0))
        self.readout.bind("<Enter>", self.category_tooltip)
        self.readout.bind("<Leave>", lambda event: self.hide_tooltip())
        self.canvas.bind("<Configure>", self.schedule_draw)
        self.canvas.bind("<Motion>", self.hover)
        self.canvas.bind("<Leave>", self.leave)
        self.context_menu = tk.Menu(self, tearoff=False, bg="#263544", fg=FG,
                                    activebackground="#36516a", activeforeground=FG)
        self.canvas.bind("<Button-3>", self.show_context_menu)
        self.bind("<Destroy>", self.destroyed, add=True)

    def destroyed(self, event):
        if event.widget == self:
            if self.pending is not None:
                self.after_cancel(self.pending)
                self.pending = None
            self.hide_tooltip()

    def schedule_draw(self, event=None):
        if event is not None:
            size = (event.width, event.height)
            if size == self.canvas_size:
                return
            self.canvas_size = size
        if self.pending is not None:
            self.after_cancel(self.pending)
        self.pending = self.after(60, self.draw)

    def set_graph(self, graph, explanation=""):
        self.graph = graph
        self.explanation = explanation or (graph or {}).get("category", {}).get("explanation", "")
        self.default_readout = self.explanation
        samples = (graph or {}).get("samples", [])
        self.sample_times = [sample["time"] for sample in samples]
        end = math.ceil((graph or {}).get("duration") or (samples[-1]["time"] + 1 if samples else 0))
        self.smoothed_percent = {resource: smooth_signal(samples, resource, end)[1]
                                 for resource in ("net_worth", "xp")} if samples else {}
        self.hide_tooltip()
        self.draw()

    def draw(self):
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
        c = self.canvas
        c.delete("all")
        self.marker_hits = []
        width, height = c.winfo_width(), c.winfo_height()
        samples = (self.graph or {}).get("samples", [])
        if not samples or width < 100 or height < 80:
            text = "Run Parse Selected to extract this match’s graph." if not self.graph else "Timeline unavailable in this recording."
            c.create_text(max(50, width/2), max(35, height/2), text=text, width=max(100, width-30),
                          fill=MUTED, font=("Segoe UI", 9))
            category = (self.graph or {}).get("category", {})
            prefix = category.get("label", "")
            message = (prefix + " · " if prefix else "") + (self.explanation or text)
            self.inspection.set(message)
            self.default_readout = message
            return
        left, right, top, bottom = 37, width-38, 10, height-26
        if bottom <= top:
            return
        duration = self.graph.get("duration") or samples[-1]["time"] or 1
        event_times = [e["time"] for e in self.graph.get("events", []) if e.get("time") is not None]
        start = min([0, *event_times])
        self.geometry_data = (left, right, top, bottom, start, duration)
        max_value = max((abs(s.get(field) or 0) for s in samples for field in ("net_worth_difference", "xp_difference")), default=1000)
        magnitude = 10 ** math.floor(math.log10(max(1000, max_value)))
        self.extent = max(1000, math.ceil(max_value / (magnitude/2)) * (magnitude/2))
        midpoint = (top+bottom)/2
        c.create_rectangle(left, top, right, midpoint, fill="#10201d", outline="")
        c.create_rectangle(left, midpoint, right, bottom, fill="#241619", outline="")
        for fraction in (-1, -.5, 0, .5, 1):
            y = midpoint - fraction*(bottom-top)/2
            c.create_line(left, y, right, y, fill="#56605f" if fraction == 0 else "#293536")
            value = fraction*self.extent
            label = "0" if not value else f"{abs(value)/1000:g}k"
            c.create_text(right+3, y, text=label, anchor="w", fill=MUTED, font=("Segoe UI", 8))
        c.create_text(4, top+4, text="R", anchor="nw", fill="#94cfac", font=("Segoe UI", 9, "bold"))
        c.create_text(4, bottom-4, text="D", anchor="sw", fill="#dc9393", font=("Segoe UI", 9, "bold"))
        step = max(60, math.ceil(duration / 300) * 60)
        for second in range(0, int(duration)+1, step):
            x = self.x(second)
            c.create_line(x, bottom, x, bottom+4, fill=MUTED)
            c.create_text(x, bottom+14, text=clock(second), fill=MUTED, font=("Segoe UI", 8))
        # Event columns are part of the plot, underneath all three data lines.
        self.draw_markers(top, bottom)
        for field, color in COLORS.items():
            if not self.visible[field].get():
                continue
            points, previous = [], None
            def flush():
                if len(points) >= 4:
                    c.create_line(*points, fill=color, width=1.5, tags="series")
            for sample in samples:
                value = sample.get(field)
                if value is None or (previous is not None and sample["time"]-previous > 1):
                    flush()
                    points = []
                if value is not None:
                    plot_value = (2*value-1)*self.extent if field == "radiant_win_probability" else value
                    y = midpoint - plot_value/self.extent*(bottom-top)/2
                    points.extend((self.x(sample["time"]), y))
                previous = sample["time"]
            flush()
        category = self.graph.get("category", {})
        status = category.get("label", "")
        basis = category.get("basis")
        if basis:
            status += f" ({basis})"
        missing = []
        for field, name in (("net_worth_difference", "Gold"), ("xp_difference", "XP"), ("radiant_win_probability", "win estimate")):
            if not any(s.get(field) is not None for s in samples):
                missing.append(name)
        detail = (" · Unavailable: " + ", ".join(missing)) if missing else ""
        self.default_readout = f"{status} · Win estimate: top 100%, center 50%, bottom 0%{detail}"
        self.inspection.set(self.default_readout)

    def category_tooltip(self, event):
        self.hide_tooltip()
        text = self.explanation or self.inspection.get()
        if self.graph:
            category = self.graph.get("category", {})
            details = category.get("details", {})
            if category.get("label") == "Comeback" and "deficit_start" in details:
                text += f"\nDeficit interval: {clock(details['deficit_start'])}–{clock(details['deficit_end'])}"
            elif category.get("label") == "Stomp" and "lead_start" in details:
                text += f"\nQualifying lead began: {clock(details['lead_start'])}"
            elif "ending_start" in details:
                text += f"\nEnding window: {clock(details['ending_start'])}–{clock(details['ending_end'])}"
            if details.get("resource_deficit_max", 0) > 0:
                unit = "gold" if category.get("basis") == "Gold" else "XP"
                text += f"\nWinner’s largest recorded deficit: {details['resource_deficit_max']:,.0f} {unit} at {clock(details['resource_deficit_second'])}"
            text += "\n\n" + self.graph.get("prediction", {}).get("explanation", "")
        self.tooltip = make_tooltip(self, text, event)

    def x(self, second):
        left, right, _, _, start, end = self.geometry_data
        return left + (second-start)/max(1, end-start)*(right-left)

    def draw_markers(self, top, bottom):
        left, right, _, _, _, _ = self.geometry_data
        box, step = 18, 20
        midpoint = (top + bottom) / 2
        capacity = max(0, int((midpoint - top - box - 1) // step) + 1)
        groups = {}
        for event in (self.graph or {}).get("events", []):
            if event.get("time") is None:
                continue
            team = event.get("attacker_team")
            if team not in (2, 3):
                team = event.get("target_team")
            edge = "top" if team == 2 else "bottom"
            bucket = max(0, min(int((right-left-1)//step), int((self.x(event["time"])-left)//step)))
            groups.setdefault((edge, bucket), []).append(event)
        for (edge, bucket), events in groups.items():
            events.sort(key=lambda e: (e["time"], e.get("tick", 0)))
            x = min(right - box/2, left + bucket*step + box/2)
            visible = events[:capacity]
            for index, event in enumerate(visible):
                y = top + box/2 + index*step if edge == "top" else bottom - box/2 - index*step
                color = "#79c998" if event.get("attacker_team") == 2 else "#e18e8e" if event.get("attacker_team") == 3 else "#a4adb7"
                key = str(event.get("target", "")).removeprefix("npc_dota_hero_")
                image = None
                if event["kind"] == "hero_death" and self.icons is not None:
                    original = self.icons.image(key)
                    if original is not None:
                        if key not in self.marker_images:
                            self.marker_images[key] = original.zoom(2).subsample(3)
                        image = self.marker_images[key]
                self.canvas.create_rectangle(x-9, y-9, x+9, y+9, fill="#172025", outline=color, tags="events")
                if image:
                    self.canvas.create_image(x, y, image=image, tags="events")
                else:
                    symbol = {"hero_death": "K", "tower": "T", "barracks": "B", "roshan": "R"}[event["kind"]]
                    self.canvas.create_text(x, y, text=symbol, fill=color, font=("Segoe UI", 9, "bold"), tags="events")
                hit_events = [event]
                if index == len(visible)-1 and len(events) > capacity:
                    hit_events += events[capacity:]
                    self.canvas.create_text(x+8, y, text=f"+{len(events)-capacity}", anchor="e", fill=FG,
                                            font=("Segoe UI", 7, "bold"), tags="events")
                self.marker_hits.append((x-9, y-9, x+9, y+9, hit_events))

    def hide_tooltip(self):
        if self.tooltip is not None:
            self.tooltip.destroy()
            self.tooltip = None

    def position_tooltip(self, event):
        position_tooltip(self.tooltip, self, event)

    def sample_at_x(self, x):
        samples = (self.graph or {}).get("samples", [])
        if not samples or not hasattr(self, "geometry_data"):
            return None
        left, right, _, _, start, end = self.geometry_data
        if not left <= x <= right:
            return None
        second = start + (x-left)/max(1, right-left)*(end-start)
        index = bisect_left(self.sample_times, second)
        if index == 0:
            return samples[0]
        if index == len(samples):
            return samples[-1]
        return samples[index-1] if second-self.sample_times[index-1] <= self.sample_times[index]-second else samples[index]

    def show_context_menu(self, event):
        sample = self.sample_at_x(event.x)
        if sample is None:
            return
        self.hide_tooltip()
        self.context_menu.delete(0, "end")
        tick = sample.get("replay_tick")
        if type(tick) is int and 0 <= tick <= 0xffffffff:
            command = f"demo_gototick {tick}"
            self.context_menu.add_command(label=f"Copy '{command}' console command",
                                          command=lambda text=command: self.copy_console_command(text))
        else:
            self.context_menu.add_command(label="Run Parse Selected to enable replay-tick commands", state="disabled")
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def copy_console_command(self, command):
        try:
            self.clipboard_clear()
            self.clipboard_append(command)
        except tk.TclError:
            self.inspection.set("Could not access the clipboard. Try copying again.")
            return
        self.inspection.set(f"Copied {command}")

    def hover(self, event):
        if not self.graph or not self.graph.get("samples") or not hasattr(self, "geometry_data"):
            return
        left, right, top, bottom, start, end = self.geometry_data
        self.canvas.delete("crosshair")
        if left <= event.x <= right:
            self.canvas.create_line(event.x, top, event.x, bottom, fill="#647d83", dash=(2, 3), tags="crosshair")
        sample = self.sample_at_x(event.x)
        if sample is None:
            self.hide_tooltip()
            return
        def value(field, probability=False):
            number = sample.get(field)
            return "unavailable" if number is None else f"{number:.1%}" if probability else f"{number:+,.0f}"
        def percent(resource, smoothed=False):
            number = self.smoothed_percent.get(resource, {}).get(sample["time"]) if smoothed else proportional_advantage(sample, resource)
            return "unavailable" if number is None else f"{number:+.1%}"
        self.inspection.set(f"{clock(sample['time'])} | Gold {value('net_worth_difference')} ({percent('net_worth')}) | XP {value('xp_difference')} ({percent('xp')}) | Win {value('radiant_win_probability', True)}")
        text = (f"{clock(sample['time'])} (Radiant minus Dire)\n"
                f"Gold advantage: {value('net_worth_difference')} ({percent('net_worth')})\n"
                f"XP advantage: {value('xp_difference')} ({percent('xp')})\n"
                f"Radiant win estimate: {value('radiant_win_probability', True)}\n\n"
                f"30-second median: Gold {percent('net_worth', True)}, XP {percent('xp', True)}\n"
                "Advantage percentages = team difference / combined team resources.")
        for x1, y1, x2, y2, events in reversed(self.marker_hits):
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                lines = []
                for entry in events:
                    credit = {2: "Radiant", 3: "Dire"}.get(entry.get("attacker_team"), "Unattributed")
                    lines.append(f"{clock(entry['time'])} | {entry['kind'].replace('_',' ')} | {credit}\n{entry.get('attacker') or '?'} -> {entry.get('target') or '?'}")
                text += "\n\nEvents (exact times):\n" + "\n\n".join(lines)
                break
        if self.tooltip is None:
            self.tooltip = make_tooltip(self, text, event)
        else:
            label = self.tooltip.winfo_children()[0]
            if label.cget("text") != text:
                label.configure(text=text)
            self.position_tooltip(event)

    def leave(self, event=None):
        self.canvas.delete("crosshair")
        self.hide_tooltip()
        if hasattr(self, "default_readout"):
            self.inspection.set(self.default_readout)
