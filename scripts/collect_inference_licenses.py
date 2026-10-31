"""Collect installed inference distribution notices for the portable build."""
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    notices = []
    for name in ("lightgbm", "numpy", "scipy", "narwhals"):
        distribution = metadata.distribution(name)
        found = []
        for file in distribution.files or []:
            if any(word in file.name.upper() for word in ("LICENSE", "COPYING", "NOTICE")):
                path = distribution.locate_file(file)
                if path.is_file():
                    found.append(f"{file}\n{path.read_text(encoding='utf-8', errors='replace')}")
        if not found:
            raise SystemExit(f"No license notices found for required inference distribution {name}")
        notices.append(f"{name} {distribution.version}\n" + "\n".join(found))
    (ROOT / "third_party/inference-licenses.txt").write_text("\n\n".join(notices), encoding="utf-8")
    print("Collected inference distribution notices")


if __name__ == "__main__":
    main()
