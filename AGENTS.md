# DotaBased Replay

This independent Git repository owns the local desktop replay browser. Workspace
orchestration and shared documentation remain in the parent repository. Do not
delegate recursively or edit sibling projects from this area.

Runtime is Python 3.11+ with Tkinter and SQLite from the standard library. Run
`python app.py`; `python -m unittest discover -s tests -v` checks offline logic.
Full parsing uses the bundled native Go/Manta helper in `parser_helper/`.
`python scripts/build_parser.py` runs Go tests, builds `bin/replay-parser.exe`
and collects third-party licenses; `build.ps1` includes both in the app bundle.
Source builds need Go 1.25+ (or `scripts/bootstrap_go.py`); end users do not.
`local_parser.py` serializes helper processes, enforces a ten minute file timeout,
and kills the active helper on Stop/close. Clear cancellation before launching
the worker, never inside its entry point. Default Parse All refreshes the catalog
first, includes hidden recordings, caches complete results by file size/mtime
and helper version, and commits incrementally. Keep verified game-clock duration
and team hero-kill score distinct from summary playback time/API placeholders;
do not infer final score from player kill sums or overwrite identities with zeros.
Parse Selected passes a fixed catalog subset through the same queue. The live
progress model/window is in `parse_progress.py`; keep helper events keyed by
match and path, with explicit cached/completed/error outcomes. Update it from
the main UI event queue, never by rereading SQLite on every progress tick.
Use `scripts/smoke_parser.py --screenshot .validation/ui-parser.png` for synthetic
offline UI progress/Stop validation, with optional `--geometry 1100x720`.
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
