"""Read-only replay inventory; temporary database is removed on exit."""
from collections import Counter
import json
from pathlib import Path
import tempfile

from library import Store, presence


def main():
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "catalog.sqlite3")
        report = store.scan()
        catalog = store.catalog()
        report.update({"unique_matches": len(catalog), "duplicates": report["files"] - len(catalog),
                       "with_players": sum(bool(m.get("players")) for m in catalog),
                       "league_matches": sum(bool(m.get("league_id")) for m in catalog),
                       "winners": dict(Counter(m.get("winner") for m in catalog)),
                       "suggestions": presence(catalog)[:10]})
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
