# DotaBased Replay

A lightweight, local desktop library for Dota 2 replay files. The prototype uses
Python's Tkinter interface and SQLite; it starts and scans without any network
requests. Scanning and parsing are read-only. Permanent replay deletion is a
separate action requiring confirmation of concrete files.

## Run

Python 3.11 or newer with Tkinter starts the browser. Windows Python includes Tkinter.
Source users also build the native helper below to use Parse All; packaged builds include it.
From this repository:

```powershell
python app.py
```

You can also double-click `run.bat`, or run the compiled application at
`dist/DotaBasedReplay/DotaBasedReplay.exe` after building. The application scans
the two supplied libraries automatically on first launch:

- Modern: `G:\STEAM\steamapps\common\dota 2 beta\game\dota\replays`
- Classic: `G:\Dota2Classic\Dota2_6.88f\game\dota\replays`

Use **Libraries & clients** to add/remove folders, assign modern/classic to a
folder, or change either executable. Subfolders are included; symlinks are
skipped. Rescanning reuses unchanged files' cached summaries. Missing and invalid
files appear in **Scan details**; files without readable summary metadata remain
in the catalog. **Hide unknown recordings** is enabled by default; turn it off
to include these entries in the grid. This preference is saved locally. A
currently unavailable library keeps its last
known catalog until it can be scanned again. Removing a library removes its
catalog copies but preserves match notes and account preferences.

## Browse and annotate

- Select a replay to see heroes, teams, account IDs, outcome, provenance and notes.
  Search matches IDs, file paths, heroes, names and saved notes. Column headings
  sort the list. League matches have green text and a **League games** filter.
- The grid places **Duration** after Date, followed by **Radiant heroes** and **Dire heroes**,
  with five inline hero icons for each team and a spaced **vs** divider. Hover
  an icon for its hero name. Winner text is green for Radiant and red for Dire.
  Notes appear as a first-line preview, with literal `...` when shortened. The
  full note stays in the editor. League is the last column. Use the horizontal
  scrollbar at smaller window widths, and mouse wheel or arrow keys to navigate.
  The grid paints visible rows only, so a large catalog does not create thousands
  of hidden image widgets.
- Drag the right edge of the **Pinned Players**, **Notes** or **League** header to resize
  that column. The resize cursor marks its boundary. These widths are saved
  locally and restored on startup; dragging does not sort or change selection.
  A chosen Notes width stays fixed rather than expanding to fill spare space.
  **Duration** shows minutes and seconds and sorts numerically; unknown values
  stay last in either sort direction.
- Frequent players appear strictly above 5% presence, sorted by descending count.
  One match counts once even if multiple copies are stored. The denominator is
  every unique library entry, including unknown recordings; unidentified files
  cannot contribute player presence. The summary makes the entry/file counts
  visible.
- Pin a suggestion or **Add ID**, then assign a local **Nickname**. Click the
  first column beside a tracked player to toggle inclusion. **Only games with
  enabled accounts** uses OR: a match qualifies when any enabled account appears.
  With no enabled accounts, that filter shows no games. The pinned-player column
  shows all tracked players present, including those whose filter is disabled.
  Radiant and Dire have separate labeled, colored lines in that column; a side
  appears only when it has pinned players. With none present the cell is empty. Hover
  for full nicknames and any players whose team was not recorded.
- Notes save after a short typing pause, on focus/selection/filter changes and on
  exit. Notes and launch overrides belong to the match, so duplicate copies share
  them. OpenDota and Dotabuff buttons open the selected match in your browser.

## Full replay parsing offline

**Parse All** reads the entire library catalog, including hidden unknown
recordings, with the bundled native Go/Manta helper. No network or Dota client
is involved. One helper runs at a time. Progress shows the current file and
completed, cached and failed counts. **Stop Parsing** terminates the current
helper promptly; completed results remain saved. A later run skips successful,
unchanged files with the current helper version. Duplicate copies are parsed
once, with another copy tried if the first fails. Each file has a ten minute
timeout, then the queue continues. Parse All first refreshes the local catalog,
including new and changed files. Stop also cancels this initial scan.

**Parse Selected** uses the same offline parser and cache for only the selected
matches. Use Ctrl-click or Shift-click to select several. Selection is captured
when the batch starts; changing the grid selection does not change the queue.
Rescan first if these files have changed since the last catalog scan.

Verified post-game team hero-kill counters supply the final score; player kill
sums and the old base score field are never used. Duration uses the recorded
game start/end clock. Typed file-info messages recover available player,
identity, league and outcome fields. Missing or incomplete recordings remain
unknown rather than receiving a fabricated score. Recorded lobby enums are
shown where available; older recordings may leave Lobby unknown. Local verified
fields take priority over cached API values. Suspicious old API 0:0 placeholders
remain unknown until locally verified, without rewriting the raw API cache.
**Parse details** opens live batch progress with per-match queued, parsing,
cached, completed, incomplete, failed and stopped states. Select a row to see
its score, duration, winner, lobby, players, recorded field sources and copy
errors. The window can be opened or reopened while parsing, and includes a Stop
button. Outside a session it shows saved local results and attempts from prior
runs. Incomplete files count as unsuccessful; they never receive invented metadata.

The packaged app needs no Go or Java installation. For source development,
build the helper with `python scripts/build_parser.py` (Go 1.25+), or first run
`python scripts/bootstrap_go.py` for a SHA256-verified portable Windows toolchain.
`build.ps1` builds the helper and includes it and dependency license notices in
the application bundle. The helper source pins Manta 1.5.2 in `parser_helper/`.

## Sizes, personal ratings and selection

**Size total** shows the sum of all currently cataloged physical copies for a
match. Sizes use binary MiB (1 MiB = 1,048,576 bytes), not megabits. Select a match
to see its copy count and total; the **Copy** chooser and **Selected** label show
the individual file's size. Size sorts by actual bytes, independent of display
rounding. Rescan after outside file changes to refresh these values.

Click a star directly in the **Rating** grid column to save a personal rating
with no dialog. Click the same selected star again to clear the rating. The
column displays only five stars. While the grid has keyboard
focus, keys `0`–`5` do the same for the focused match. These local ratings belong
to the match, so duplicate copies share a rating. Existing databases gain the
rating column without replacing notes, client overrides or import provenance.

Ctrl-click (Command-click on macOS) toggles individual rows; Shift-click selects
a range. Ctrl+A selects every currently visible row. Arrow keys move focus and
Shift+arrows extend the range. The selection count appears above the grid; the
detail editor follows the focused row. Selections survive sorting and remain
selected through filtering while those rows stay visible. Clicking a star rates
only that row and retains the other selected rows. Notes are saved before focus
changes. Use horizontal scrolling to reach every column on smaller windows.

## Delete replay files

Select one or more match rows, then click **Delete selected files…**, or press
Delete while the replay grid has focus. Deletion is blocked during scans or other
background operations. Selecting a match initially lists **all of its cataloged
copies**, including copies in different libraries. The confirmation dialog
shows every exact physical path, its individual size, and the checked count and
combined size. All listed copies are initially checked; uncheck any copy to keep
it. The Cancel button has initial focus, and Escape cancels.

**Permanently delete checked files** removes only the confirmed physical `.dem`
files. It does not use the Recycle Bin and cannot undo the removal. Notes,
ratings, client overrides and import provenance remain in SQLite, even after the
last copy is removed. Cancel changes no files.

The application snapshots its catalog targets before confirmation, then checks
the library assignment, regular-file type, path containment, symlink/junction/
reparse traversal, file identity, size and modification time again before each
removal. On Windows it deletes through the validated file handle, so replacing
the pathname cannot redirect removal to a different file. Changed or refused
files remain visible and are reported; already-missing copies are marked absent.
Partial failures show the exact affected paths and error stages. No wildcard,
shell or recursive deletion is used. Other operating systems use a validated
path unlink; the Windows handle protection is specific to the Windows build.

## Import local match notes

**Import notes…** accepts the per-link annotations in a local Markdown/text file.
The chooser starts in the classic replay directory containing `matches.md`.
Plain Dotabuff/OpenDota URLs and Markdown links are accepted; separators such as
`-`, `--`, `-----` and an em dash are handled. UTF-16 with a byte-order marker,
UTF-8 and Windows-1252 text are supported. Introductory text and section comments
are not treated as match notes. Links with no annotation are skipped.

The source file is never edited. New annotations populate empty match notes;
existing notes are preserved and missing imported blocks append with source/line
provenance. A local import ledger retains each original source line and a content
fingerprint. Importing the same file repeatedly does not duplicate notes, even
when a link is repeated or moves to another line. Notes for matches not currently
in the library are retained for a future scan. An SQLite backup is created beside
the database before an import writes, and the notes/ledger update in one transaction.

For a reviewable command-line import, omit `--apply` to preview changes:

```powershell
python notes_import.py "G:\Dota2Classic\Dota2_6.88f\game\dota\replays\matches.md"
python notes_import.py "G:\Dota2Classic\Dota2_6.88f\game\dota\replays\matches.md" --apply
```

Both commands accept `--database <path>` to use an isolated catalog. Importing
does not request any match links over the network. The supplied source file has
254 unique match links: 199 annotated links and 55 bare links.

## Offline hero icons

The application bundles 127 small PNG hero icons from the official Steam CDN,
with names/IDs from the public
[OpenDota hero constants manifest](https://github.com/odota/dotaconstants/blob/master/build/heroes.json).
Icons are Valve/Dota 2 game assets; the application records their CDN URLs and
SHA-256 hashes in `assets/heroes.json`. Hero icons require no network access at
runtime. Missing images fall back to a small text tile with the full hero name
available on hover.

To refresh these public assets explicitly during development:

```powershell
python scripts/fetch_hero_icons.py
```

This downloads the generic public hero manifest and icon files from
`cdn.cloudflare.steamstatic.com`, with three concurrent requests. No replay,
match, account ID or user note is transmitted. Existing PNGs are reused. The
downloaded icons total about 651 KiB and are included in the executable bundle.

## Local metadata and API enrichment

The footer parser reads a small summary record directly, including raw Snappy
decompression. Both `PBUFDEM` and `PBDEMS2` headers are supported. It extracts
match ID, heroes, player names, SteamID-derived account IDs, teams, game mode,
duration, winner, league ID and end time when present. A nonzero league ID
identifies league play without any API request. Bot and hidden accounts are
excluded from suggestions.

Lobby type and final team kill scores are recovered by **Parse All** from the
full recorded entity stream where available. **Fetch selected metadata** and
**Enrich next 20** are optional manual fallbacks using OpenDota's public match
endpoint; league names, start time and missing winner/players may also be filled.
Verified local full parse fields take priority, followed by usable local summary
fields and cached API data. A truncated recording without sufficient final state
may remain unknown; inspect Parse details for its failure and available sources.

**Look up account on OpenDota** fetches the selected account's current name and
avatar URL metadata, cached for seven days. Local nicknames retain priority.
**Open cached avatar** opens the image in your browser; this prototype does not
render avatars inline. Hidden/private profiles can have little or no metadata.

API behavior is intentionally bounded:

- No automatic API requests during scanning or startup, and no replay uploads or
  paid parse requests. Only explicit match/profile GET requests are used.
- Requests are serialized with at least 2.1 seconds between starts, with a local
  persistent cap of 1,000 requests per UTC day. Each enrichment batch covers at
  most 20 visible matches; **Stop network batch** cancels after the active call.
- Successful match records are cached for 365 days; profiles for seven days.
  Expired metadata remains visible offline until the next explicit lookup.
  Negative 400/404 results are cached for 24 hours and skipped during batches.
- HTTP 429 persists a cooldown of at least two minutes and respects longer
  `Retry-After` values. Remaining-minute/day headers also pause requests. Network
  failures and server errors stop the batch; already fetched results remain.
  Other apps sharing the IP may consume the same upstream quota.

Protocol source: [Valve replay schema maintained by SteamDatabase](https://github.com/SteamDatabase/Protobufs/blob/master/dota2/demo.proto).
API references: [OpenDota API documentation](https://docs.opendota.com/) and
[OpenDota's rate-limit configuration](https://github.com/odota/core/blob/master/config.ts).

## Watching replays

Each library has a client assignment. **Copy** selects a physical replay when a
match exists in multiple folders. **Library default / modern / classic** provides
a persistent per-match client override. **Watch replay** starts the selected
executable with `-console +playdemo <absolute replay path>` using a safe argument
array and the executable's working directory. No shell is used and replay paths
with engine command separators are rejected.

The provided defaults point at `game\bin\win64\dota2.exe` in each client.
This does not detect the patch from a replay: the assigned library determines the
client. Compatibility still depends on that client's build, Steam availability
and whether another client is already running. Close the other Dota client when
switching versions. The launch command is tested with mocks; playback itself
requires a manual check on your machine.

## Storage and privacy

Default database: `%LOCALAPPDATA%\DotaBasedReplay\library.sqlite3` on Windows,
or `$XDG_DATA_HOME/dotabased-replay/library.sqlite3` on other platforms. It stores
library paths, file fingerprints, summaries, preferences, notes, tracked players,
personal ratings, API cache, note-import provenance and request budget. No credentials are needed. Back up that database
while the application is closed. To isolate an experiment:

```powershell
python app.py --database .validation/my-library.sqlite3
```

All settings are local. Requested API reads disclose the requested match or
account ID to OpenDota; browser links contact the corresponding website.

## Build for distribution

Runtime has no third-party Python dependencies. Install optional build tooling
in your development environment, then build on the target operating system:

```powershell
python -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File build.ps1
```

Distribute the entire `dist/DotaBasedReplay` directory; the recipient needs no
Python installation. A folder build starts faster than a self-extracting bundle.
`build.ps1 -OneFile` produces a single executable if preferred. Bundles include
Python/Tcl/Tk and are larger than the source; no Electron/browser runtime is
bundled. These are unsigned prototype builds. Build output and user data are
ignored by Git. No installer or auto-updater is included.

## GitHub releases

The **Windows release** Actions workflow builds Windows x64 on a clean hosted
runner with Python 3.12, Go 1.27.3 and the pinned build dependencies. It runs the
offline Python tests and native parser tests, builds the application, verifies
the embedded blue executable icon and packaged assets, then starts the app from
the extracted ZIP using an empty temporary database. No personal replay folders
or API credentials are used. Official Actions are pinned to immutable commits.

Push a version tag to publish a release automatically:

```powershell
git tag -a v1.0 -m "DotaBASED Replay 1.0"
git push origin main
git push origin v1.0
```

The tag must point to the intended committed source. Use a new tag for each
release; published releases are never overwritten. Tags such as `v1.1.0-beta.1`
produce prereleases; stable versions become the latest release. Publication
first creates a draft, uploads the verified ZIP and SHA-256 checksum, then makes
it public. If upload fails, the draft stays unpublished and the workflow can be
rerun. Only the publishing job has repository write permission.

For a build without publishing, run **Windows release** using **Run workflow**
and enter an artifact version. Manual runs never publish, even on a tag. Download
the `windows-x64-release` workflow artifact, containing the ZIP and checksum.

To create the same package locally after `build.ps1`:

```powershell
python scripts/package_release.py --version v1.0
Get-FileHash release/DotaBasedReplay-1.0-windows-x64.zip -Algorithm SHA256
```

Upload `release/DotaBasedReplay-1.0-windows-x64.zip` and its `.zip.sha256` file.
The archive contains one launch executable, its `_internal` runtime/helper/assets
folder, and this README. Extract everything before running `DotaBasedReplay.exe`.
The blue icon is embedded in the executable and survives downloading/extraction.
The package remains unsigned. Personal settings and cached metadata remain in
the local application-data directory when upgrading. A tagged release does not
automatically update existing installations.

## Verification

```powershell
python -m unittest discover -s tests -v
python inspect_library.py
python scripts/smoke_ui.py --screenshot .validation/ui-preview.png
python scripts/smoke_management.py --screenshot .validation/ui-management.png --modal-screenshot .validation/ui-delete-confirmation.png
python app.py --database .validation/startup.sqlite3 --smoke
```

Offline tests cover compressed/uncompressed protobuf summaries, malformed input,
Snappy copies and limits, match deduplication, cache reuse and expiration, notes
and preferences, the strict presence threshold, account filtering, launch
arguments, API quotas/backoff, and bounded batch behavior. `inspect_library.py`
uses a disposable database and prints a read-only inventory. The UI smoke uses a
disposable database, exercises selection/notes/account/league filters and can
capture just its own application window on Windows. Neither command contacts
APIs or launches Dota.

The UI smoke also checks real grid image items before/after scrolling, sorting
with selection retained, the unknown-recording toggle and a temporary import of
the supplied notes file. Additional offline tests cover note encodings, Markdown
links, delimiter variants, source preservation, backup handle cleanup, existing
notes, duplicate imports, first-line previews and unknown-match filtering.

Management tests cover additive rating migration, exact star hit regions,
multi-selection, numeric size sorting, duplicate-copy sizes, cancel, confirmed
temporary-file deletion, partial failures, stale/replaced files, junction/outside
path rejection and note/rating retention. `smoke_management.py` creates synthetic
replays in a temporary directory and captures a cancellable confirmation dialog.
It never selects the actual replay libraries. Actual deletion tests operate only
on disposable fixture files; no user replays are removed during validation.

API handling was validated with mocked responses. Live match/profile requests
were not performed during implementation; manual API and actual client playback
checks remain for the operator.

Scrollbars keep the dark palette when their content fits completely, including
disabled, hover and pressed states. The blue Replay mark reuses the website's
classic DotaBASED geometry in the header, default window/dialog icon and packaged
Windows executable. Asset provenance and optional regeneration instructions are
in `assets/README.md`; runtime branding needs no extra dependencies.

The supplied libraries were checked on 2026-10-24: 1,054 files, 1,052 unique
entries, 1,024 unique matches with player summaries and 160 league matches. Two
matches have duplicate copies. Twenty-eight auto recordings have no usable Dota
summary (one has an incomplete footer); the app retains these with scan notices.
