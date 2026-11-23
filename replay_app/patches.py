"""Estimate gameplay patches from the bundled Dota 2 release calendar."""

from bisect import bisect_right
import json

from replay_app.resources import ASSETS


_RELEASES = json.loads((ASSETS / "patch_dates.json").read_text(encoding="utf-8"))
_NAMES = tuple(_RELEASES)
_TIMESTAMPS = tuple(_RELEASES.values())
_VERSIONS = json.loads((ASSETS / "patch_server_versions.json").read_text(encoding="utf-8"))


def patch_for_version(version):
    return _VERSIONS.get(str(version), {}).get("patch")


def patch_at(timestamp):
    if type(timestamp) is not int or not _TIMESTAMPS[0] <= timestamp < 2**32:
        return None
    return _NAMES[bisect_right(_TIMESTAMPS, timestamp) - 1]
