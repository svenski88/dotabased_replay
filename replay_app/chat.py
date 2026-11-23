"""Read-only presentation of locally recorded chat; no API fallback."""


def chat_lines(match):
    if match.get("chat_complete") is not True:
        return "Chat has not been parsed. Use Parse Selected or Parse All to recover recorded chat.\nUnsupported or incomplete recordings may not provide a chat log."
    entries = match.get("chat", [])
    if not entries:
        return "No chat messages were found in this recording. Only chat stored in the replay can be shown."
    lines = []
    for entry in entries:
        seconds = entry.get("time")
        if seconds is None:
            timestamp = f"Tick {entry['tick']}"
        else:
            minutes, seconds_part = divmod(int(abs(seconds)), 60)
            timestamp = f"{'-' if seconds < 0 else ''}{minutes:02}:{seconds_part:02}"
        speaker = entry.get("speaker") or "Unknown player"
        lines.append(f"[{timestamp}] [{entry['channel']}] {speaker}: {entry['text']}")
    return "\n".join(lines)
