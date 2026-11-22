import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from client_install import load_recipe
from client_recipe import WINDOWS_DEPOTS, import_browser_capture, import_build_pages, read_server_version, save_recipe


class RecipeTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_extract_build_depot_changes_without_loading_or_running_scripts(self):
        page = self.root / "build.html"
        page.write_text('''
          <a class="muted" href="/depot/373301/history/?changeid=M:1070167885756987064">Depot 373301</a>
          <a class="muted" href="https://steamdb.info/depot/373303/history/?changeid=M%3A2018048621183605969">Depot 373303</a>
          <a href="/depot/373303/history/?changeid=M:7">Previous manifest</a>
          <script>throw new Error("page script")</script>
        ''', encoding="utf-8")
        self.assertEqual(import_build_pages([page])[1], {
            "373301": "1070167885756987064", "373303": "2018048621183605969",
        })

    def test_conflicting_or_missing_build_links_are_rejected(self):
        page = self.root / "build.html"
        page.write_text("<html></html>", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "No build manifest"):
            import_build_pages([page])
        page.write_text('''
          <a class="muted" href="/depot/373301/history/?changeid=M:1">Depot 373301</a>
          <a class="muted" href="/depot/373301/history/?changeid=M:2">Depot 373301</a>
        ''', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "conflicting manifests"):
            import_build_pages([page])

    def test_multiple_builds_use_newest_available_manifest_per_depot(self):
        older = self.root / "older.html"
        target = self.root / "target.html"
        older.write_text('''
          <link rel="canonical" href="https://steamdb.info/patchnotes/8108956/">
          <meta itemprop="datePublished" content="2022-01-29T02:19:00+00:00">
          <a class="muted" href="/depot/373303/history/?changeid=M:2461489532891711571">Win64</a>
          <a class="muted" href="/depot/381455/history/?changeid=M:4357707856374498140">Content 6</a>
        ''', encoding="utf-8")
        target.write_text('''
          <link rel="canonical" href="https://steamdb.info/patchnotes/8109111/">
          <meta itemprop="datePublished" content="2022-01-29T03:00:27+00:00">
          <a class="muted" href="/depot/373303/history/?changeid=M:2518937140377374552">Win64</a>
        ''', encoding="utf-8")
        build, manifests, sources = import_build_pages([older, target], "8109111")
        self.assertEqual(build, "8109111")
        self.assertEqual(manifests, {"373303": "2518937140377374552", "381455": "4357707856374498140"})
        self.assertEqual(len(sources), 2)
        with self.assertRaisesRegex(ValueError, "only earlier build pages"):
            import_build_pages([older, target], "8108956")

    def test_recipe_prompts_for_unchanged_depots_and_saves_installer_format(self):
        source = self.root / "steam.inf"
        source.write_bytes(b"ClientVersion=5071\r\nServerVersion=5072\r\n")
        version = read_server_version(source)
        path = self.root / "client_7.30e.json"
        with self.assertRaisesRegex(ValueError, "381451"):
            save_recipe(path, "7.30e", "7620787", version, {"373301": "1"}, [])
        self.assertFalse(path.exists())
        depots = dict.fromkeys(WINDOWS_DEPOTS, "2018048621183605969")
        save_recipe(path, "7.30e", "7620787", version, depots, ["https://steamdb.info/patchnotes/7620787/"])
        self.assertEqual(load_recipe(path)["server_version"], 5072)
        self.assertEqual(load_recipe(path)["depots"], depots)

    def test_browser_capture_keeps_target_and_newest_manifest_per_depot(self):
        capture = self.root / "capture.json"
        pages = [
            {"build_id": "99", "published_at": "2022-01-29T02:19:00Z",
             "depots": {"373303": "2461489532891711571", "373302": "4357707856374498140"}},
            {"build_id": "101", "published_at": "2022-01-29T03:00:27Z", "depots": {}},
            {"build_id": "100", "published_at": "2022-01-29T03:00:27Z",
             "depots": {"373303": "2518937140377374552"}},
        ]
        payload = {"version": 1, "app_id": 570, "target_build": "101", "pages": pages}
        capture.write_text(json.dumps(payload), encoding="utf-8")
        build, manifests, sources = import_browser_capture(capture)
        self.assertEqual(build, "101")
        self.assertEqual(manifests, {"373303": "2518937140377374552", "373302": "4357707856374498140"})
        self.assertEqual(sources, [f"https://steamdb.info/patchnotes/{key}/" for key in ("101", "100", "99")])
        with self.assertRaisesRegex(ValueError, "capture targets build 101"):
            import_browser_capture(capture, "99")
        capture.write_text(json.dumps({**payload, "target_build": "100"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Newest selected page is build 101"):
            import_browser_capture(capture)
        pages[0]["depots"]["373302"] = 4357707856374498140
        capture.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid depot or manifest IDs"):
            import_browser_capture(capture)


if __name__ == "__main__":
    unittest.main()
