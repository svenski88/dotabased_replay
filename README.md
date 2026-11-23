# DotaBased Replay

Browse, organize, and watch local Dota 2 replays. The app scans and parses recordings offline, keeps notes and ratings across duplicate copies, and opens replays in your configured Dota clients.

## Install on Windows

Download the Windows x64 ZIP from [Releases](https://github.com/svenski88/dotabased_replay/releases), extract the entire archive, and run **DotaBasedReplay.exe** with its `_internal` folder beside it. The portable app is unsigned and includes its runtime. To upgrade, close the app and extract the new release into a fresh folder. Your library data stays in your Windows profile.

## Set up your library

1. Open **Libraries & clients** and replace the example paths with your own. Use **Add library…** for replay downloads and long-term storage. Each library can have its own playback client.
2. Use **Add installed client…** to select a Dota executable or **Configure new pinned client…** to install a historical Windows Source 2 build. Pinned clients go in separate folders outside Steam's library. Select **Edit client…** to assign a patch route such as `7.20`.
3. Choose **Scan libraries**. Select a match and replay copy, then choose **Watch Replay**. With **Automatic**, the app checks the saved match override, the patch route, and then the copy's library assignment. Close the running Dota client before switching builds.

The default modern Dota install is under `steamapps\common\dota 2 beta\game` in your Steam library. Look for replays in `dota\replays` and the executable at `bin\win64\dota2.exe`. See the [pinned client guide](docs/pinned-clients.md) for historical installs and replay compatibility.

## Work with replays

| Task | How |
| --- | --- |
| Find a match | Search heroes, players, notes, and parsed chat together. All terms must match the same game. Put phrases in quotes, as in `SF, CM "late comeback"`. |
| Recover match details | Use **Parse All** or **Parse Selected**. Full parsing can recover scores, duration, chat, and graphs from supported recordings. **Parse details** shows progress and errors. |
| Check the patch | A plain patch name comes from a verified Dota server-version mapping. A leading `~` marks a date estimate. Select a copy to see its replay build and Dota version when recorded. |
| Track games and players | Save notes and ratings per match. Use **Players & Accounts** to pin players, add nicknames, and filter by enabled accounts. |
| Move or remove files | Preview moves under **Libraries & clients → Migration rules…**. **Remove library** only removes the library from the catalog. **Delete selected files…** permanently deletes the physical copies you confirm. |
| Fill remaining metadata gaps | Optionally fetch OpenDota metadata for the selected match or up to 20 visible uncached matches. |

The [replay guide](docs/replay-guide.md) covers search, chat, graph controls, categories, migration, and cache recovery.

## Local data and network access

Windows stores settings, notes, ratings, tracked accounts, and caches in `%LOCALAPPDATA%\DotaBasedReplay\library.sqlite3`. Back up the database while the app is closed.

Startup, scans, and parsing work offline. Optional OpenDota lookups send the requested match or account IDs. Browser links open external sites, and DepotDownloader contacts Steam for pinned-client installs. Replay files stay local.

## Credits and licensing

**About** shows the build version, project links, and offline third-party notices. The source is publicly viewable and has no project open-source license. Dota 2 hero artwork © Valve Corporation. DotaBased Replay is an independent community project with no Valve affiliation or endorsement. TheWonderCow’s micro19 model is included with permission. The Windows ZIP includes `THIRD-PARTY-NOTICES.txt`. [Distribution notices in the source tree](third_party/distribution-notices.txt)

## Documentation

- [Pinned clients and catalog maintenance](docs/pinned-clients.md)
- [Numbered patch catalog and source audit](docs/pinned-series-heads.md)
- [Run from source, validate, build, and release](docs/development.md)

If you're reading the README from the Windows ZIP, open the [documentation on GitHub](https://github.com/svenski88/dotabased_replay/tree/main/docs).
