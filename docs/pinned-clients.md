# Pinned Dota clients

[Back to DotaBased Replay](../README.md) · [Numbered patch audit](pinned-series-heads.md)

## Choose and install a client

Keep game versions in separate folders. A patch route such as `7.20` covers the letter patches in that series. A catalog selection such as **7.40 series** selects its designated recipe, while **7.40** selects the base-patch recipe. An exact letter patch requires its own catalog entry.

The catalog includes **6.88f**, the final pre-7.00 Source 2 patch. It is a starting point for replay compatibility in that era. Source 1 recordings need a separate client and are outside this catalog. If following the [Dota 2 Classic manual](https://dota2classic.com/Download/Manual), select the Source 2 files for 6.88f. The older app profile named **classic** migrates to **6.88f** when it points to a `Dota2_6.88f` installation.

1. Get the Windows x64 executable from the [DepotDownloader releases](https://github.com/SteamRE/DepotDownloader/releases).
2. Open **Libraries & clients → Configure new pinned client…**. Select a patch or series, or use **Import recipe…** to open an existing JSON recipe. Choose an existing parent folder outside Steam's libraries and select the DepotDownloader executable.
3. Enable QR sign-in if anonymous Steam access is unavailable. DepotDownloader authenticates and fetches the exact manifests from Steam. The app verifies the downloaded build, registers its executable, and adds the series route.
4. Test a replay from the target patch. For troubleshooting, the menu next to **Watch Replay** can launch the client to its main menu with the selected launch settings.

The installer resumes partial downloads in a sibling `.installing` folder when run again with the same recipe. It validates the manifests, key game files, and server version before finalizing the install. It creates no Steam installation record. The replay app launches the pinned executable directly and enables its console log.

**Suppress the pinned client's update prompt** adjusts the pinned client's `game/dota/steam.inf`. The installer saves the original as `steam.inf.replay-original` beside it and uses that original for subsequent verification. For an app-installed build, rerun **Install client** with the same recipe and parent to change that setting without downloading again. Clear the checkbox or use `--keep-update-prompt` to restore the original.

From the repository root, the equivalent installer accepts a recipe and downloader path:

```powershell
python client_install.py --recipe assets/client_7.20e.json --parent 'D:\PinnedDota' --depot-downloader 'C:\Tools\DepotDownloader.exe' --qr
```

Use `--preflight` to check access to the manifests before installation. The bundled 7.20e recipe is the compatibility-tested build `3391106`, Dota version `3283`. The final 7.20e build `3500444` has a [separate importable recipe](../assets/build_manifests/client_7.20e_build_3500444.json).

## Create a recipe

1. Identify the public Steam Build ID. To represent a numbered series, use the last public build before the next numbered release.
2. Choose **Create recipe…** in the installer. Enter the Build ID and eight Windows and content depot manifest IDs. **Import saved HTML…** accepts saved build pages, including earlier pages for manifests carried forward into the target build. **Import browser capture…** accepts an existing build capture JSON.
3. Enter the gameplay patch and use **Read steam.inf…** on the original `game/dota/steam.inf` from the target build to fill in its Dota `ServerVersion`.
4. Use **Save recipe…** to validate the fields and use the JSON in the installer. Keep manifest IDs as strings when editing JSON. A build that uses a different depot layout requires a custom recipe.

## Maintain the bundled catalog

The [pinned catalog](../assets/pinned_client_catalog.json) stores each patch, Steam build, Dota server version, its depot manifests, and sources. The [numbered patch audit](pinned-series-heads.md) documents the checked release boundaries. Verify manifest access and game playback separately from the metadata review.

```powershell
python scripts/update_client_catalog.py --add-recipe path/to/client_7.40b.json
python scripts/update_client_catalog.py --add-capture path/to/capture.json --patch 7.40b --steam-inf path/to/steam.inf
```

Use `--series SERIES=PATCH` to assign a reviewed recipe as the series default. For bulk updates, pair `--snapshot-history history.json` with `--patch-windows windows.json`. Both files are JSON arrays.

- Each window has `patch`, `first_build`, and `next_build`. Use observed public build IDs for both boundaries.
- Each history record has `steam_build`, timezone-qualified `published_at`, `server_version`, a complete Windows `depots` mapping, and `sources`. Alternatively, supply the archived Steam PICS `appinfo` for app 570 with the server version and sources.
- The script selects the last observed public build strictly before the next boundary. Check coverage around both boundaries and the final build, especially when several builds share a date. Confirm the version using the target build's original `steam.inf`.

The catalog uses [archived public Steam app info](https://gitea.com/Sainan/steam-pics) and [archived Dota files](https://github.com/SteamTracking/GameTracking-Dota2) where available. Review the catalog diff before publishing.

The [patch server version map](../assets/patch_server_versions.json) is used for replay patch labels. Add to it when an archived server version can be tied to a gameplay patch through game data or official notes. Replays resolved by date keep the `~` prefix.
