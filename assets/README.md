# Hero icons

The 127 PNG icons in [`valve/heroes/`](valve/heroes/) are Valve/Dota 2 game assets
from the official Steam CDN for offline replay visualization. See the
[artwork notice](valve/heroes/LICENSE.txt). The icon files total
666,851 bytes. `heroes.json` records each icon's URL, SHA-256 hash, localized name
and numeric hero ID. No replay, match or account identifiers are used to request
them.

- Manifest: https://raw.githubusercontent.com/odota/dotaconstants/master/build/heroes.json
- CDN: https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons/
- Refresh script: `python scripts/fetch_hero_icons.py`

The runtime loads these local files only. PyInstaller includes this directory
through `build.ps1`.

`hero_search.json` is a read-only snapshot of DotaBASED `public.heroes`, exported
2026-10-27 (128 rows including Unknown). It supplies localized names,
abbreviations and aliases; numeric IDs join to internal names in `heroes.json`.
Search never queries the backend at runtime. To refresh, export the JSON rows of
`SELECT id, localized_name, abbreviations, aliases FROM public.heroes ORDER BY id`
and run `python scripts/import_hero_search.py path/to/export.json --exported-on YYYY-MM-DD`.
The importer validates the export before replacing the bundled snapshot. No
credentials or personal account metadata are included.

# Replay application brand

`brand/replay-mark.svg` derives from the website's
`dotabased/public/assets/dotabased-mark-prism-classic.svg`. It retains the exact
rounded tile and rune paths, with a blue/cyan frame (`#2589ff` to `#42d5ff`),
pale blue rune (`#d3f3ff` to `#6dbdff`) and blue-black tile (`#101b2b`).
No sibling website assets are modified. PNG exports are transparent and range
from 16 to 512 pixels; `replay.ico` contains seven frames from 16 to 256 pixels.

The header uses the 48px PNG. Tk uses multiple PNG sizes for its default window
and dialog icon; the Windows executable embeds the ICO. All are bundled offline.
To regenerate after editing the SVG:

```powershell
node scripts/build_brand_assets.cjs
```

This developer-only script uses Node, Microsoft Edge and Playwright. It defaults
to the existing workspace `../dotabased/node_modules/playwright`; pass
`--playwright C:/path/to/node_modules/playwright` to use another installed copy.
No browser, Node, renderer or Python image package is required by app recipients.

# Gameplay patch dates

`patch_dates.json` contains UTC Unix timestamps used for offline patch estimates.
For 7.08 onward, it uses Valve's [patch notes feed](https://www.dota2.com/datafeed/patchnoteslist?language=english),
retrieved November 20, 2026. Earlier entries use known Dota 2 release dates from
the [Dota 2 patch archive](https://liquipedia.net/dota2/Archive:Patches) and
[version history](https://liquipedia.net/dota2/Game_Versions/6.70_to_6.88f), entered
at midnight UTC. The most recent entry applies until its successor is added.
Release-day matches and events played on a different version can fall outside
these estimates.
