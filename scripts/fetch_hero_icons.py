"""Fetch public hero definitions and official Steam icons for offline bundling.

Only generic hero names are transmitted, never replay, match or account data.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

MANIFEST = "https://raw.githubusercontent.com/odota/dotaconstants/master/build/heroes.json"
CDN = "https://cdn.cloudflare.steamstatic.com"
ASSETS = Path(__file__).resolve().parents[1] / "assets"


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "DotaBasedReplay/0.1 public hero assets"}), timeout=30) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Asset exceeds size limit")
    return data


def main():
    manifest = json.loads(fetch(MANIFEST))
    directory = ASSETS / "heroes"
    directory.mkdir(parents=True, exist_ok=True)
    def download(hero):
        name = hero["name"].removeprefix("npc_dota_hero_")
        if not name.replace("_", "").isalnum():
            raise ValueError("Invalid hero name")
        relative = hero.get("icon") or f"/apps/dota2/images/dota_react/heroes/icons/{name}.png"
        if not relative.startswith("/apps/dota2/images/") or ".." in relative:
            raise ValueError("Unexpected icon path")
        target = directory / f"{name}.png"
        if not target.is_file():
            data = fetch(CDN + relative)
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Not a PNG")
            target.write_bytes(data)
        return name, {"id": hero["id"], "name": hero["localized_name"], "url": CDN + relative,
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    with ThreadPoolExecutor(max_workers=3) as executor:
        records = dict(executor.map(download, manifest.values()))
    (ASSETS / "heroes.json").write_text(json.dumps({"manifest": MANIFEST, "heroes": records}, indent=2), encoding="utf-8")
    print(f"Bundled {len(records)} official Steam hero icons ({sum(p.stat().st_size for p in directory.glob('*.png')):,} bytes)")


if __name__ == "__main__":
    main()
