"""Per-client storage settings and an explicit immutable move preview."""
from datetime import date
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from library import format_size
from migration import make_plan, migrate, save_rule


class MigrationDialog(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.store = app, app.store
        self.plan = None
        self.running = False
        self.title("Long-term replay storage")
        self.geometry("970x700")
        self.minsize(760, 580)
        self.configure(bg="#10151d")
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda event: self.close())
        self.grab_set()
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Long-term storage", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="Choose any registered source folder, including existing long-term storage, and a destination.\nSave one rule per client. Nothing moves on startup or during scans. Age uses the file's last-modified date.", wraplength=900).pack(anchor="w", pady=(6, 12))
        self.client = tk.StringVar(value="modern")
        self.source = tk.StringVar()
        self.storage = tk.StringVar()
        self.before = tk.StringVar(value=date.today().isoformat())
        self.controls = []
        form = ttk.Frame(body)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        for row, label in enumerate(("Client", "Source replay folder (downloads or storage)", "Destination storage folder", "Modified before (YYYY-MM-DD)")):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        client_box = ttk.Combobox(form, textvariable=self.client, values=("modern", "classic"), state="readonly", width=12)
        client_box.grid(row=0, column=1, sticky="w")
        self.sources = ttk.Combobox(form, textvariable=self.source, state="readonly")
        self.sources.grid(row=1, column=1, sticky="ew")
        storage_entry = ttk.Entry(form, textvariable=self.storage)
        storage_entry.grid(row=2, column=1, sticky="ew")
        browse = ttk.Button(form, text="Browse...", command=self.browse)
        browse.grid(row=2, column=2, padx=(8, 0))
        before_entry = ttk.Entry(form, textvariable=self.before, width=16)
        before_entry.grid(row=3, column=1, sticky="w")
        self.controls = [(client_box, "readonly"), (self.sources, "readonly"), (storage_entry, "normal"), (browse, "normal"), (before_entry, "normal")]
        client_box.bind("<<ComboboxSelected>>", lambda event: self.load_rule())
        for variable in (self.source, self.storage, self.before):
            variable.trace_add("write", self.invalidate)
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=10)
        save = ttk.Button(actions, text="Save rule", command=self.save)
        save.pack(side="left")
        clear = ttk.Button(actions, text="Remove saved rule", command=self.clear)
        clear.pack(side="left", padx=8)
        preview = ttk.Button(actions, text="Preview migrations", command=self.preview)
        preview.pack(side="left")
        self.controls += [(save, "normal"), (clear, "normal"), (preview, "normal")]
        self.summary = tk.StringVar(value="Choose folders and a date, then preview. Saving a rule never moves files.")
        ttk.Label(body, textvariable=self.summary, wraplength=900).pack(anchor="w", pady=(0, 8))
        region = ttk.Frame(body)
        region.pack(fill="both", expand=True)
        self.details = tk.Text(region, height=8, wrap="word", bg="#18212c", fg="#e6edf5", insertbackground="#e6edf5", relief="flat", padx=10, pady=10, state="disabled")
        scroll = ttk.Scrollbar(region, command=self.details.yview)
        scroll.pack(side="right", fill="y")
        self.details.pack(fill="both", expand=True)
        self.details.configure(yscrollcommand=scroll.set)
        footer = ttk.Frame(body)
        footer.pack(side="bottom", fill="x", pady=(12, 0), before=region)
        self.confirm_button = ttk.Button(footer, text="Confirm move of previewed files", style="Accent.TButton", state="disabled", command=self.confirm)
        self.confirm_button.pack(side="right")
        self.cancel_button = ttk.Button(footer, text="Cancel", command=self.close)
        self.cancel_button.pack(side="right", padx=10)
        self.load_rule()
        self.after(50, self.cancel_button.focus_set)

    def rule(self):
        return {"client": self.client.get(), "source": self.source.get().strip(), "storage": self.storage.get().strip(), "before": self.before.get().strip()}

    def invalidate(self, *args):
        self.plan = None
        if hasattr(self, "confirm_button"):
            self.confirm_button.configure(state="disabled")
            self.summary.set("Rule changed. Preview again before moving files.")

    def load_rule(self):
        rule = self.store.get_pref("migration_rules", {}).get(self.client.get(), {})
        paths = [item["path"] for item in self.store.libraries() if item["client"] == self.client.get()]
        self.sources.configure(values=paths)
        self.source.set(rule.get("source", paths[0] if paths else ""))
        self.storage.set(rule.get("storage", ""))
        self.before.set(rule.get("before", date.today().isoformat()))

    def browse(self):
        path = filedialog.askdirectory(parent=self, title="Select existing long-term replay storage folder")
        if path:
            self.storage.set(path)

    def save(self):
        try:
            save_rule(self.store, self.rule())
            self.summary.set("Rule saved for this client. Preview and confirm whenever you want to run it.")
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror("Cannot save storage rule", str(exc), parent=self)

    def clear(self):
        rules = self.store.get_pref("migration_rules", {})
        rules.pop(self.client.get(), None)
        self.store.set_pref("migration_rules", rules)
        self.invalidate()
        self.summary.set("Saved rule removed. Replay files and library folders are unchanged.")

    def text(self, value):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", value)
        self.details.configure(state="disabled")

    def preview(self):
        if self.app.busy:
            return
        try:
            rule = save_rule(self.store, self.rule())
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror("Cannot preview migrations", str(exc), parent=self)
            return
        self.set_running(True)
        def work():
            # Refresh the source catalog explicitly; the scan itself is read-only.
            self.store.scan(cancelled=self.app.cancel.is_set)
            return make_plan(self.store, rule)
        def complete(plan):
            if not self.winfo_exists():
                return
            self.set_running(False)
            self.plan = plan
            size = sum(target.source.size for target in plan.files)
            self.summary.set(f"{len(plan.files)} files / {format_size(size)} eligible; {len(plan.errors)} refused. Review exact paths, then confirm.")
            self.text("\n\n".join(f"FROM: {target.source.path}\nTO: {target.destination}\n{target.source.size:,} bytes" for target in plan.files) + ("\n\nRefused:\n" + "\n".join(plan.errors) if plan.errors else ""))
            self.confirm_button.configure(state="normal" if plan.files else "disabled")
        self.app.run_job("Preparing replay migration preview...", work, complete)
        self.watch_job()

    def set_running(self, value):
        self.running = value
        for widget, state in self.controls:
            widget.configure(state="disabled" if value else state)
        self.confirm_button.configure(state="disabled")
        self.cancel_button.configure(text="Stop after current file" if value else "Cancel")

    def watch_job(self):
        # run_job reports exceptional failures through the app's common error path.
        if not self.winfo_exists():
            return
        if self.running and not self.app.busy:
            self.set_running(False)
        if self.running:
            self.summary.set(self.app.status.get())
            self.after(150, self.watch_job)

    def confirm(self):
        if not self.plan or self.app.busy:
            return
        plan = self.plan
        self.app.save_notes()
        self.set_running(True)
        def complete(report):
            if not self.winfo_exists():
                return
            self.plan = None
            self.set_running(False)
            summary = f"{'Stopped' if report['cancelled'] else 'Complete'}: {len(report['moved'])} moved; {len(report['failed'])} failed. Verified storage copies are retained on source-removal failure."
            self.summary.set(summary)
            self.app.status.set(summary)
            self.text(json.dumps(report, indent=2))
        self.app.run_job("Moving confirmed replay files...", lambda: migrate(self.store, plan, confirmed=True, cancelled=self.app.cancel.is_set, progress=lambda value: self.app.events.put(("progress", value))), complete)
        self.watch_job()

    def close(self):
        if self.running:
            self.app.cancel.set()
            self.summary.set("Stopping after the current file finishes safely...")
        else:
            self.destroy()
