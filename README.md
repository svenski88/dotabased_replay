# DotaBased Replay

A local desktop library for Dota 2 replay files: browse matches, track players,
save notes and ratings, recover recorded match details, inspect match graphs and
automatic game-shape categories, and open replays in the
right Dota client. Scanning and full parsing work offline and read replay files
without changing them.

## Download and install on Windows

1. Open [Releases](https://github.com/svenski88/dotabased_replay/releases) and download the Windows x64 ZIP from the release assets.
2. Extract the **entire ZIP** into a folder you want to keep, such as `C:\Tools\DotaBasedReplay`.
3. Open the extracted `DotaBasedReplay` folder and run **DotaBasedReplay.exe**.
4. Keep the `_internal` folder beside the executable; it contains the runtime, parser and offline hero icons.

This is a portable, unsigned Windows application: there is no installer and you
do not need Python, Go or Java. Run the extracted executable rather than opening
it inside the ZIP. To upgrade, close the app, extract the new release into a new
folder, and launch it there; your local settings and annotations are retained.
Updates are downloaded manually.

## Connect your replay folders and Dota clients

The app's initial paths are examples from the development machine. Replace them
with your own folders and executables before watching replays.

1. Open **Libraries & clients** and use **Remove selected** for example folders you do not use; this removes their catalog entries, not replay files.
2. Choose **modern** or **classic** in the folder dropdown, click **Add folder…**, and select a folder containing your `.dem` replays.
3. To change an existing folder's assignment, select its row, choose **modern** or **classic**, then click **Apply client to selected**.
4. Under **Dota client executables**, use **Browse…** beside **Modern** and **Classic** to select each installed game's actual executable.
5. Click **Save & scan** to save executable paths and scan your libraries.

Modern Steam installations usually store replays under
`<SteamLibrary>\steamapps\common\dota 2 beta\game\dota\replays` and run
`<SteamLibrary>\steamapps\common\dota 2 beta\game\bin\win64\dota2.exe`.
For an old client, browse inside **your separate classic installation**: its
executable may be named `dota.exe` or `dota2.exe`. Select the game executable,
not a downloader or community launcher. Add its replay folder separately and
assign it **classic**. Subfolders are scanned automatically.

For classic client setup, see [Dota 2 Classic](https://dota2classic.com/) and its
[manual installation guide](https://dota2classic.com/Download/Manual). For a
broad starting point for **pre-7.00 Source 2 replays**, we recommend **6.88f**,
the final pre-7.00 patch. Choose the Source 2 client and depot manifests for that
version when following the guide; the site's standard download focuses on
**Source 1 6.84**, so it is a different build.

Playback compatibility depends on the replay's recorded build: 6.88f cannot be
guaranteed to play every older replay, including Source 1 recordings. Keep
different game versions in separate directories. The app follows your library
assignment rather than detecting and installing a matching patch; close another
Dota client before switching versions.

## Recommended workflow

1. **Save & scan** — configure folders and clients, then build the initial catalog from local replay summaries.
2. **Parse All** — recover as much match metadata as possible offline before making API requests; wait for it to finish or use **Stop Parsing**.
3. **Parse details** — inspect incomplete or failed recordings and the fields recovered; missing final state can leave score, duration or outcome unknown.
4. **Optional: Fetch selected metadata / Enrich next 20** — use OpenDota to fill remaining gaps for the focused match or up to 20 visible uncached matches with known IDs.
5. **Watch replay** — select a match, choose its **Copy** and **Library default / modern / classic** client, then launch playback.

Full parsing includes hidden unknown recordings, refreshes the catalog first,
and caches successful results by file size, modification time and parser version.
Completed work survives stopping; retrying skips unchanged successes. Local
verified metadata takes priority over API data. An incomplete recording or an
unavailable API match may still have unknown fields after both steps.

## Quick user guide

- **Rescan library** — discover new or changed files and refresh fast summaries; unavailable folders retain their previous catalog until accessible.
- **Scan details** — inspect missing folders, unreadable summaries and scan errors.
- **Search** — all terms must match the same game. Separate terms with spaces or commas: `SF, CM comeback` finds games matching both heroes and “comeback”. Search includes recorded player names/IDs, your local player nicknames (even when their account filter is disabled), hero display/internal names, DotaBASED aliases and abbreviations, replay paths, match metadata and saved/imported notes. Use double quotes for phrases: `"Shadow Fiend", "late comeback"`. Matching ignores case; metadata matching also normalizes accents, punctuation and underscores. Short terms such as `AM` match whole words, avoiding accidental matches inside longer text. Ambiguous abbreviations such as `ES` match either corresponding hero. All fields share the search, so a hero mentioned in notes can also satisfy a term. Literal `and` is ordinary search text, not an operator.
- **League games** — show only matches with a recorded or enriched league ID.
- **Hide unknown recordings** — hide entries without usable match/player information; enabled by default.
- **Select matches** — click one row, Ctrl-click to toggle more, Shift-click for a range, or Ctrl+A for all visible rows.
- **Sort** — click a column heading; Duration and Size sort numerically, with unknown durations last.
- **Navigate** — use the scrollbars, mouse wheel or arrow keys; Shift+arrows extend selection.
- **Resize columns** — drag the right header edge of Pinned Players, Notes or League; widths are saved.
- **Heroes / Winner** — hover offline hero icons for names; Winner uses green for Radiant and red for Dire.
- **Size total / Copy** — see all copies' combined size in MiB, then choose the individual physical file to watch.
- **Rating** — click one of five stars, click the same star again to clear, or press `0`–`5` while the grid has focus.
- **Match notes** — edit the selected match's notes; they save automatically and are shared across duplicate copies.
- **Import notes…** — import annotated Dotabuff/OpenDota links from local text or Markdown, preserving existing notes and backing up the database.
- **Frequent players > 5%** — discover players present in strictly more than 5% of unique catalog entries, counting duplicate copies once.
- **Pin selected player / Add ID** — track a suggested player or enter a Steam account ID manually.
- **Nickname / Unpin** — save a local player label or remove that player from your tracked list.
- **Filter checkbox** — toggle an account's participation in the enabled-account filter without hiding it from Pinned Players.
- **Only games with enabled accounts** — keep matches containing any enabled account; no enabled accounts means no matches.
- **Pinned Players** — show present tracked players per team: green `(Win)`, muted red `(Loss)`, neutral for unknown outcomes; hover for full names and unknown teams.
- **Parse All / Parse Selected** — run the offline native parser on the whole catalog or the selected matches only.
- **Chat log** — view recorded messages in the scrollable pane beside players and match notes after a successful full parse. Messages show the recorded speaker, channel and game clock when available (otherwise the replay tick). Run **Parse Selected** again for previously parsed games after upgrading to the chat-capable parser. Only chat actually stored in a supported Source 2 recording is available; team/private chat may be absent, and unsupported or incomplete recordings may not produce a log. Chat is cached locally and included in library search after parsing; combine chat words or quoted phrases with heroes, players and notes.
- **Stop Parsing** — stop the current helper and queue, retaining completed results for the next run.
- **Parse details** — view live progress, saved results, field sources and per-copy errors; select a row for details.
- **Fetch selected metadata** — request cached/public OpenDota metadata for the focused match with a known match ID.
- **Enrich next 20 / Stop network batch** — fetch up to 20 visible uncached matches or stop after the active request finishes.
- **Look up account on OpenDota / Open cached avatar** — fetch a player's public profile metadata or open the cached avatar URL in your browser.
- **OpenDota / Dotabuff** — open the focused match's page in your browser.
- **Watch replay** — launch your configured game executable with `-console -novid -gamestateintegration` and `+playdemo` for the chosen replay; the per-match client override is saved.
- **Copy Match ID** — copy the selected replay's match ID using the button beside its detail heading. Disabled when no replay is selected or its match ID is unknown.
- **Delete selected files…** — review exact physical copies, uncheck any to keep, then confirm permanent deletion; Cancel changes no files.

Deletion bypasses the Recycle Bin and cannot be undone. Match notes, ratings and
client overrides survive removal of replay copies. **Remove selected** in library
settings only removes a folder from the catalog; it does not delete its files.

## Match graphs and categories

**Parse All / Parse Selected** now also extracts offline graph data. Existing
metadata-only cache entries gain timelines on the next explicit parse. Match
selection loads only that match's compressed graph, keeping inventory filtering
lightweight. Completed graphs and derived results survive stopping a queue;
changing the model or category rules lets parsing reuse compatible cached features.

The **Players & Accounts** bar at the left and **Chat Log** bar at the right
expand/collapse independently. Both start collapsed. Their state and expanded
widths are remembered; drag an expanded panel's inner border to resize it. Expanded
chat spans the main body height. The inventory/details divider is also adjustable
and remembered. At narrow widths, players and notes stack beside the graph.
Search, league/unknown filters and category selection share one row; hover for
their guides. Parsing, enrichment and deletion share the action row above the grid.
Copy/client controls, Match tools and the OpenDota/Dotabuff icon links share the
match heading row, with **Watch Replay** fixed at the right. Narrow action rows
provide horizontal scrolling so controls remain accessible with both panels open.

The graph occupies the former chat area. Gold and XP are Radiant-minus-Dire
advantages on a common symmetric raw-value axis. The green **Win estimate** line
uses the same plot space with 100% at the top, 50% at neutral and 0% at the bottom.
Hover to see actual units/probability, proportional gold/XP advantages and their
30-second medians. Percentages divide the Radiant-minus-Dire difference by the
combined team resource total, matching the category rules. Legend checkboxes hide
individual lines. Radiant-credited kills appear at the top and Dire-credited kills
at the bottom; grey markers retain unattributed deaths. Towers, barracks and Roshan
have distinct markers. Events occupy aligned columns inside the chart, stacking
inward from each edge beneath the data lines. Boxes are collapsed only when a
column would reach the neutral center; its final box shows the overflow count,
with exact event times retained in the tooltip. Windows tooltips use the monitor
under the pointer, including displays with negative desktop coordinates.

Right-click a graph time and choose **Copy 'demo_gototick N' console command**
to copy a seek command for the nearest recorded one-second graph sample. Paste
it into the Dota client console. The command uses the actual replay packet tick,
including pregame and pause offsets, rather than multiplying game time by 30.
Run **Parse Selected** once after upgrading to add tick mappings to older cached
graphs; their menu explains this until the mapping is available.

The local **micro19** model is used for both league and non-league recordings.
Missing player NW or building state leaves its estimate unavailable. Older replay
builds may still have XP/event graphs without direct NW or win estimates. These
are model estimates, not Valve's curve; the supplied artifact has an unresolved
training-label/feature-range discrepancy documented in [models/README.md](models/README.md).
No online lookup or model training happens during parsing.

Each match receives one automatic category, independent of win estimates:

- **Comeback**: eventual winner trails by 10% of combined team resources for at
  least two minutes after minute five, then wins. Takes precedence over other shapes.
- **Stomp**: winner sustains a 7.5% lead for two minutes by minute 10 and maintains
  dominance afterward, allowing only brief dips without a sustained recovery.
- **Close Game**: at least 60% of the window from five minutes before the finish
  to one minute before it stays within +/-5%. Large earlier swings are allowed.
- **Other**: sufficient data without one of those shapes, including dominance
  established too late for Stomp.
- **Insufficient data / Not parsed**: distinguish unavailable evidence from graphs
  that have not yet been extracted.

Category rules use a trailing 30-second median and at least 95% resource coverage.
They use gold first, with **XP fallback** when direct NW is unavailable; that basis
and the qualifying interval are available in the graph readout's hover explanation.
Use the category column/filter alongside existing text, account and league filters.

Developer verification: `python scripts/smoke_graphs.py` exercises synthetic offline
UI states and writes three screenshots under ignored `.validation/graph-ui/`.
The Windows package smoke also runs an independent golden inference check.

## Local data and optional network access

Windows stores settings, notes, ratings, tracked accounts and caches in
`%LOCALAPPDATA%\DotaBasedReplay\library.sqlite3`; back it up while the app is
closed. On other platforms, the location is
`$XDG_DATA_HOME/dotabased-replay/library.sqlite3` (defaulting to `~/.local/share`).
Replacing the application folder does not replace this database.

Startup, scans and full parsing make no API requests and never upload replays.
Optional match/profile lookups send the requested IDs to OpenDota; browser links
and avatar URLs contact their websites. No API key is required. Requests are
serialized at least 2.1 seconds apart, capped locally at 1,000 per UTC day, and
pause on rate limits. Successful matches are cached for 365 days and profiles
for seven days; expired data remains visible offline. Private profiles and
unavailable matches may have no additional information.

## Run from source

Developers need Python 3.11+ with Tkinter; the app has no third-party Python
runtime dependencies for browsing; install `requirements-runtime.txt` for offline
LightGBM win estimates. Windows Python includes Tkinter. Build the native helper
with Go 1.25+ before full parsing (or use `python scripts/bootstrap_go.py` to
download a SHA256-verified portable Windows toolchain).

```powershell
python -m pip install -r requirements-runtime.txt
python scripts/build_parser.py
python app.py
# Optional: use an isolated database for development.
python app.py --database .validation/my-library.sqlite3
```

`run.bat` also starts the source app. `parser_helper/` pins Go/Manta dependencies;
the build script tests it and gathers third-party notices. See
[assets/README.md](assets/README.md) for offline asset provenance and refresh tools.

## Build and verify

```powershell
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File build.ps1
python scripts/smoke_parser.py --screenshot .validation/ui-parser.png
```

`build.ps1` runs native tests and bundles the helper, Python/Tcl/Tk and assets in
`dist/DotaBasedReplay/`; launch `dist/DotaBasedReplay/DotaBasedReplay.exe` and
distribute the entire folder. `build.ps1 -OneFile` creates a single executable
instead. Build output, replay files and personal databases are ignored by Git.

Offline tests cover parsing, cache precedence, filters, notes, ratings, selection,
deletion safety and API behavior with mocks. The parser UI smoke uses disposable
synthetic fixtures; `scripts/smoke_management.py` similarly tests management and
the confirmation dialog. `scripts/smoke_ui.py` and `inspect_library.py` read the
configured default replay folders using disposable databases. No automated check
launches Dota; actual playback and live API availability require manual testing.

Search prepares its metadata index once per catalog reload and waits 150 ms
after the last keystroke before filtering, so typing bursts produce one redraw.
Notes and ratings update without rebuilding the metadata index. Run
`python scripts/smoke_search.py` for synthetic search/debounce UI checks, or
`python scripts/benchmark_search.py` for index preparation and warm query
timings on 1,000- and 5,000-game synthetic catalogs. Neither reads user replays.

While parsing, committed matches refresh in the grid without waiting for the
queue to finish. Current filters and sorting apply to the updated metadata;
selection, pending notes and the selected replay copy are retained where the
match remains visible. A selected match's graph refreshes when its parse finishes.
Cached-result bursts share one catalog refresh per UI poll, and ordinary helper
progress ticks do not reload the catalog. Unchanged matches reuse prepared search
documents. Browsing remains available during parsing.

Normal parsing retains one-second graph samples but skips development-only
entity property discovery. `bin/replay-parser.exe --graph-probe <replay.dem>`
still includes that discovery for compatibility investigations. Existing cached
results remain valid. Graph hover reuses its tooltip window and finds samples
with a binary search to reduce work while moving the mouse.

## Package and publish a release

After a local folder build, create a ZIP and checksum with:

```powershell
python scripts/package_release.py --version v1.1.0
Get-FileHash release/DotaBasedReplay-1.1.0-windows-x64.zip -Algorithm SHA256
```

Packaging validates the x64 executable/helper, icons and assets, excludes personal
data, and smoke-tests the extracted ZIP with an empty temporary database. The
archive contains the executable, `_internal` folder and this README.

The **Windows release** GitHub Actions workflow tests and builds Windows x64.
Use **Run workflow** with an artifact version for a build without publishing;
download the `windows-x64-release` artifact containing the ZIP and checksum.
To publish, commit the reviewed source, create a new version tag on that commit,
and push the branch and tag:

```powershell
git tag -a v1.1.0 -m "DotaBased Replay 1.1.0"
git push origin main
git push origin v1.1.0
```

Tag pushes publish a release after verified assets are uploaded through a draft;
prerelease tags such as `v1.1.0-beta.1` produce prereleases. Use a fresh version
for every release and keep published releases unchanged. Manual workflow runs
never publish. End users download and extract the ZIP from Releases to upgrade.
