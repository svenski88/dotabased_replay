# Development and releases

[Back to DotaBased Replay](../README.md)

## Run from source

Use Python 3.11+ with Tkinter. Browsing works with the standard library. Install the runtime requirements for offline LightGBM win estimates. Full replay parsing requires the native Go/Manta helper, built with Go 1.25+. On Windows, `python scripts/bootstrap_go.py` can download a SHA256-verified portable Go toolchain.

```powershell
python -m pip install -r requirements-runtime.txt
python scripts/build_parser.py
python app.py
```

Use `run.bat` to start the app on Windows, or `python app.py --database .validation/my-library.sqlite3` to use a disposable database. The default Windows database is under `%LOCALAPPDATA%\DotaBasedReplay`. On other platforms the default is `$XDG_DATA_HOME/dotabased-replay/library.sqlite3`, with `~/.local/share` used when `XDG_DATA_HOME` is unset.

The native build runs Go tests and gathers third-party notices. See the [asset notes](../assets/README.md) for provenance and refresh tools.

## Build and validate

```powershell
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File build.ps1
```

The folder build bundles the native helper, Python/Tcl/Tk, and runtime assets in `dist/DotaBasedReplay/`. Distribute the entire folder. Use `build.ps1 -OneFile` to create a single executable. Build output, validation files, replays, and personal databases are ignored by Git.

| Check | Command |
| --- | --- |
| Parsing progress and cancellation | `python scripts/smoke_parser.py --screenshot .validation/ui-parser.png` |
| Library management and deletion confirmation | `python scripts/smoke_management.py` |
| File migration with synthetic replays | `python scripts/smoke_migration.py` |
| Graph UI with synthetic data | `python scripts/smoke_graphs.py` |
| Search and debounce | `python scripts/smoke_search.py` |
| Search benchmarks on synthetic catalogs | `python scripts/benchmark_search.py` |

For a read-only check against configured replay folders, use `scripts/smoke_ui.py` or `inspect_library.py` with their disposable databases. The offline checks leave Dota closed and mock API calls. Validate actual playback and live API availability separately.

Search prepares an index per catalog reload and debounces typing by 150 ms. Parsing updates the grid incrementally and keeps selection and pending notes for matches that remain visible. Helper progress alone leaves the catalog cache alone, while batches of completed results share a refresh. Ordinary parsing keeps one-second graph samples. Use `bin/replay-parser.exe --graph-probe <replay.dem>` for development-only entity property discovery. The [graph feasibility study](graph-feasibility.md) records the original compatibility investigation.

## Package and release on Windows

Build the folder distribution first, then create the ZIP and SHA256 checksum. Use the version you intend to ship.

```powershell
python scripts/package_release.py --version v1.5
Get-FileHash release/DotaBasedReplay-1.5-windows-x64.zip -Algorithm SHA256
```

Packaging verifies the x64 executable, helper, icons, and runtime assets. It excludes personal data and smoke-tests the extracted ZIP with an empty temporary database. The ZIP contains the app, its `_internal` folder and the project README. The Windows packaging smoke also verifies bundled model inference.

In GitHub Actions, use **Windows release → Run workflow** with an artifact version to test the build and attestation without publishing a release. Download the `windows-x64-release` artifact and extract its inner ZIP and checksum. Verify the inner ZIP with the [GitHub CLI](https://cli.github.com/manual/gh_attestation_verify).

```powershell
gh attestation verify DotaBasedReplay-1.5-windows-x64.zip --repo svenski88/dotabased_replay --signer-workflow svenski88/dotabased_replay/.github/workflows/release.yml --deny-self-hosted-runners
```

Replace `1.5` with the version you built. For a tagged release, add `--source-ref refs/tags/v1.5` with the corresponding tag. Attestations cover the exact ZIP built by GitHub Actions. Windows Authenticode signing is a separate step.

To publish, create a fresh tag on the reviewed release commit and push it after the commit is available on `main`. The publish job checks the checksum and verifies the ZIP's provenance against that tag before creating or updating a draft. Tags such as `v1.5-beta.1` produce prereleases. Leave published release tags and assets intact.
