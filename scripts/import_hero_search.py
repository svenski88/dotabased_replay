"""Bundle a JSON export of DotaBASED public.heroes; no network or credentials."""
import argparse
from datetime import date
import json
from pathlib import Path


def snapshot(rows, exported_on):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Expected a nonempty JSON array of hero rows")
    heroes, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each hero row must be a JSON object")
        identifier = row.get("id")
        if type(identifier) is not int or identifier < 0 or identifier in seen:
            raise ValueError("Hero IDs must be unique nonnegative integers")
        name = row.get("localized_name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Missing name for hero {identifier}")
        hero = {"id": identifier, "localized_name": name}
        for field in ("abbreviations", "aliases"):
            terms = row.get(field)
            if not isinstance(terms, list) or any(not isinstance(term, str) or not term.strip() for term in terms):
                raise ValueError(f"Invalid {field} for hero {identifier}")
            hero[field] = terms
        heroes.append(hero)
        seen.add(identifier)
    return {"schema_version": 1, "source": f"DotaBASED public.heroes (read-only snapshot, {exported_on})", "heroes": sorted(heroes, key=lambda hero: hero["id"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="JSON row array: id, localized_name, abbreviations, aliases")
    parser.add_argument("--exported-on", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "assets" / "hero_search.json")
    args = parser.parse_args()
    data = snapshot(json.loads(args.export.read_text(encoding="utf-8-sig")), args.exported_on)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Bundled {len(data['heroes'])} heroes in {args.output}")


if __name__ == "__main__":
    main()
