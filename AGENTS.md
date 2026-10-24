# DotaBased Replay

This independent Git repository owns the local desktop replay browser. Workspace
orchestration and shared documentation remain in the parent repository. Do not
delegate recursively or edit sibling projects from this area.

Runtime is Python 3.11+ with Tkinter and SQLite from the standard library. Run
`python app.py`; `python -m unittest discover -s tests -v` checks offline logic.
`python inspect_library.py` inventories the configured default replay folders
using a disposable database. Scanning/parsing replay files is read-only. The
application also supports separately confirmed permanent deletion; never select
or delete real user replays during implementation or automated validation.
Use synthetic temporary files for destructive tests, never copy real replays
into Git. No network is required at startup or for the offline tests.

Keep user preferences, notes and cached API data outside source control. Use
`--database <path>` for isolated validation. API reads must remain explicit,
cached and rate limited; do not submit parsing jobs or launch a large collection
implicitly. Client launching must use argument arrays with `shell=False`.

Use focused tests for parser/storage/filter/API/launch changes and smoke the
desktop UI. Build with `powershell -File build.ps1` when packaging changes.
Do not commit, push, deploy, change live databases, or launch a Dota client as
part of automated verification without explicit user instructions.

The virtualized canvas grid lives in `replay_grid.py`; bundled public Steam hero
assets live in `assets/`. Keep runtime hero rendering offline. The asset refresh
script may request only generic public hero assets, never replay/account IDs.
`notes_import.py` defaults to a preview, supports BOM-encoded local source text,
and applies imports with a database backup and idempotent provenance ledger.
Never copy a user's notes file into fixtures or overwrite existing match notes.

Ratings are local per-match integers from 0 to 5. Preserve notes, client overrides
and import provenance during additive SQLite migrations. `deletion.py` builds
immutable per-copy catalog snapshots and revalidates path containment, reparse
traversal, file identity/size/mtime and catalog membership before each deletion.
Only the explicit confirmation handler may execute an approved deletion plan.
Keep confirmation Cancel-focused, show exact paths and sizes, allow per-copy
exclusions and report partial failures. No shell or recursive deletion is used.
