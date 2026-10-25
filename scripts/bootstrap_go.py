"""Developer-only portable Go download, verified against official release SHA256."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1] / ".validation" / "toolchain"


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    with urlopen("https://go.dev/dl/?mode=json", timeout=60) as response:
        releases = json.load(response)
    release = next(item for item in releases if item["stable"])
    asset = next(item for item in release["files"] if item["os"] == "windows" and item["arch"] == "amd64" and item["kind"] == "archive")
    archive = ROOT / asset["filename"]
    if not archive.exists():
        with urlopen("https://go.dev/dl/" + asset["filename"], timeout=120) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != asset["sha256"]:
        raise RuntimeError("Official Go archive SHA256 mismatch")
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if not (ROOT / member.filename).resolve().is_relative_to(ROOT.resolve()):
                raise RuntimeError("Archive path traversal")
        bundle.extractall(ROOT)
    (ROOT / "release.json").write_text(json.dumps({"version": release["version"], **asset}, indent=2))
    print(f"Portable {release['version']} installed in {ROOT / 'go'}")


if __name__ == "__main__":
    main()
