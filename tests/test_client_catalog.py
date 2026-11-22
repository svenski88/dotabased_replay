from pathlib import Path
import unittest

from client_catalog import REQUIRED_DEPOTS, load_catalog, recipe_for_patch
from client_install import load_recipe, same_build
from scripts.update_client_catalog import compile_history


class CatalogTests(unittest.TestCase):
    def test_bundled_lookup_accepts_exact_patch_and_explicit_series(self):
        catalog = load_catalog()
        self.assertEqual(recipe_for_patch(catalog, " 7.30E ")["steam_build"], 8248131)
        self.assertEqual(recipe_for_patch(catalog, "7.30")["server_version"], 5175)
        self.assertEqual(recipe_for_patch(catalog, "7.20")["server_version"], 3283)
        self.assertEqual(recipe_for_patch(catalog, "7.40")["steam_build"], 21272529)
        self.assertEqual(recipe_for_patch(catalog, "7.40 series")["steam_build"], 22472058)
        self.assertIsNone(recipe_for_patch(catalog, "7.40b"))
        self.assertIsNone(recipe_for_patch(catalog, "7.30d"))
        self.assertEqual(recipe_for_patch(catalog, "7.31d")["depots"]["373302"], "1248254969179815201")

    def test_catalog_and_receipt_can_differ_in_sources_but_not_install_order(self):
        recipe = recipe_for_patch(load_catalog(), "7.20e")
        default = load_recipe(Path(__file__).resolve().parents[1] / "assets/client_7.20e.json")
        self.assertTrue(same_build(default, {**recipe, "sources": ["https://example.com/archive"]}))
        self.assertFalse(same_build(default, {**recipe, "depots": dict(reversed(recipe["depots"].items()))}))
        self.assertFalse(same_build(default, {**recipe, "steam_build": 3391107}))

    def test_history_uses_full_snapshot_before_next_build_on_the_same_day(self):
        depots = {depot: {"manifests": {"public": {"gid": str(2021000000000000000 + int(depot))}}}
                  for depot in sorted(REQUIRED_DEPOTS)}

        def snapshot(build, time):
            return {"appinfo": {"appid": "570", "depots": {**depots, "branches": {"public": {"buildid": str(build), "timeupdated": str(time)}}}},
                    "server_version": build + 50, "sources": ["https://example.com/archive"]}

        first, final, following = snapshot(100, 1640000000), snapshot(101, 1640000040), snapshot(102, 1640000080)
        snapshots = [following, final, first]
        windows = [{"patch": "7.30d", "first_build": 100, "next_build": 102}]
        recipe, = compile_history(snapshots, windows)
        self.assertEqual(recipe["steam_build"], 101)
        self.assertEqual(recipe["server_version"], 151)
        self.assertEqual(recipe["depots"]["381454"], "2021000000000381454")
        self.assertIn("373302", recipe["depots"])
        with self.assertRaisesRegex(ValueError, "both observed"):
            list(compile_history([first, final], windows))
        del final["appinfo"]["depots"]["373302"]
        with self.assertRaisesRegex(ValueError, "lacks Windows client depots 373302"):
            list(compile_history(snapshots, windows))


if __name__ == "__main__":
    unittest.main()
