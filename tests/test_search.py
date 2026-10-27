import unittest
from unittest.mock import patch

from library import filter_matches
from search import SearchIndex, hero_match, query_terms
from scripts.import_hero_search import snapshot


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.matches = [
            {"match_id": "901", "players": [{"account_id": 42, "name": "Alice", "hero": "nevermore"}, {"account_id": 99, "name": "Bob", "hero": "crystal_maiden"}], "notes": "Huge late comeback, good wards", "copies": [{"path": r"C:\replays\901.dem"}]},
            {"match_id": "902", "players": [{"account_id": 99, "name": "Bob", "hero": "axe"}], "notes": "good wards then a late huge comeback"},
        ]
        self.accounts = [{"id": 42, "nickname": "Captain Sven", "enabled": False}]

    def find(self, query):
        return filter_matches(self.matches, self.accounts, search=query)

    def test_and_spaces_commas_and_mixed_metadata(self):
        for query in ("SF CM", "SF,CM", "sf, CM comeback", 'Captain Sven, Rylai, "late comeback"', '"Shadow Fiend", crystal_maiden, Alice', r"901 C:\replays"):
            with self.subTest(query=query):
                self.assertEqual(self.find(query), self.matches[:1])
        self.assertEqual(self.find("SF Axe"), [])
        self.assertEqual(self.find("SF missing"), [])

    def test_notes_and_phrase_search(self):
        self.assertEqual(self.find("huge comeback"), self.matches)
        self.assertEqual(self.find('"huge late comeback"'), self.matches[:1])
        self.assertEqual(self.find('"huge late come'), self.matches[:1])
        self.assertEqual(self.find(", , \t"), self.matches)

    def test_nickname_tracks_identity_and_edits_without_enabled_filter(self):
        self.assertEqual(self.find('"Captain Sven"'), self.matches[:1])
        self.accounts[0]["nickname"] = "New label"
        self.assertEqual(self.find("Captain"), [])
        self.assertEqual(self.find("New label"), self.matches[:1])
        self.assertEqual(filter_matches(self.matches, self.accounts, enabled=True, search="New"), [])

    def test_normalization_and_aliases(self):
        for term, hero in (("Shadow Fiend", "nevermore"), ("shadowfiend", "nevermore"), ("SF", "Hero #11"), ("Crystal Maiden", "npc_dota_hero_crystal_maiden"), ("N'aix", "life_stealer"), ("Natures Prophet", "furion"), ("Magina", "antimage"), ("Outhouse", "obsidian_destroyer")):
            with self.subTest(term=term):
                self.assertTrue(hero_match(term, hero))
        self.assertTrue(hero_match("ES", "earthshaker"))
        self.assertTrue(hero_match("ES", "earth_spirit"))
        self.assertFalse(hero_match("ES", "ember_spirit"))
        self.assertTrue(hero_match("future hero", "future_hero"))

    def test_short_abbreviations_not_substrings_or_property_names(self):
        self.assertEqual(self.find("AM"), [])
        self.assertEqual(self.find("NA"), [])
        self.matches[0]["notes"] += " AM was mentioned"
        self.assertEqual(self.find("AM"), self.matches[:1])
        self.assertFalse(hero_match("AM", "shadow_shaman"))

    def test_literal_apostrophes_backslashes_and_unfinished_quotes(self):
        self.assertEqual(query_terms('"Nature\'s Prophet", N\'aix C:\\replays'), ("nature's prophet", "n'aix", "c:\\replays"))
        self.assertEqual(query_terms('SF "Crystal Mai'), ("sf", "crystal mai"))

    def test_import_validates_export_before_writing(self):
        row = {"id": 11, "localized_name": "Shadow Fiend", "abbreviations": ["SF"], "aliases": ["Nevermore"]}
        self.assertEqual(snapshot([row], "2026-10-27")["heroes"], [row])
        for rows in ([], [None], [row, row], [{**row, "aliases": "Nevermore"}], [{**row, "localized_name": ""}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                snapshot(rows, "2026-10-27")

    def test_index_reuses_prepared_metadata_and_compiled_query(self):
        index = SearchIndex(self.matches, self.accounts)
        expected = filter_matches(self.matches, self.accounts, search="SF CM", search_index=index)
        with patch("search.normalize", side_effect=AssertionError("Warm query normalized text")), patch("search.scalar_values", side_effect=AssertionError("Warm query traversed metadata")):
            self.assertEqual(filter_matches(self.matches, self.accounts, search="SF CM", search_index=index), expected)

    def test_index_invalidates_edits_nicknames_and_metadata_reload(self):
        index = SearchIndex(self.matches, self.accounts)
        document = index.documents[id(self.matches[0])]
        self.matches[0]["notes"] = "Fresh annotation"
        self.assertEqual(filter_matches(self.matches, self.accounts, search="Fresh annotation", search_index=index), self.matches[:1])
        self.assertEqual(filter_matches(self.matches, self.accounts, search="Huge", search_index=index), self.matches[1:])
        self.assertIs(index.documents[id(self.matches[0])], document)
        self.matches[0]["rating"] = 5
        self.matches[0]["client_override"] = "classic"
        self.assertEqual(filter_matches(self.matches, self.accounts, search="5 classic", search_index=index), self.matches[:1])
        self.accounts[0]["nickname"] = "Renamed friend"
        index.update_accounts(self.accounts)
        self.assertEqual(filter_matches(self.matches, self.accounts, search="Captain", search_index=index), [])
        self.assertEqual(filter_matches(self.matches, self.accounts, search="Renamed friend", search_index=index), self.matches[:1])
        self.matches[0]["players"][0]["hero"] = "invoker"
        index.update(self.matches[0])
        self.assertEqual(filter_matches(self.matches, self.accounts, search="SF", search_index=index), [])
        self.assertEqual(filter_matches(self.matches, self.accounts, search="Kael", search_index=index), self.matches[:1])
        refreshed = [{**self.matches[0], "notes": "Reloaded result"}]
        replacement = SearchIndex(refreshed, self.accounts)
        self.assertEqual(filter_matches(refreshed, self.accounts, search="Reloaded", search_index=replacement), refreshed)
        self.assertEqual(filter_matches(refreshed, self.accounts, search="Fresh", search_index=replacement), [])

    def test_prepared_fields_keep_phrase_boundaries(self):
        catalog = [{"notes": "unrelated", "one": "late", "two": "comeback"}]
        index = SearchIndex(catalog)
        self.assertEqual(filter_matches(catalog, [], search='"late comeback"', search_index=index), [])
        self.assertEqual(filter_matches(catalog, [], search="late comeback", search_index=index), catalog)


if __name__ == "__main__":
    unittest.main()
