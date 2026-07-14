"""Deterministic zero-planning lane for common local commands."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import mac_tools


def execute(text: str) -> str | None:
    raw = " ".join(text.lower().strip().split()).rstrip(".,!?")
    raw = re.sub(r"^(?:hey|okay|ok|please)[, ]+", "", raw)
    combined_navigation = re.fullmatch(
        r"(?:open|launch) safari (?:and|then|and then) (?:open|go to|navigate to) (https?://\S+|(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:/\S*)?)",
        raw,
    )
    navigation_match = re.fullmatch(
        r"(?:open|go to|navigate to)(?: (?:safari|the browser))?(?: and (?:open|go to))? (https?://\S+|(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:/\S*)?)",
        raw,
    )
    match = combined_navigation or navigation_match
    if match:
        address = match.group(1)
        result = mac_tools.open_url(address, "Safari")
        host = urlparse(result.get("url", "")).netloc.removeprefix("www.")
        if result.get("ok"):
            return (f"Safari is open on {host or address}." if combined_navigation else
                    f"{host or address} is open in Safari.")

    command = " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())
    for prefix in ("hey ", "okay ", "ok ", "please "):
        if command.startswith(prefix):
            command = command[len(prefix):]

    project_match = re.fullmatch(r"(?:start|begin) (?:a )?project(?: session)? (?:for )?(.+)", command)
    resume_match = re.fullmatch(r"resume (?:the )?(?:project )?(?:session )?(?:for )?(.+)", command)
    if project_match or resume_match:
        import project_workflow
        repository = (project_match or resume_match).group(1).strip()
        result = project_workflow.start(repository) if project_match else project_workflow.resume(repository)
        if result.get("ok"):
            return f"{'Started' if project_match else 'Resumed'} the {result['repository']} project session on {result['branch']}."
        return None
    if command in {"project status", "project session status", "what is my project status"}:
        import project_workflow
        result = project_workflow.status()
        if not result.get("active"):
            return result.get("message")
        return f"{result['repository']} is active on {result['branch']} with {result['changed_files']} changed files."
    if command in {"end project", "end project session", "close project session", "finish project session"}:
        import project_workflow
        result = project_workflow.close()
        if result.get("ok"):
            return f"Closed the {result['repository']} project session. {result.get('warning', '')}".strip()
        return None

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
    if command in {"previous", "previous song", "go back a song"}:
        import spot
        result = spot.control("previous")
        return "Going back." if result.get("ok") else None

    playlist_match = re.fullmatch(r"(?:play|start|open) (?:my )?(?:spotify )?playlist (?:named |called )?(.+?)(?: on spotify)?", command)
    if playlist_match:
        import spot
        name = playlist_match.group(1).strip()
        result = spot.play_playlist(name)
        return f"Playing {result.get('name', name)}." if result.get("ok") else None

    close_match = re.fullmatch(r"(?:close|quit|exit)(?: out of)? (?:the )?(.+?)(?: app| application)?", command)
    if close_match:
        requested = close_match.group(1).strip()
        if requested in {"current", "current app", "this", "this app", "active app"}:
            requested = mac_tools.frontmost_application()
        app = mac_tools.canonical_application_name(requested)
        result = mac_tools.quit_application(app)
        if result.get("ok"):
            return f"{app} is closed."
        error = result.get("error", "")
        return f"I couldn't close {app}. {error}".strip()

    app_match = re.fullmatch(r"(?:open|launch|start)(?: up)? (?:the )?([a-z0-9][a-z0-9 +._-]*?)(?: app| application)?", command)
    if app_match:
        requested = app_match.group(1).strip()
        if not mac_tools.application_exists(requested):
            return None
        app = mac_tools.canonical_application_name(requested)
        result = mac_tools.open_application(app)
        return f"{app} is open." if result.get("ok") else None

    volume_match = re.fullmatch(r"set (?:the )?volume to (\d{1,3})(?: percent)?", command)
    if volume_match:
        level = min(100, int(volume_match.group(1)))
        mac_tools.set_system_volume(level)
        return f"Volume set to {level} percent."
    if command in {"mute", "mute the volume", "mute my mac"}:
        mac_tools.set_system_volume(0)
        return "Muted."
    if command in {"computer status", "system status", "battery status", "how is my laptop doing"}:
        result = mac_tools.system_status()
        if result.get("ok"):
            battery = result.get("battery_percent")
            power = " and charging" if result.get("power_connected") else ""
            return f"Battery is at {battery:.0f} percent{power}." if battery is not None else "Your Mac is running normally."
    return None
