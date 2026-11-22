from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from client_install import (BUILTIN_RECIPE, EXECUTABLE, ORIGINAL_STEAM_INFO, RECEIPT, STEAM_INFO, VERSION_ENDPOINT,
                            configure_update_prompt, install_client, load_recipe)
from library import Store, client_for_replay
from migration import save_rule
from test_replays import timestamp, write_replay


class ClientTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_routes_use_series_then_override_then_folder(self):
        store = Store(self.root / "settings.sqlite3")
        for library in store.libraries():
            store.remove_library(library["id"])
        directory = self.root / "recordings"
        directory.mkdir()
        archive = self.root / "archive"
        archive.mkdir()
        store.set_pref("clients", {"old client": ""})
        store.add_library(directory, "old client")
        rule = {"client": "old client", "source": str(directory), "storage": str(archive), "before": "2020-01-01"}
        self.assertEqual(save_rule(store, rule)["client"], "old client")
        write_replay(directory / "1.dem", match_id=1, end_time=timestamp(2018, 11, 26), build=3282)
        write_replay(directory / "2.dem", match_id=2, build=3282, dota_version=3278)
        store.scan()
        matches = {match["match_id"]: match for match in store.catalog()}
        for match in matches.values():
            self.assertEqual(client_for_replay(match, match["copies"][0], store.client_routes()), "7.20e")
        self.assertFalse(matches["1"]["patch_verified"])
        self.assertEqual((matches["2"]["patch"], matches["2"]["patch_verified"]), ("7.20e", True))
        match = matches["1"]
        copy = match["copies"][0]
        self.assertEqual(client_for_replay(match, copy, {}), "old client")
        self.assertEqual(client_for_replay({**match, "client_override": "classic"}, copy, store.client_routes()), "classic")

    def test_legacy_688f_rename_retains_assignments_and_registers_storage(self):
        database = self.root / "legacy.sqlite3"
        legacy = str(self.root / "Dota2_6.88f" / EXECUTABLE)
        source, storage = self.root / "downloads", self.root / "archive"
        rule = {"client": "classic", "source": str(source), "storage": str(storage), "before": "2020-01-01"}
        with closing(sqlite3.connect(database)) as db, db:
            db.executescript("""
                CREATE TABLE preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE libraries (id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, client TEXT NOT NULL);
                CREATE TABLE matches (id TEXT PRIMARY KEY, notes TEXT DEFAULT '', client TEXT DEFAULT '');
                INSERT INTO matches VALUES ('123','Keep these notes','classic');
            """)
            preferences = {"initialized": True, "clients": {"classic": legacy, "7.30e": "pinned.exe"},
                           "client_routes": {"6.88": "classic"}, "migration_rules": {"classic": rule}}
            db.executemany("INSERT INTO preferences VALUES (?,?)",
                           [(key, json.dumps(value)) for key, value in preferences.items()])
            db.execute("INSERT INTO libraries VALUES (5,?, 'classic')", (str(source),))

        store = Store(database)
        self.assertNotIn("classic", store.client_paths())
        self.assertEqual(store.client_paths()["6.88f"], legacy)
        self.assertEqual(store.client_paths()["7.30e"], "pinned.exe")
        self.assertEqual(store.client_routes(), {"6.88": "6.88f"})
        self.assertEqual(store.get_pref("migration_rules"), {"6.88f": {**rule, "client": "6.88f"}})
        self.assertEqual([(library["path"], library["kind"], library["client"]) for library in store.libraries()],
                         [(str(source), "replays", "6.88f"), (str(storage), "storage", "6.88f")])
        self.assertEqual(Store(database).libraries(), store.libraries())
        with store.connect() as db:
            self.assertEqual(tuple(db.execute("SELECT notes,client FROM matches WHERE id='123'").fetchone()),
                             ("Keep these notes", "6.88f"))

    def test_removed_client_stays_removed_and_clears_its_routes(self):
        database = self.root / "clients.sqlite3"
        store = Store(database)
        store.save_client("7.30e", "pinned.exe", ["7.30"])
        self.assertEqual(store.client_routes()["7.30"], "7.30e")
        store.remove_client("7.30e")
        store.remove_client("7.20e")
        store = Store(database)
        self.assertEqual(store.client_routes(), {})
        self.assertNotIn("7.30e", store.client_paths())
        self.assertNotIn("7.20e", store.client_paths())

    def test_pinned_install_uses_exact_manifests_and_can_be_reopened(self):
        recipe = load_recipe(BUILTIN_RECIPE)
        downloader = self.root / "DepotDownloader.exe"
        downloader.touch()
        original = f"ClientVersion={recipe['server_version']}\r\nServerVersion={recipe['server_version']}\r\nSourceRevision=42\r\n".encode("ascii")

        def run(command, **kwargs):
            stage = Path(command[command.index("-dir") + 1])
            self.assertTrue(stage.name.endswith(".installing"))
            self.assertNotEqual(Path(kwargs["cwd"]), stage)
            self.assertFalse(kwargs["shell"])
            depot, manifest = command.index("-depot"), command.index("-manifest")
            self.assertEqual(command[depot + 1:manifest], list(recipe["depots"]))
            self.assertEqual(command[manifest + 1:command.index("-dir")], list(recipe["depots"].values()))
            manifests = stage / ".DepotDownloader"
            manifests.mkdir()
            for depot, manifest in recipe["depots"].items():
                (manifests / f"{depot}_{manifest}.manifest").touch()
            for relative in (EXECUTABLE, "game/bin/win64/engine2.dll", "game/dota/bin/win64/client.dll",
                             "game/dota/gameinfo.gi", "game/dota/maps/dota.vpk", "game/dota/pak01_dir.vpk"):
                file = stage / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b"test fixture")
            (stage / STEAM_INFO).write_bytes(original)
            return subprocess.CompletedProcess(command, 0)

        with patch("client_install.subprocess.run", side_effect=run) as runner:
            exe = install_client(BUILTIN_RECIPE, self.root, downloader)
            self.assertEqual(exe, self.root / "Dota2_7.20e" / EXECUTABLE)
            self.assertTrue((exe.parents[3] / RECEIPT).is_file())
            self.assertEqual(exe.with_name("steam_appid.txt").read_text().strip(), "570")
            info = exe.parents[3] / STEAM_INFO
            backup = exe.parents[3] / ORIGINAL_STEAM_INFO
            self.assertEqual(backup.read_bytes(), original)
            adjusted = original.replace(str(recipe["server_version"]).encode("ascii"), VERSION_ENDPOINT)
            self.assertEqual(info.read_bytes(), adjusted)
            self.assertEqual(install_client(BUILTIN_RECIPE, self.root, downloader), exe)
            install_client(BUILTIN_RECIPE, self.root, downloader, suppress_update_prompt=False)
            self.assertEqual(info.read_bytes(), original)
            install_client(BUILTIN_RECIPE, self.root, downloader)
            self.assertEqual(info.read_bytes(), adjusted)
            runner.assert_called_once()

    def test_failed_download_never_publishes_target_or_uses_steam_library(self):
        downloader = self.root / "DepotDownloader.exe"
        downloader.touch()
        with patch("client_install.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(ValueError, "Steam download failed"):
                install_client(BUILTIN_RECIPE, self.root, downloader)
        self.assertFalse((self.root / "Dota2_7.20e").exists())
        with self.assertRaisesRegex(ValueError, "outside Steam"):
            install_client(BUILTIN_RECIPE, self.root / "steamapps", downloader)

    def test_update_prompt_preserves_unrelated_local_edits(self):
        info = self.root / STEAM_INFO
        info.parent.mkdir(parents=True)
        original = b"ClientVersion=3283\nServerVersion=3283\nSourceRevision=42\n"
        info.write_bytes(original)
        configure_update_prompt(self.root, True)
        edited = info.read_bytes() + b"LocalSetting=custom\n"
        info.write_bytes(edited)
        with self.assertRaisesRegex(ValueError, "has local edits"):
            configure_update_prompt(self.root, False)
        self.assertEqual(info.read_bytes(), edited)
        self.assertEqual((self.root / ORIGINAL_STEAM_INFO).read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
