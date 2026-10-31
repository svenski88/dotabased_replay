"""Validate a Windows folder build and package the complete portable release."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP = "DotaBasedReplay"


def version_name(value):
    if not re.fullmatch(r"v?\d+\.\d+(?:\.\d+)?(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?", value):
        raise ValueError("Use a release version such as v1.0, v1.1.0 or v1.1.0-beta.1")
    return value.removeprefix("v")


def payload_files(bundle):
    files = sorted(path for path in bundle.rglob("*") if path.is_file())
    if {path.name for path in bundle.iterdir()} != {f"{APP}.exe", "_internal"}:
        raise ValueError("Distribution must contain only the canonical executable and _internal folder")
    for path in bundle.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"Distribution contains a linked path: {path}")
        name = path.name.lower()
        if path.is_file() and (name.endswith((".dem", ".dem.bz2", ".sqlite", ".sqlite3", ".db", ".log")) or
                               ".sqlite" in name or name.startswith(".env")):
            raise ValueError(f"Distribution contains user data or a log: {path}")
    for relative in (f"{APP}.exe", "_internal/bin/replay-parser.exe", "_internal/assets/brand/replay.ico",
                     "_internal/assets/brand/replay-mark-48.png", "_internal/assets/heroes.json",
                     "_internal/third_party/parser-licenses.txt", "_internal/third_party/inference-licenses.txt",
                     "_internal/models/micro19/model.txt", "_internal/models/micro19/model_meta.json",
                     "_internal/assets/links/opendota.png", "_internal/assets/links/dotabuff.png"):
        if not (bundle / relative).is_file():
            raise ValueError(f"Required distribution file missing: {relative}")
    if len(list((bundle / "_internal/assets/heroes").glob("*.png"))) < 100:
        raise ValueError("Bundled hero icons are missing")
    if not any((bundle / "_internal/lightgbm" / directory / "lib_lightgbm.dll").is_file() for directory in ("bin", "lib")):
        raise ValueError("Required LightGBM inference DLL is missing")
    return files


def verify_binary(bundle):
    import pefile  # Developer build dependency; never imported by the application.
    with pefile.PE(str(bundle / f"{APP}.exe")) as pe:
        if pe.FILE_HEADER.Machine != 0x8664:
            raise ValueError("Expected Windows x64 application")
        resources = {entry.id: entry for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries}
        def data(entry):
            item = entry.directory.entries[0].data.struct
            return pe.get_data(item.OffsetToData, item.Size)
        group = data(resources[14].directory.entries[0])
        if struct.unpack_from("<HHH", group) != (0, 1, 7):
            raise ValueError("Expected seven branded executable icon sizes")
        icons = {entry.id: data(entry) for entry in resources[3].directory.entries}
        sizes = []
        for index in range(7):
            width, _, _, _, _, _, _, resource_id = struct.unpack_from("<BBBBHHIH", group, 6 + index * 14)
            size = width or 256
            expected = (ROOT / f"assets/brand/replay-mark-{size}.png").read_bytes()
            if icons[resource_id] != expected:
                raise ValueError(f"Executable has an unexpected icon at size {size}")
            sizes.append(size)
    helper = bundle / "_internal/bin/replay-parser.exe"
    with pefile.PE(str(helper), fast_load=True) as pe:
        if pe.FILE_HEADER.Machine != 0x8664:
            raise ValueError("Expected Windows x64 native parser")
    return sizes


def smoke(bundle, directory):
    # Initialize the isolated DB before launch so Store does not seed real folders.
    database = directory / "release-smoke.sqlite3"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("CREATE TABLE preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO preferences VALUES ('initialized', 'true')")
    subprocess.run([str(bundle / "_internal/bin/replay-parser.exe"), "--version"], check=True, timeout=15)
    subprocess.run([str(bundle / f"{APP}.exe"), "--smoke-model"], cwd=bundle, check=True, timeout=30)
    subprocess.run([str(bundle / f"{APP}.exe"), "--database", str(database), "--smoke"],
                   cwd=bundle, check=True, timeout=30)
    with closing(sqlite3.connect(database)) as db:
        if db.execute("SELECT COUNT(*) FROM libraries").fetchone()[0]:
            raise ValueError("Release smoke unexpectedly configured replay libraries")


def package(version, bundle, output):
    version = version_name(version)
    if os.name != "nt":
        raise ValueError("Build and validate the Windows release on Windows")
    bundle = bundle.resolve()
    output = output.resolve()
    if output == bundle or bundle in output.parents:
        raise ValueError("Release output must be outside the distribution folder")
    files = payload_files(bundle)
    sizes = verify_binary(bundle)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{APP}-{version}-windows-x64.zip"
    temporary_archive = archive.with_suffix(".zip.partial")
    try:
        with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
            for path in files:
                zipped.write(path, str(Path(APP) / path.relative_to(bundle)))
            zipped.write(ROOT / "README.md", f"{APP}/README.md")
        # Test the extracted artifact, not just the developer's original folder.
        with tempfile.TemporaryDirectory(prefix="replay-release-") as directory:
            scratch = Path(directory)
            with zipfile.ZipFile(temporary_archive) as zipped:
                bad = zipped.testzip()
                if bad:
                    raise ValueError(f"Archive CRC check failed: {bad}")
                zipped.extractall(scratch)
            smoke(scratch / APP, scratch)
        temporary_archive.replace(archive)
    finally:
        temporary_archive.unlink(missing_ok=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_suffix(".zip.sha256")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    proof = {"version": version, "archive": archive.name, "bytes": archive.stat().st_size,
             "sha256": digest, "icon_sizes": sizes, "extracted_startup": "passed", "bundled_inference": "passed"}
    print(json.dumps(proof, indent=2))
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--bundle", type=Path, default=ROOT / "dist" / APP)
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    args = parser.parse_args()
    package(args.version, args.bundle, args.output)


if __name__ == "__main__":
    main()
