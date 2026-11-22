"""Update the bundled pinned-client catalog from reviewed recipes or complete build snapshots."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client_catalog import BUILTIN_CATALOG, load_catalog, validate_catalog, validate_catalog_recipe
from client_install import load_recipe, write_atomically
from client_recipe import WINDOWS_DEPOTS, import_browser_capture, read_server_version


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_snapshot(snapshot):
    if "appinfo" not in snapshot:
        return snapshot
    appinfo = snapshot["appinfo"]
    if str(appinfo["appid"]) != "570":
        raise ValueError("Steam PICS snapshots must be for app 570")
    depots = appinfo["depots"]
    public = depots["branches"]["public"]
    manifests = {}
    for depot in WINDOWS_DEPOTS:
        entry = depots.get(depot, {}).get("manifests", {}).get("public")
        if entry:
            manifests[depot] = entry["gid"]
    return {
        "steam_build": int(public["buildid"]),
        "published_at": datetime.fromtimestamp(int(public["timeupdated"]), timezone.utc).isoformat(),
        "server_version": snapshot.get("server_version"),
        "depots": manifests,
        "sources": snapshot.get("sources"),
    }


def compile_history(snapshots, windows):
    def publication(build):
        published = datetime.fromisoformat(build["published_at"])
        if published.utcoffset() is None:
            raise ValueError("Snapshot timestamps require a time zone")
        return published, build["steam_build"]

    ordered = sorted(map(normalize_snapshot, snapshots), key=publication)
    indices = {build["steam_build"]: index for index, build in enumerate(ordered)}
    if len(indices) != len(ordered):
        raise ValueError("Snapshot history contains duplicate Steam Build IDs")
    for window in windows:
        patch, first, next_build = (window[key] for key in ("patch", "first_build", "next_build"))
        if first not in indices or next_build not in indices or indices[first] >= indices[next_build]:
            raise ValueError(f"Patch {patch} requires both observed public build boundaries, in release order")
        final = ordered[indices[next_build] - 1]
        recipe = {key: final[key] for key in ("steam_build", "server_version", "depots", "sources")}
        yield validate_catalog_recipe({"patch": patch, "app_id": 570, **recipe})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=BUILTIN_CATALOG)
    parser.add_argument("--add-recipe", type=Path, action="append", default=[])
    parser.add_argument("--add-capture", type=Path, help="Import a browser capture for a reviewed patch")
    parser.add_argument("--patch", help="Gameplay patch for --add-capture")
    parser.add_argument("--steam-inf", type=Path, help="Archived steam.inf for the target build in --add-capture")
    parser.add_argument("--snapshot-history", type=Path)
    parser.add_argument("--patch-windows", type=Path)
    parser.add_argument("--series", action="append", default=[], metavar="SERIES=PATCH")
    args = parser.parse_args()
    if bool(args.snapshot_history) != bool(args.patch_windows):
        parser.error("--snapshot-history and --patch-windows must be used together")
    if any((args.add_capture, args.patch, args.steam_inf)) and not all((args.add_capture, args.patch, args.steam_inf)):
        parser.error("--add-capture, --patch, and --steam-inf must be used together")
    try:
        catalog = load_catalog(args.catalog) if args.catalog.exists() else {"version": 1, "recipes": {}, "series": {}}
        recipes = [load_recipe(path) for path in args.add_recipe]
        if args.add_capture:
            build, depots, sources = import_browser_capture(args.add_capture)
            recipes.append({"patch": args.patch, "app_id": 570, "steam_build": int(build),
                            "server_version": int(read_server_version(args.steam_inf)), "depots": depots,
                            "sources": sources})
        if args.snapshot_history:
            recipes.extend(compile_history(read_json(args.snapshot_history), read_json(args.patch_windows)))
        for recipe in recipes:
            catalog["recipes"][recipe["patch"]] = validate_catalog_recipe(recipe)
        catalog["series"].update(dict(entry.split("=", 1) for entry in args.series))
        validate_catalog(catalog)
        # Sort patch keys without changing the installer order of depots within a recipe.
        for key in ("recipes", "series"):
            catalog[key] = dict(sorted(catalog[key].items()))
        write_atomically(args.catalog, (json.dumps(catalog, indent=2) + "\n").encode("utf-8"))
    except (KeyError, TypeError, OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"{len(catalog['recipes'])} recipes in {args.catalog}")


if __name__ == "__main__":
    main()
