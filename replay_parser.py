"""Read Dota replay summary records without parsing the entire game stream.

Wire fields follow SteamDatabase/Protobufs dota2/demo.proto. No network or writes.
"""
from pathlib import Path
import math
import re
import struct

MAX_SUMMARY = 16 * 1024 * 1024
STEAM_BASE = 76561197960265728


class ReplayError(ValueError):
    pass


def varint(data, pos=0):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise ReplayError("Truncated varint")
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, pos
    raise ReplayError("Oversized varint")


def snappy(data):
    """Decode a bounded raw Snappy block (all four tag forms)."""
    expected, pos = varint(data)
    if expected > MAX_SUMMARY:
        raise ReplayError("Summary exceeds size limit")
    output = bytearray()
    while pos < len(data):
        tag = data[pos]
        pos += 1
        kind = tag & 3
        if kind == 0:
            length = tag >> 2
            if length < 60:
                length += 1
            else:
                width = length - 59
                if pos + width > len(data):
                    raise ReplayError("Truncated Snappy literal length")
                length = int.from_bytes(data[pos:pos + width], "little") + 1
                pos += width
            if pos + length > len(data) or len(output) + length > expected:
                raise ReplayError("Invalid Snappy literal")
            output.extend(data[pos:pos + length])
            pos += length
        else:
            width = {1: 1, 2: 2, 3: 4}[kind]
            if pos + width > len(data):
                raise ReplayError("Truncated Snappy copy")
            offset = int.from_bytes(data[pos:pos + width], "little")
            pos += width
            if kind == 1:
                offset |= (tag & 224) << 3
                length = 4 + ((tag >> 2) & 7)
            else:
                length = 1 + (tag >> 2)
            if offset <= 0 or offset > len(output) or len(output) + length > expected:
                raise ReplayError("Invalid Snappy copy")
            # Copy may overlap itself; repeat only the needed prefix of the window.
            window = bytes(output[-offset:])
            output.extend((window * ((length + offset - 1) // offset))[:length])
    if len(output) != expected:
        raise ReplayError("Snappy size mismatch")
    return bytes(output)


def fields(data):
    result = {}
    pos = 0
    while pos < len(data):
        key, pos = varint(data, pos)
        number, wire = key >> 3, key & 7
        if not number:
            raise ReplayError("Invalid protobuf field")
        if wire == 0:
            value, pos = varint(data, pos)
        elif wire in (1, 5):
            width = 8 if wire == 1 else 4
            if pos + width > len(data):
                raise ReplayError("Truncated fixed field")
            value = data[pos:pos + width]
            pos += width
        elif wire == 2:
            length, pos = varint(data, pos)
            if length > MAX_SUMMARY or pos + length > len(data):
                raise ReplayError("Truncated length-delimited field")
            value = data[pos:pos + length]
            pos += length
        else:
            raise ReplayError(f"Unsupported protobuf wire type {wire}")
        result.setdefault(number, []).append(value)
    return result


def first(mapping, field, default=None):
    return mapping.get(field, [default])[0]


def text(mapping, field):
    value = first(mapping, field, b"")
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else ""


def decode_summary(payload):
    info = fields(payload)
    game = fields(first(info, 4, b""))
    dota = fields(first(game, 4, b""))
    if not dota:
        raise ReplayError("No Dota summary in replay")
    players = []
    for raw in dota.get(4, []):
        player = fields(raw)
        steam_id = first(player, 4, 0)
        account = steam_id - STEAM_BASE if STEAM_BASE < steam_id < STEAM_BASE + 2**32 else None
        if first(player, 3, 0):
            account = None
        players.append({"account_id": account, "name": text(player, 2),
                        "hero": text(player, 1).removeprefix("npc_dota_hero_"),
                        "team": first(player, 5), "steam_id": str(steam_id)})
    raw_duration = first(info, 1)
    duration = struct.unpack("<f", raw_duration)[0] if isinstance(raw_duration, bytes) and len(raw_duration) == 4 else None
    if duration is not None and (not math.isfinite(duration) or duration < 0):
        duration = None
    return {"match_id": str(first(dota, 1)) if first(dota, 1) else None,
            "game_mode": first(dota, 2), "winner": first(dota, 3),
            "league_id": first(dota, 5), "end_time": first(dota, 11),
            "duration": duration,
            "players": players, "source": "Replay summary"}


def parse_replay(path):
    path = Path(path)
    with path.open("rb") as stream:
        header = stream.read(16)
        if len(header) < 12 or header[:8] not in (b"PBUFDEM\x00", b"PBDEMS2\x00"):
            raise ReplayError("Unsupported replay header (expected PBUFDEM or PBDEMS2)")
        offset = struct.unpack_from("<I", header, 8)[0]
        size = path.stat().st_size
        if not 12 <= offset < size:
            raise ReplayError("No complete file-info footer (replay may be incomplete)")
        stream.seek(offset)
        prefix = stream.read(30)
        command, pos = varint(prefix)
        _, pos = varint(prefix, pos)  # playback tick
        length, pos = varint(prefix, pos)
        if command & 15 != 2 or length > MAX_SUMMARY or offset + pos + length > size:
            raise ReplayError("Invalid file-info record")
        stream.seek(offset + pos)
        payload = stream.read(length)
        if command & (64 | 112):
            payload = snappy(payload)
        result = decode_summary(payload)
        result["format"] = header[:7].decode("ascii")
        if not result["match_id"]:
            result["match_id"] = filename_match_id(path)
        return result


def filename_match_id(path):
    match = re.fullmatch(r"(\d+)(?:_\d+)?\.dem", Path(path).name, re.I)
    return match.group(1) if match else None
