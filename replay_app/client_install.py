"""Install an explicitly pinned Dota Steam build into a separate directory."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from tempfile import NamedTemporaryFile, TemporaryDirectory

from replay_app.resources import ASSETS


RECEIPT = "replay-client.json"
EXECUTABLE = Path("game/bin/win64/dota2.exe")
STEAM_INFO = Path("game/dota/steam.inf")
ORIGINAL_STEAM_INFO = STEAM_INFO.with_name("steam.inf.replay-original")
VERSION_ENDPOINT = b"https://api.steampowered.com/IGCVersion_570/GetClientVersion/v1?format=xml"
BUILTIN_RECIPE = ASSETS / "client_7.20e.json"


def load_recipe(path):
    return validate_recipe(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def validate_recipe(recipe):
    if (not isinstance(recipe, dict) or recipe.get("app_id") != 570 or not isinstance(recipe.get("patch"), str)
            or not re.fullmatch(r"[0-9]+\.[0-9]{2}[a-z]?", recipe["patch"])):
        raise ValueError("Choose a Dota 2 recipe with a gameplay patch name and app ID 570")
    if type(recipe.get("server_version")) is not int or recipe["server_version"] <= 0:
        raise ValueError("The recipe needs a numeric Dota server version")
    depots = recipe.get("depots", {})
    if not isinstance(depots, dict) or not depots or not all(re.fullmatch(r"[1-9][0-9]*", value) for value in depots):
        raise ValueError("The recipe needs numeric depot IDs")
    missing = [depot for depot, manifest in depots.items()
               if not isinstance(manifest, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", manifest) or int(manifest) >= 2**64]
    if missing:
        raise ValueError(f"The {recipe['patch']} recipe needs historical manifest IDs for depots {', '.join(missing)}")
    return recipe


def download_command(downloader, recipe, destination, *, qr=False, preflight=False):
    depots = recipe["depots"]
    args = [str(downloader), "-app", str(recipe["app_id"]), "-depot", *depots,
            "-manifest", *depots.values(), "-dir", str(destination)]
    if qr:
        args.append("-qr")
    return args + (["-manifest-only"] if preflight else ["-validate"])


def check_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"Use a regular folder without links or junctions: {path}")


@contextmanager
def install_lock(path):
    if path.is_symlink():
        raise ValueError(f"Unexpected link at {path}")
    with path.open("a+b") as lock:
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError(f"An install is already running for {path.stem}") from exc
        yield


def client_executable(root, recipe):
    for relative in (EXECUTABLE, "game/bin/win64/engine2.dll", "game/dota/bin/win64/client.dll",
                     "game/dota/gameinfo.gi", "game/dota/maps/dota.vpk", "game/dota/pak01_dir.vpk"):
        file = root / relative
        if not file.is_file() or not file.stat().st_size:
            raise ValueError(f"The downloaded client is missing {relative}")
    backup = root / ORIGINAL_STEAM_INFO
    info = (backup if backup.is_file() else root / STEAM_INFO).read_text(encoding="utf-8-sig")
    if not re.search(rf"^ServerVersion\s*=\s*{recipe['server_version']}\s*$", info, flags=re.MULTILINE):
        raise ValueError(f"The downloaded files do not match Dota server version {recipe['server_version']}")
    return root / EXECUTABLE


def write_atomically(path, data):
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def configure_update_prompt(root, suppress):
    """Apply or restore the version-check configuration in a verified pinned install."""
    info, backup = root / STEAM_INFO, root / ORIGINAL_STEAM_INFO
    check_directory(info.parent.parent)
    check_directory(info.parent)
    if info.is_symlink() or backup.is_symlink():
        raise ValueError("The pinned client version files must be regular files.")
    active = info.read_bytes()
    original = backup.read_bytes() if backup.is_file() else active
    if not suppress and not backup.is_file():
        return
    adjusted = original
    for field in (b"ClientVersion", b"ServerVersion"):
        line = rb"(?m)^((?:\xef\xbb\xbf)?" + field + rb"[ \t]*=[ \t]*)[0-9]+(?=[ \t]*\r?$)"
        adjusted, count = re.subn(line, lambda match: match[1] + VERSION_ENDPOINT, adjusted)
        if count != 1:
            raise ValueError(f"Expected one numeric {field.decode()} in the pinned client's original steam.inf.")
    if active not in (original, adjusted):
        raise ValueError("The pinned client's steam.inf has local edits. Review them before changing the update prompt setting.")
    if suppress and not backup.is_file():
        write_atomically(backup, original)
    desired = adjusted if suppress else original
    if active != desired:
        write_atomically(info, desired)


def install_client(recipe_path, parent, downloader, *, qr=False, preflight=False, suppress_update_prompt=True):
    recipe = validate_recipe(recipe_path) if isinstance(recipe_path, dict) else load_recipe(recipe_path)
    parent = Path(parent).expanduser().absolute()
    if any(part.casefold() in {"steamapps", ".."} for part in parent.parts):
        raise ValueError("Choose a pinned-client folder outside Steam’s library")
    for folder in (*reversed(parent.parents), parent):
        check_directory(folder)
    target = parent / f"Dota2_{recipe['patch']}"
    staging = target.with_name(target.name + (".preflight" if preflight else ".installing"))
    lock = staging.with_name(f".{staging.name}.lock")
    with install_lock(lock):
        if (target.exists() or target.is_symlink()) and not preflight:
            check_directory(target)
            receipt = target / RECEIPT
            if receipt.is_file() and same_build(load_recipe(receipt), recipe):
                executable = client_executable(target, recipe)
                configure_update_prompt(target, suppress_update_prompt)
                return executable
            raise ValueError(f"A different install already exists at {target}")
        downloader = Path(downloader).expanduser().resolve(strict=True)
        if not downloader.is_file():
            raise ValueError("Select the DepotDownloader executable")
        staging.mkdir(exist_ok=True)
        check_directory(staging)
        marker = staging / (RECEIPT + ".pending")
        if marker.is_file():
            if not same_build(load_recipe(marker), recipe):
                raise ValueError(f"The staging directory belongs to a different recipe: {staging}")
        else:
            if any(staging.iterdir()):
                raise ValueError(f"Use a new staging directory: {staging}")
            marker.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
        command = download_command(downloader, recipe, staging, qr=qr, preflight=preflight)
        log_path = staging / "depot-download.log"
        # DepotDownloader writes its session state relative to its working directory.
        with TemporaryDirectory(prefix="dotabased-depot-") as working:
            if qr:
                result = subprocess.run(command, cwd=working, shell=False,
                                        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            else:
                with log_path.open("w", encoding="utf-8") as log:
                    result = subprocess.run(command, cwd=working, shell=False, stdout=log, stderr=subprocess.STDOUT,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            detail = "Steam authentication console" if qr else str(log_path)
            raise ValueError(f"Steam download failed with exit code {result.returncode}. See {detail}.")
        manifests = staging / ".DepotDownloader"
        missing = [depot for depot, manifest in recipe["depots"].items()
                   if not (manifests / f"{depot}_{manifest}.manifest").is_file()]
        if missing:
            sign_in = " Try signing in with the Steam QR code." if not qr else ""
            raise ValueError(f"Steam did not provide all required depots ({', '.join(missing)}).{sign_in}")
        if preflight:
            return staging
        exe = client_executable(staging, recipe)
        configure_update_prompt(staging, suppress_update_prompt)
        app_id = exe.with_name("steam_appid.txt")
        if not app_id.exists():
            app_id.write_text("570\n", encoding="ascii")
        (staging / RECEIPT).write_text(json.dumps(recipe, indent=2), encoding="utf-8")
        staging.rename(target)
        (target / marker.name).unlink()
        return target / EXECUTABLE


def same_build(first, second):
    return all(first.get(key) == second.get(key) for key in ("patch", "app_id", "steam_build", "server_version")) and (
        list(first["depots"].items()) == list(second["depots"].items())
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, default=BUILTIN_RECIPE)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--depot-downloader", type=Path, required=True)
    parser.add_argument("--qr", action="store_true", help="Authenticate directly in DepotDownloader with Steam Guard")
    parser.add_argument("--preflight", action="store_true", help="Check manifest access without downloading game content")
    parser.add_argument("--keep-update-prompt", action="store_true", help="Keep or restore the pinned client's original version check")
    args = parser.parse_args()
    try:
        print(install_client(args.recipe, args.parent, args.depot_downloader, qr=args.qr, preflight=args.preflight,
                             suppress_update_prompt=not args.keep_update_prompt))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
