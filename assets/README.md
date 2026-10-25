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
