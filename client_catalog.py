"""Offline lookup of reviewed Steam builds for pinned Windows clients."""
from pathlib import Path
import json
import re

from client_install import ASSETS, validate_recipe
from client_recipe import WINDOWS_DEPOTS


BUILTIN_CATALOG = ASSETS / "pinned_client_catalog.json"
# The legacy Win32 depot still provides the DX11 shader packs used by Win64.
REQUIRED_DEPOTS = WINDOWS_DEPOTS.keys()


def validate_catalog_recipe(recipe):
    validate_recipe(recipe)
    if type(recipe.get("steam_build")) is not int or recipe["steam_build"] <= 0:
        raise ValueError("Catalog recipes require a numeric Steam Build ID")
    missing = REQUIRED_DEPOTS - recipe["depots"].keys()
    if missing:
        raise ValueError(f"Build {recipe['steam_build']} lacks Windows client depots {', '.join(sorted(missing))}")
    sources = recipe.get("sources")
    if not isinstance(sources, list) or not sources or any(not isinstance(url, str) or not url.startswith("https://") for url in sources):
        raise ValueError("Catalog recipes require HTTPS source links")
    return recipe


def validate_catalog(catalog):
    if not isinstance(catalog, dict) or catalog.get("version") != 1:
        raise ValueError("Unsupported pinned client catalog format")
    recipes, series = catalog.get("recipes"), catalog.get("series")
    if not isinstance(recipes, dict) or not isinstance(series, dict):
        raise ValueError("The pinned client catalog requires recipes and series")
    for patch, recipe in recipes.items():
        if validate_catalog_recipe(recipe)["patch"] != patch:
            raise ValueError(f"Catalog entry {patch} has a different recipe patch")
    for key, patch in series.items():
        if not re.fullmatch(r"[0-9]+\.[0-9]{2}", key) or not isinstance(patch, str) or patch not in recipes or patch.rstrip("abcdefghijklmnopqrstuvwxyz") != key:
            raise ValueError(f"Invalid catalog series mapping for {key}")
    return catalog


def load_catalog(path=BUILTIN_CATALOG):
    return validate_catalog(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def recipe_for_patch(catalog, patch):
    key = patch.strip().lower()
    recipes = catalog["recipes"]
    if key.endswith(" series"):
        return recipes.get(catalog["series"].get(key.removesuffix(" series")))
    return recipes.get(key) or recipes.get(catalog["series"].get(key))
