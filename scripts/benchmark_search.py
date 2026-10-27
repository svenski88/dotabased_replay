"""Synthetic search timings; no replay folders, personal database or network."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from library import filter_matches
from search import SearchIndex


def catalog_fixture(count):
    catalog = []
    for index in range(count):
        players = [{"account_id": 42 + slot, "steam_id": str(76561197960265770 + slot), "name": f"Player {slot}", "hero": hero, "team": 2 if slot < 5 else 3}
                   for slot, hero in enumerate(("nevermore" if index % 3 == 0 else "axe", "crystal_maiden", "pudge", "antimage", "life_stealer", "invoker", "furion", "earthshaker", "mirana", "wisp"))]
        fields = {"match_id": str(100000 + index), "players": players, "duration": 1800 + index, "radiant_score": 30, "dire_score": 24, "winner": 2, "game_mode": 22, "league_id": 57}
        catalog.append({**fields, "key": fields["match_id"], "copies": [{"path": f"C:/synthetic/replays/{100000 + index}.dem", "size": 1048576, "mtime": 123456789, "client": "modern"}], "total_size": 1048576, "rating": index % 6, "notes": "Huge late comeback, excellent wards", "league_name": "Synthetic League", "end_time": 1770000000, "local_results": [{"path": f"C:/synthetic/replays/{100000 + index}.dem", "fields": deepcopy(fields), "complete": True, "helper_version": "fixture", "provenance": {key: "Complete local parser" for key in fields}}]})
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=int, nargs="+", default=[1000, 5000])
    args = parser.parse_args()
    for count in args.counts:
        catalog = catalog_fixture(count)
        accounts = [{"id": 42, "nickname": "Captain Sven", "enabled": False}]
        print(f"{count} matches; {len(json.dumps(catalog)) / count:.0f} JSON chars/match", flush=True)
        started = perf_counter()
        index = SearchIndex(catalog, accounts)
        print(f"Index preparation: {perf_counter() - started:.3f}s", flush=True)
        for query in ("SF CM comeback", "unmatchedword", "Captain Sven, Rylai"):
            started = perf_counter()
            found = filter_matches(catalog, accounts, search=query, search_index=index)
            print(f"{query!r}: {perf_counter() - started:.3f}s, {len(found)} results", flush=True)


if __name__ == "__main__":
    main()
