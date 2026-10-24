"""Concrete per-copy permanent-delete confirmation; cancelling has no side effects."""
import tkinter as tk
from tkinter import ttk

from library import format_size


class DeleteDialog(tk.Toplevel):
    def __init__(self, parent, plan):
        super().__init__(parent)
        self.plan = plan
        self.result = None
        self.title("Confirm permanent replay deletion")
        self.configure(bg="#10151d")
        self.geometry("900x610")
        self.minsize(680, 460)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", self.cancel)
        ttk.Label(self, text="Permanently delete replay files?", font=("Segoe UI", 17, "bold"), foreground="#f0aaa4").pack(anchor="w", padx=20, pady=(18, 10))
        ttk.Label(self, text="Checked .dem files will be permanently removed from disk. This does not use the Recycle Bin.\nMatch notes, ratings and imported annotations will be kept.", wraplength=840).pack(anchor="w", padx=20)
        ttk.Label(self, text="All listed copies are checked by default. Uncheck any individual copy you want to keep.", style="Muted.TLabel", wraplength=840).pack(anchor="w", padx=20, pady=10)
        footer = ttk.Frame(self, padding=(20, 14))
        footer.pack(side="bottom", fill="x")
        self.total = tk.StringVar()
        ttk.Label(footer, textvariable=self.total).pack(side="left")
        self.delete_button = ttk.Button(footer, text="Permanently delete checked files", style="Danger.TButton", command=self.confirm)
        self.delete_button.pack(side="right", padx=(10, 0))
        self.cancel_button = ttk.Button(footer, text="Cancel", command=self.cancel)
        self.cancel_button.pack(side="right")
        region = ttk.Frame(self, padding=(20, 0))
        region.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(region, background="#18212c", highlightthickness=0)
        scroll = ttk.Scrollbar(region, orient="vertical", command=self.canvas.yview)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        rows = ttk.Frame(self.canvas, padding=12)
        window = self.canvas.create_window(0, 0, window=rows, anchor="nw")
        rows.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))
        self.choices = {}
        self.path_labels = []
        for target in plan.files:
            row = ttk.Frame(rows, padding=(0, 6))
            row.pack(fill="x")
            selected = tk.BooleanVar(value=True)
            self.choices[target.path] = selected
            ttk.Checkbutton(row, variable=selected, command=self.update_total).pack(side="left", anchor="n")
            path = ttk.Label(row, text=f"{target.path}\n{format_size(target.size)}  ({target.size:,} bytes)" + (" · already missing" if target.identity is None else ""), wraplength=760, justify="left")
            path.pack(side="left", fill="x", expand=True)
            self.path_labels.append(path)
        if plan.errors:
            ttk.Label(rows, text="These files are refused and will not be deleted:", foreground="#f0aaa4").pack(anchor="w", pady=(12, 6))
            for error in plan.errors:
                label = ttk.Label(rows, text=error, wraplength=760, foreground="#e6b98c", justify="left")
                label.pack(anchor="w", pady=4)
                self.path_labels.append(label)
        self.bind("<Configure>", self.resize_paths)
        self.update_total()
        self.after(50, self.cancel_button.focus_set)
        self.grab_set()

    def resize_paths(self, event):
        if event.widget == self:
            for label in self.path_labels:
                label.configure(wraplength=max(400, self.winfo_width() - 110))

    def selected_paths(self):
        return tuple(path for path, selected in self.choices.items() if selected.get())

    def update_total(self):
        selected = set(self.selected_paths())
        size = sum(target.size for target in self.plan.files if target.path in selected)
        self.total.set(f"{len(selected)} / {len(self.plan.files)} files checked · {format_size(size)}\n{size:,} bytes total")
        self.delete_button.configure(state="normal" if selected else "disabled")

    def confirm(self):
        if self.selected_paths():
            self.result = self.plan.subset(self.selected_paths())
            self.destroy()

    def cancel(self, event=None):
        self.result = None
        self.destroy()

    def show(self):
        self.wait_window()
        return self.result
