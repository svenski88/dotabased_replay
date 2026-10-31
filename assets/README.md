# Hero icons

These 127 PNG icons are public Valve/Dota 2 game assets downloaded from the
official Steam CDN for offline display in the replay grid. The icon files total
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

# Match service icons

`links/opendota.png` and `links/dotabuff.png` are offline 20-pixel PNG versions
of the services' public website icons, fetched 2026-10-30. Runtime link buttons
do not fetch icons or send any match/account data until clicked.

- OpenDota source: https://www.opendota.com/assets/images/logo.png
- Dotabuff source: https://www.dotabuff.com/favicon.ico

These identify links to their respective services; they are not app branding.
