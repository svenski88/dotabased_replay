"""Per-client startup commands and opt-in compatibility presets."""

import tkinter as tk
from tkinter import ttk

from replay_app.library import startup_console_args


def chat_wheel_commands(start, phrases):
    return tuple(f"chat_wheel_phrase_{slot} {phrase}" for slot, phrase in enumerate(phrases, start))


# 7.32e client defaults. Resetting the first wheel was verified against the Settings crash.
PRESETS = {
    "7.32e": {
        "primary_chat_wheel": (
            "Reset primary chat wheel",
            "Restores the eight stock phrases. Verified to fix the Settings crash.",
            chat_wheel_commands(0, (8, 1, 2, 3, 4, 5, 6, 7)),
        ),
        "secondary_chat_wheel": (
            "Reset secondary chat wheel",
            "Restores the stock phrases for slots 9 through 16. Optional compatibility test.",
            chat_wheel_commands(8, (65, 69, 79, 66, 80, 61, 62, 70)),
        ),
    },
}


def preference_key(client):
    return f"client_startup_commands/{client}"


def startup_profile(store, client):
    saved = store.get_pref(preference_key(client), "")
    if isinstance(saved, str):
        return saved, ()
    return saved["commands"], saved["presets"]


def commands_for_client(store, client):
    custom, enabled = startup_profile(store, client)
    commands = [
        command
        for key, (_, _, preset) in PRESETS.get(client, {}).items()
        if key in enabled
        for command in preset
    ]
    if custom:
        commands.append(custom)
    return "; ".join(commands)


def open_startup_commands(parent, store, client):
    custom, enabled = startup_profile(store, client)
    dialog = tk.Toplevel(parent)
    dialog.title(f"Startup console commands for {client}")
    dialog.transient(parent)
    dialog.bind("<Escape>", lambda event: dialog.destroy())
    body = ttk.Frame(dialog, padding=18)
    body.pack(fill="both", expand=True)

    toggles = {}
    if presets := PRESETS.get(client):
        ttk.Label(body, text="Recommended commands", style="Section.TLabel").pack(anchor="w")
        for key, (label, description, _) in presets.items():
            variable = toggles[key] = tk.BooleanVar(dialog, key in enabled)
            ttk.Checkbutton(body, text=label, variable=variable).pack(anchor="w", pady=(6, 0))
            ttk.Label(body, text=description, style="Muted.TLabel", wraplength=465).pack(anchor="w", padx=(22, 0))
        ttk.Label(body, text="Chat-wheel changes can carry over to modern Dota through shared Steam settings.",
                  wraplength=465).pack(anchor="w", pady=(8, 12))

    ttk.Label(body, text="Custom commands", style="Section.TLabel").pack(anchor="w")
    ttk.Label(body, text="Enter one command per line, such as volume 0.07. Custom commands run after any presets.",
              wraplength=465, style="Muted.TLabel").pack(anchor="w", pady=(4, 6))
    commands = tk.Text(body, width=58, height=6, wrap="word", padx=8, pady=5,
                       bg="#18212c", fg="#e6edf5", insertbackground="#e6edf5")
    commands.pack(fill="both", expand=True)
    commands.insert("1.0", "\n".join(part.strip() for part in custom.split(";") if part.strip()))

    status = tk.StringVar(dialog)
    ttk.Label(body, textvariable=status, wraplength=465).pack(anchor="w", pady=(5, 0))

    def save():
        text = "; ".join(line.strip() for line in commands.get("1.0", "end-1c").splitlines() if line.strip())
        try:
            startup_console_args(text)
        except ValueError as exc:
            status.set(str(exc))
            return
        store.set_pref(preference_key(client), {
            "commands": text,
            "presets": [key for key, variable in toggles.items() if variable.get()],
        })
        dialog.destroy()

    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(10, 0))
    ttk.Button(actions, text="Save commands", style="Accent.TButton", command=save).pack(side="right")
    ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side="right", padx=(0, 8))
    dialog.grab_set()
    commands.focus_set()
    return dialog

