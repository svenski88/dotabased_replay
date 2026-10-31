import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from library import Store, filter_matches, launch, launch_command, presence
from opendota import ApiError, OpenDota, Unavailable
from replay_parser import ReplayError, STEAM_BASE, decode_summary, parse_replay, snappy


def vint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result + bytes([value]))


def number(field, value):
    return vint(field << 3) + vint(value)


def blob(field, value):
    return vint(field << 3 | 2) + vint(len(value)) + value


def summary(match_id=123, account=42, league=57, duration=1800):
    player = blob(1, b"npc_dota_hero_axe") + blob(2, b"Alice") + number(4, STEAM_BASE + account) + number(5, 2)
    dota = number(1, match_id) + number(2, 22) + number(3, 2) + blob(4, player) + number(5, league)
    return vint(1 << 3 | 5) + struct.pack("<f", duration) + blob(4, blob(4, dota))


def literal_snappy(payload):
    length = len(payload) - 1
    if length < 60:
        prefix = bytes([length << 2])
    else:
        width = (length.bit_length() + 7) // 8
        prefix = bytes([(59 + width) << 2]) + length.to_bytes(width, "little")
    return vint(len(payload)) + prefix + payload


def write_replay(path, match_id=123, compressed=True, magic=b"PBDEMS2\0", duration=1800):
    payload = summary(match_id, duration=duration)
    if compressed:
        payload = literal_snappy(payload)
    footer = vint(66 if compressed else 2) + vint(90000) + vint(len(payload)) + payload
    path.write_bytes(magic + struct.pack("<II", 16, 16) + footer)


class ParserTests(unittest.TestCase):
    def test_both_headers_and_footer_compression(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "123.dem"
            for magic in (b"PBDEMS2\0", b"PBUFDEM\0"):
                for compressed in (True, False):
                    write_replay(path, compressed=compressed, magic=magic)
                    result = parse_replay(path)
                    self.assertEqual(result["match_id"], "123")
                    self.assertEqual(result["players"][0]["account_id"], 42)
                    self.assertEqual(result["players"][0]["hero"], "axe")
                    self.assertEqual(result["league_id"], 57)
                    self.assertEqual(result["winner"], 2)

    def test_snappy_overlapping_copies_all_tag_forms(self):
        # Literal 'a', then repeated copies using short, 16-bit and 32-bit offsets.
        data = vint(13) + b"\x00a" + bytes([1, 1]) + bytes([14, 1, 0]) + bytes([15, 1, 0, 0, 0])
        self.assertEqual(snappy(data), b"a" * 13)

    def test_invalid_snappy_is_bounded(self):
        for data in (vint(17 * 1024 * 1024), vint(4) + b"\x01\x00", vint(2) + b"\x0ca", vint(3) + b"\x00a"):
            with self.assertRaises(ReplayError):
                snappy(data)

    def test_truncated_or_unsupported_file_visible_as_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.dem"
            for data in (b"", b"HL2DEMO\0" + b"\0" * 20, b"PBDEMS2\0" + b"\0" * 20):
                path.write_bytes(data)
                with self.assertRaises(ReplayError):
                    parse_replay(path)

    def test_nonfinite_duration_is_unknown(self):
        self.assertIsNone(decode_summary(summary(duration=float("nan")))["duration"])
        self.assertIsNone(decode_summary(summary(duration=-10))["duration"])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "catalog.sqlite3")
        for library in self.store.libraries():
            self.store.remove_library(library["id"])

    def add(self, name, client="modern"):
        directory = self.root / name
        directory.mkdir()
        self.store.add_library(str(directory), client)
        return directory

    def test_zero_duration_survives_catalog_remote_fallback(self):
        directory = self.add("zero-duration")
        write_replay(directory / "123.dem", duration=0)
        self.store.scan()
        self.assertEqual(self.store.catalog()[0]["duration"], 0)

    def test_duplicate_match_one_presence_entry_and_two_launch_copies(self):
        first, second = self.add("modern"), self.add("classic", "classic")
        write_replay(first / "123.dem")
        write_replay(second / "123.dem")
        self.store.scan()
        catalog = self.store.catalog()
        self.assertEqual(len(catalog), 1)
        self.assertEqual(len(catalog[0]["copies"]), 2)
        self.assertEqual(presence(catalog)[0]["fraction"], 1)
        self.assertEqual({c["client"] for c in catalog[0]["copies"]}, {"modern", "classic"})

    def test_unchanged_file_not_reparsed_and_deleted_file_hidden_notes_retained(self):
        directory = self.add("library")
        path = directory / "123.dem"
        write_replay(path)
        self.store.scan()
        self.store.save_match("123", notes="A turning point", client="classic")
        with patch("library.parse_replay", side_effect=AssertionError("should be cached")):
            self.assertEqual(self.store.scan()["cached"], 1)
        self.assertEqual(self.store.catalog()[0]["notes"], "A turning point")
        path.unlink()
        self.store.scan()
        self.assertEqual(self.store.catalog(), [])
        write_replay(path)
        self.store.scan()
        self.assertEqual(self.store.catalog()[0]["client_override"], "classic")

    def test_malformed_file_kept_and_cache_does_not_replace_offline_summary(self):
        directory = self.add("library")
        write_replay(directory / "123.dem")
        (directory / "auto.dem").write_bytes(b"broken")
        report = self.store.scan()
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(len(self.store.catalog()), 2)
        self.store.cache("matches/123", {"match_id": 123, "radiant_win": False, "radiant_score": 42, "dire_score": 33, "lobby_type": 1, "leagueid": 99}, 100)
        match = next(m for m in self.store.catalog() if m.get("match_id") == "123")
        self.assertEqual((match["winner"], match["league_id"]), (2, 57))
        self.assertEqual((match["radiant_score"], match["dire_score"]), (42, 33))

    def test_cache_expiry_and_local_preferences(self):
        self.store.cache("players/42", {"profile": {"personaname": "Alice"}}, 60, now=100)
        self.assertIsNotNone(self.store.cached("players/42", now=150))
        self.assertIsNone(self.store.cached("players/42", now=160))
        self.assertIsNotNone(self.store.cached("players/42", now=200, include_stale=True))
        self.store.pin(42, "Local alias", False)
        reopened = Store(self.store.path)
        self.assertEqual(reopened.accounts(), [{"id": 42, "nickname": "Local alias", "enabled": 0}])

    def test_safe_launch_arguments_without_launching_client(self):
        executable = self.root / "client.exe"
        replay = self.root / "spaces in replay.dem"
        executable.touch()
        replay.touch()
        args = launch_command(executable, replay)
        self.assertEqual(args[1:5], ["-console", "-novid", "-gamestateintegration", "+playdemo"])
        self.assertEqual(args[5], str(replay.resolve()).replace("\\", "/"))
        with patch("library.subprocess.Popen") as popen:
            launch(executable, replay)
            self.assertEqual(popen.call_args.args[0], args)
            self.assertIs(popen.call_args.kwargs["shell"], False)
        bad = self.root / "replay;quit.dem"
        bad.touch()
        with self.assertRaises(ValueError):
            launch_command(executable, bad)


class FilterTests(unittest.TestCase):
    def test_threshold_strictly_above_five_percent_and_duplicates_in_match_not_counted(self):
        catalog = [{"players": [{"account_id": 42, "name": "Alice"}] * 2}, {"players": [{"account_id": 42}, {"account_id": 99}]}] + [{"players": []} for _ in range(18)]
        result = presence(catalog)
        self.assertEqual([r["id"] for r in result], [42])
        self.assertEqual(result[0]["count"], 2)

    def test_account_toggles_or_filter_and_no_enabled_accounts(self):
        catalog = [{"players": [{"account_id": 1}], "league_id": 7}, {"players": [{"account_id": 2}], "notes": "Watch this"}]
        accounts = [{"id": 1, "enabled": 1}, {"id": 2, "enabled": 0}]
        self.assertEqual(filter_matches(catalog, accounts, True), catalog[:1])
        self.assertEqual(filter_matches(catalog, [], True), [])
        self.assertEqual(filter_matches(catalog, accounts, search="WATCH"), catalog[1:])
        self.assertEqual(filter_matches(catalog, accounts, league_only=True), catalog[:1])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "catalog.sqlite3")
        self.clock = 1800000000.0
        self.calls = []
        self.responses = []
        def request(url):
            self.calls.append(url)
            return self.responses.pop(0)
        self.api = OpenDota(self.store, request, lambda: self.clock, self.sleep)

    def sleep(self, seconds):
        self.clock += seconds

    def test_cache_and_persistent_spacing_and_budget(self):
        self.responses.extend([(200, {}, {"match_id": 123}), (200, {}, {"profile": {"personaname": "Alice", "avatar": "https://example.test/avatar.png"}})])
        self.api.fetch("matches/123")
        self.api.fetch("matches/123")
        before = self.clock
        self.api.fetch("players/42")
        self.assertAlmostEqual(self.clock - before, 2.1, places=5)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.store.get_pref("api_budget")["count"], 2)
        self.assertEqual(self.store.cached("players/42")["data"]["profile"]["personaname"], "Alice")

    def test_429_persists_cooldown_without_retrying(self):
        self.responses.append((429, {"Retry-After": "240"}, None))
        with self.assertRaises(ApiError):
            self.api.fetch("matches/123")
        self.assertEqual(self.store.get_pref("api_next_at"), self.clock + 240)
        with self.assertRaisesRegex(ApiError, "cooling down"):
            self.api.fetch("matches/124")
        self.assertEqual(len(self.calls), 1)

    def test_negative_cache_and_batch_continues_unavailable_records(self):
        self.responses.extend([(404, {}, None), (200, {}, {"match_id": 124})])
        result = self.api.enrich([123, 124])
        self.assertEqual(result, {"completed": 1, "unavailable": 1})
        with self.assertRaises(Unavailable):
            self.api.fetch("matches/123")
        self.assertEqual(len(self.calls), 2)

    def test_batch_caps_twenty_and_respects_cancel(self):
        with patch.object(self.api, "fetch", return_value={}) as fetch:
            self.assertEqual(self.api.enrich(range(100))["completed"], 20)
            self.assertEqual(fetch.call_count, 20)
            self.assertEqual(self.api.enrich([1, 2], cancelled=lambda: True)["completed"], 0)

    def test_batch_stops_on_rate_limit(self):
        self.responses.append((429, {}, None))
        with self.assertRaises(ApiError):
            self.api.enrich([123, 124])
        self.assertEqual(len(self.calls), 1)

    def test_daily_budget_blocks_network_but_allows_cached_record(self):
        self.responses.append((200, {}, {"match_id": 123}))
        self.api.fetch("matches/123")
        budget = self.store.get_pref("api_budget")
        self.store.set_pref("api_budget", {**budget, "count": 1000})
        self.api.fetch("matches/123")
        with self.assertRaisesRegex(ApiError, "daily budget"):
            self.api.fetch("matches/124")
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
