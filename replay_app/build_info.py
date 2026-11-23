"""Version metadata shared by the desktop app and release packager."""
import json

from replay_app.resources import RESOURCE_ROOT


BUILD_INFO = "build-info.json"


def read_build_version(root=RESOURCE_ROOT):
    metadata = json.loads((root / BUILD_INFO).read_text(encoding="utf-8-sig"))
    if not isinstance(metadata, dict) or not isinstance(metadata.get("version"), str) or not metadata["version"]:
        raise ValueError("Build metadata needs a version")
    return metadata["version"]


def display_version():
    try:
        return read_build_version()
    except FileNotFoundError:
        return "Development build"
