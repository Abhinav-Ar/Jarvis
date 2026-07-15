"""Deterministic zero-planning lane for common local commands."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import mac_tools


def _tool(name: str, arguments: dict, request_id: str = "") -> dict:
    """Run fast-lane actions through the same supervisor as model-selected tools."""
    import tools
    return tools.execute(name, arguments, context={"request_id": request_id, "task_id": ""})


def _stage(application: str, request_id: str = "") -> None:
    try:
        import desktop
        import activity
        result = _tool("desktop_window_arrange", {"applications": [application], "confirmed": True}, request_id)
        activity.record_step("stage_application_window", application, result)
    except Exception:
        pass


def execute(text: str, request_id: str = "") -> str | None:
    raw = " ".join(text.lower().strip().split()).rstrip(".,!?")
    raw = re.sub(r"^(?:hey|okay|ok|please)[, ]+", "", raw)
    workspace_match = re.fullmatch(
        r"(?:open|launch) (.+?) and (.+?)(?:,)? (?:"
        r"then (?:arrange|tile) (?:them|the windows)(?: .*)?"
        r"|and (?:create|make|set up) (?:a )?(?:balanced )?workspace(?: .*)?"
        r")",
        raw,
    )
    tile_match = re.fullmatch(r"(?:arrange|tile) (.+?) and (.+?) side by side", raw)
    if workspace_match or tile_match:
        import activity
        import desktop
        match = workspace_match or tile_match
        applications = [mac_tools.canonical_application_name(match.group(1)), mac_tools.canonical_application_name(match.group(2))]
        if all(mac_tools.application_exists(application) for application in applications):
            activity.set_execution_path(
                f"Prepare a two-application workspace for {applications[0]} and {applications[1]}",
                ["Open both applications", "Exit fullscreen if necessary", "Move both windows to one display", "Tile the windows", "Verify both frames"],
            )
            activity.update("working", "Preparing workspace…", " • ".join(applications))
            result = _tool("desktop_window_arrange", {"applications": applications, "confirmed": True}, request_id)
            activity.record_step("arrange_two_app_workspace", ", ".join(applications), result)
            if result.get("ok"):
                if result.get("layout") == "stack":
                    return (
                        f"I arranged {applications[0]} and {applications[1]} in an even stacked workspace "
                        "because their minimum widths would make a side-by-side layout cramped on this display."
                    )
                return f"{applications[0]} and {applications[1]} are arranged in a balanced side-by-side workspace."
            return f"I couldn’t finish the window layout. {result.get('error', 'The window state could not be verified.')}"
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
        result = _tool("browser_navigate", {"url": address, "browser": "Safari"}, request_id)
        host = urlparse(result.get("url", "")).netloc.removeprefix("www.")
        if result.get("ok"):
            _stage("Safari", request_id)
            return (f"Safari is open on {host or address}." if combined_navigation else
                    f"{host or address} is open in Safari.")

    installation_status = (
        re.fullmatch(r"is (?:(?:a|the) )?(.+?) installed(?: yet)?", raw)
        or re.fullmatch(r"has (?:(?:a|the) )?(.+?) finished installing", raw)
        or re.fullmatch(r"(?:check |check whether )?(?:(?:a|the) )?(.+?) installation status", raw)
    )
    if installation_status:
        import app_installer
        return app_installer.status_summary(installation_status.group(1).strip())

    # Known multi-step workflows own their prerequisite, recovery, and
    # verification loops locally. GPT is only used if no deterministic workflow
    # recognizes the request.
    import execution_engine
    workflow_reply = execution_engine.try_execute(text)
    if workflow_reply:
        return workflow_reply

    command = " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())
    for prefix in ("hey ", "okay ", "ok ", "please "):
        if command.startswith(prefix):
            command = command[len(prefix):]

    if command in {
        "status", "orion status", "agent status", "what are you working on",
        "what are you doing", "operating status",
    }:
        from orion_kernel import kernel
        status = kernel().status()
        active = status.get("active_goal", {}).get("goal")
        goal = f" I’m currently tracking: {active['objective']}." if active else " I don’t have an active goal."
        return (
            f"ORION is online with {status['adapters']} adapters, {status['memories']} layered memories, "
            f"and {status['event_rules']} active monitors.{goal}"
        )

    if command in {"list workflows", "show workflows", "what workflows do you know", "what can you automate"}:
        from orion_kernel import kernel
        items = kernel().workflows().get("workflows", [])
        if not items:
            return "I don’t have any taught workflows yet."
        names = ", ".join(item["name"] for item in items[:8])
        return f"I know {len(items)} workflow{'s' if len(items) != 1 else ''}: {names}."

    if command in {"capability status", "capabilities", "worker families", "what worker families are available"}:
        import capability_families
        state = capability_families.status()
        available = [item["name"] for item in state["families"] if item["available"]]
        blocked = [item["name"] for item in state["families"] if not item["available"]]
        return f"Available families: {', '.join(available)}. Awaiting setup: {', '.join(blocked)}."

    if command in {"generation status", "codex status", "what is codex working on", "is codex finished"}:
        import generation
        result = generation.job_status()
        job = result.get("job")
        if not job:
            return result.get("message", "No generation job has been started.")
        if job["status"] == "running":
            return f"Codex job {job['id']} is still working in {Path(job['workspace']).name}."
        if job["status"] == "completed":
            summary = str(job.get("result", "")).strip()
            return f"Codex job {job['id']} finished. {summary[:300]}".strip()
        return f"Codex job {job['id']} is {job['status']}."

    taught = re.fullmatch(
        r"teach (?:orion )?(?:a )?workflow(?: named| called)? (.+?): when i say (.+?), (?:do |you should )?(.+)",
        raw,
    )
    if taught:
        from orion_kernel import kernel
        name, trigger, procedure = (part.strip() for part in taught.groups())
        steps = [part.strip(" ,") for part in re.split(r"\s*(?:,?\s+then\s+|;)\s*", procedure) if part.strip(" ,")]
        result = kernel().teach_workflow(name, trigger, steps)
        if result.get("ok"):
            return f"I learned {name}. Say “{trigger}” and I’ll follow its {len(steps)} saved steps."

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
        result = _tool("spotify_control", {"action": "pause"}, request_id)
        return "Paused." if result.get("ok") else None
    if command in {"resume the music", "resume spotify", "play spotify"}:
        import spot
        result = _tool("spotify_control", {"action": "play"}, request_id)
        return "Playing." if result.get("ok") else None
    if command in {"skip", "skip this song", "next song"}:
        import spot
        result = _tool("spotify_control", {"action": "next"}, request_id)
        return "Skipped." if result.get("ok") else None
    if command in {"previous", "previous song", "go back a song"}:
        import spot
        result = _tool("spotify_control", {"action": "previous"}, request_id)
        return "Going back." if result.get("ok") else None

    playlist_match = re.fullmatch(r"(?:play|start|open) (?:my )?(?:spotify )?playlist (?:named |called )?(.+?)(?: on spotify)?", command)
    if playlist_match:
        import spot
        name = playlist_match.group(1).strip()
        result = _tool("spotify_play_playlist", {"name": name}, request_id)
        return f"Playing {result.get('name', name)}." if result.get("ok") else None

    project_close_match = re.fullmatch(
        r"(?:close|quit) everything(?: on my (?:laptop|mac|computer))? related to (?:the )?(.+?) (?:project|workspace)",
        command,
    )
    if project_close_match:
        import project_workflow
        result = project_workflow.close_workspace(project_close_match.group(1).strip())
        if result.get("ok"):
            closed = ", ".join(result.get("closed_applications", [])) or "the project workspace"
            warning = f" {result['warning']}" if result.get("warning") else ""
            return f"Closed {closed} for the {result['repository']} project.{warning}".strip()
        return None

    close_match = re.fullmatch(r"(?:close|quit|exit)(?: out of)? (?:the )?(.+?)(?: app| application)?", command)
    if close_match:
        requested = close_match.group(1).strip()
        if requested in {"current", "current app", "this", "this app", "active app"}:
            requested = mac_tools.frontmost_application()
        app = mac_tools.canonical_application_name(requested)
        result = _tool("quit_application", {"name": app}, request_id)
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
        result = _tool("open_application", {"name": app}, request_id)
        if result.get("ok"):
            _stage(app, request_id)
        return f"{app} is open." if result.get("ok") else None

    volume_match = re.fullmatch(r"set (?:the )?volume to (\d{1,3})(?: percent)?", command)
    if volume_match:
        level = min(100, int(volume_match.group(1)))
        _tool("set_system_volume", {"level": level}, request_id)
        return f"Volume set to {level} percent."
    if command in {"mute", "mute the volume", "mute my mac"}:
        _tool("set_system_volume", {"level": 0}, request_id)
        return "Muted."
    if command in {"computer status", "system status", "battery status", "how is my laptop doing"}:
        result = _tool("system_status", {}, request_id)
        if result.get("ok"):
            battery = result.get("battery_percent")
            power = " and charging" if result.get("power_connected") else ""
            return f"Battery is at {battery:.0f} percent{power}." if battery is not None else "Your Mac is running normally."
    return None
