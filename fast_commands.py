"""Deterministic zero-planning lane for common local commands."""

from __future__ import annotations

import re

import mac_tools


def execute(text: str) -> str | None:
    command = " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())
    for prefix in ("hey ", "okay ", "ok ", "please "):
        if command.startswith(prefix):
            command = command[len(prefix):]

    if command in {"stop the music", "pause the music", "pause spotify", "stop spotify"}:
        import spot
        result = spot.control("pause")
        return "Paused." if result.get("ok") else None
    if command in {"resume the music", "resume spotify", "play spotify"}:
        import spot
        result = spot.control("play")
        return "Playing." if result.get("ok") else None
    if command in {"skip", "skip this song", "next song"}:
        import spot
        result = spot.control("next")
        return "Skipped." if result.get("ok") else None

    app_match = re.fullmatch(r"(?:open|launch)(?: up)? (safari|spotify|github desktop|mail|calendar|notes)", command)
    if app_match:
        app = app_match.group(1).title().replace("Github", "GitHub")
        result = mac_tools.open_application(app)
        return f"{app} is open." if result.get("ok") else None

    volume_match = re.fullmatch(r"set (?:the )?volume to (\d{1,3})(?: percent)?", command)
    if volume_match:
        level = min(100, int(volume_match.group(1)))
        mac_tools.set_system_volume(level)
        return f"Volume set to {level} percent."
    return None
