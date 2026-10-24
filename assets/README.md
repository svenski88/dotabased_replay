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
