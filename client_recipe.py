"""Author Windows Source 2 client recipes from historical Steam depot records."""

from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote

from client_install import validate_recipe


WINDOWS_DEPOTS = {
    "373301": "Dota 2 Content",
    "381451": "Dota 2 Content 2",
    "381452": "Dota 2 Content 3",
    "381453": "Dota 2 Content 4",
    "381454": "Dota 2 Content 5",
    "381455": "Dota 2 Content 6",
    "373302": "Windows shaders / legacy Win32",
    "373303": "Windows 64-bit",
}


class BuildManifestLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.manifests = {}
        self.build_id = None
        self.published = None

    def handle_starttag(self, tag, attrs):
        link = dict(attrs)
        if tag == "link" and link.get("rel") == "canonical":
            match = re.search(r"https://steamdb\.info/patchnotes/([0-9]+)/?(?:$|[?#])", link.get("href") or "")
            if match:
                self.build_id = match[1]
        if tag == "meta" and link.get("itemprop") == "datePublished" and link.get("content"):
            try:
                published = datetime.fromisoformat(link["content"])
            except ValueError:
                pass
            else:
                if published.tzinfo is not None:
                    self.published = published
        if tag != "a":
            return
        if "muted" not in (link.get("class") or "").split():
            return
        href = unquote(link.get("href") or "")
        match = re.search(r"/depot/(\d+)/history/\?changeid=M:(\d+)(?=$|[&#])", href)
        if match:
            depot, manifest = match.groups()
            if self.manifests.setdefault(depot, manifest) != manifest:
                raise ValueError(f"The page contains conflicting manifests for depot {depot}. Save the SteamDB build page.")


def read_build_page(path):
    parser = BuildManifestLinks()
    parser.feed(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
    parser.close()
    if not parser.manifests:
        raise ValueError("No build manifest links found. Save the SteamDB build page as HTML, or enter the IDs manually.")
    return parser


def import_build_pages(paths, target_id=""):
    return merge_build_pages([read_build_page(path) for path in paths], target_id)


@dataclass(frozen=True)
class CapturedBuild:
    build_id: str
    published: datetime
    manifests: dict[str, str]


def import_browser_capture(path, target_id=""):
    capture = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if (not isinstance(capture, dict) or capture.get("version") != 1 or capture.get("app_id") != 570
            or not isinstance(capture.get("pages"), list) or not capture["pages"]):
        raise ValueError("Choose a DotaBased SteamDB capture JSON file.")
    target_build = capture.get("target_build")
    if not isinstance(target_build, str) or (target_id and target_id != target_build):
        raise ValueError(f"The capture targets build {target_build}. Clear the Build ID field or enter the matching ID.")
    pages = []
    seen = set()
    for entry in capture["pages"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid build record in the browser capture.")
        build, date, depots = (entry.get(key) for key in ("build_id", "published_at", "depots"))
        if not isinstance(build, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", build) or build in seen:
            raise ValueError("Each captured build needs a unique numeric Steam Build ID.")
        try:
            published = datetime.fromisoformat(date) if isinstance(date, str) else None
        except ValueError:
            published = None
        if published is None or published.utcoffset() is None:
            raise ValueError(f"Build {build} needs a timezone-qualified publication time.")
        if not isinstance(depots, dict) or any(
            depot not in WINDOWS_DEPOTS or not isinstance(manifest, str)
            or not re.fullmatch(r"[1-9][0-9]{0,19}", manifest) or int(manifest) >= 2**64
            for depot, manifest in depots.items()
        ):
            raise ValueError(f"Build {build} has invalid depot or manifest IDs.")
        seen.add(build)
        pages.append(CapturedBuild(build, published, depots))
    if target_build not in seen:
        raise ValueError("The browser capture is missing its target build.")
    return merge_build_pages(pages, target_build, allow_empty=True)


def merge_build_pages(pages, target_id, *, allow_empty=False):
    if not pages:
        raise ValueError("Select a saved SteamDB build page.")
    if len(pages) > 1:
        if any(not page.build_id or page.published is None for page in pages):
            raise ValueError("Each page needs a Steam Build ID and publication time to combine builds. Use full saved build pages.")
        pages.sort(key=lambda page: (page.published, int(page.build_id)), reverse=True)
    target = pages[0]
    if target_id and target.build_id and target_id != target.build_id:
        raise ValueError(f"Newest selected page is build {target.build_id}. Select the target build and only earlier build pages.")
    manifests, sources = {}, []
    for page in pages:
        added = {depot: value for depot, value in page.manifests.items() if depot in WINDOWS_DEPOTS and depot not in manifests}
        manifests.update(added)
        if (added or (allow_empty and page is target)) and page.build_id:
            sources.append(f"https://steamdb.info/patchnotes/{page.build_id}/")
    if not manifests and not allow_empty:
        raise ValueError("No Windows client depots were found in the saved build pages.")
    return target.build_id, manifests, sources


def read_server_version(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    match = re.search(r"^ServerVersion\s*=\s*([1-9][0-9]*)[ \t]*$", text, re.MULTILINE)
    if not match:
        raise ValueError("The steam.inf file has no numeric ServerVersion.")
    return match[1]


def save_recipe(path, patch, build, server_version, depots, sources):
    missing = [depot for depot in WINDOWS_DEPOTS if not depots.get(depot)]
    if missing:
        raise ValueError(f"Enter the historical manifest IDs for depots {', '.join(missing)}.")
    try:
        build, server_version = int(build), int(server_version)
    except ValueError as exc:
        raise ValueError("Enter the numeric Steam Build ID and Dota ServerVersion.") from exc
    if build <= 0:
        raise ValueError("Enter a positive Steam Build ID.")
    recipe = validate_recipe({"patch": patch, "app_id": 570, "steam_build": build,
                              "server_version": server_version, "depots": depots, "sources": sources})
    Path(path).write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
