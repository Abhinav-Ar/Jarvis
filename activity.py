"""Low-latency user-visible activity state and local feedback cues."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse


RUNTIME = Path(os.getenv("JARVIS_RUNTIME_DIR", Path.home() / "Library/Application Support/Jarvis/.runtime"))
STATE_FILE = RUNTIME / "activity.json"
CHAT_FILE = RUNTIME / "chat.json"
ACTION_FILE = RUNTIME / "actions.json"
_lock = threading.Lock()


def update(state: str, label: str, detail: str = "") -> None:
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        temporary = STATE_FILE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"state": state, "label": label, "detail": detail, "updated": time.time()}),
            encoding="utf-8",
        )
        temporary.replace(STATE_FILE)
    except OSError:
        pass


def reset_ui() -> None:
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        CHAT_FILE.write_text("[]", encoding="utf-8")
        ACTION_FILE.write_text("[]", encoding="utf-8")
        (RUNTIME / "active-task.json").unlink(missing_ok=True)
        (RUNTIME / "hud-preview").unlink(missing_ok=True)
    except OSError:
        pass


def append_chat(role: str, text: str) -> None:
    if not text.strip():
        return
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        messages = json.loads(CHAT_FILE.read_text(encoding="utf-8")) if CHAT_FILE.exists() else []
        messages.append({"role": role, "text": text.strip(), "time": time.time()})
        CHAT_FILE.write_text(json.dumps(messages[-12:]), encoding="utf-8")
    except (OSError, ValueError, TypeError):
        pass


def describe_tool(name: str, arguments: dict) -> tuple[str, str]:
    labels = {
        "open_application": "OPEN APPLICATION", "quit_application": "CLOSE APPLICATION", "browser_navigate": "NAVIGATE BROWSER",
        "desktop_inspect": "ANALYZE BOTH SCREENS", "desktop_action": "CONTROL DESKTOP",
        "git_repositories": "SCAN REPOSITORIES", "git_status": "INSPECT CHANGES",
        "git_commit": "CREATE COMMIT", "git_commit_and_push": "COMMIT + PUSH",
        "spotify_control": "CONTROL SPOTIFY", "spotify_play_playlist": "PLAY PLAYLIST",
        "spotify_create_discovery_playlist": "BUILD PLAYLIST", "get_weather": "CHECK WEATHER",
        "open_search": "SEARCH WEB", "create_reminder": "CREATE REMINDER",
        "create_note": "CREATE NOTE", "create_calendar_event": "CREATE EVENT",
        "todoist_create_task": "CREATE TODOIST TASK", "system_status": "READ SYSTEM",
    }
    label = labels.get(name, name.replace("_", " ").upper())
    if name == "open_application":
        target = str(arguments.get("name", "application"))
    elif name == "browser_navigate":
        target = urlparse(str(arguments.get("url", ""))).netloc or "requested website"
    elif name.startswith("git_"):
        target = str(arguments.get("repository", "local repositories"))
    elif name == "desktop_action":
        action = arguments.get("action", "action")
        target = f"{action} at ({arguments.get('x')}, {arguments.get('y')})" if action == "click" else str(action)
    elif name.startswith("spotify_"):
        target = str(arguments.get("name") or arguments.get("query") or arguments.get("action") or "Spotify")
    elif name == "get_weather":
        target = str(arguments.get("location", "current location"))
    else:
        target = "authorized request"
    return label, target[:100]


def begin_action(name: str, arguments: dict) -> tuple[str, str]:
    action_id = uuid.uuid4().hex
    label, target = describe_tool(name, arguments)
    entry = {"id": action_id, "label": label, "target": target, "status": "running", "time": time.time()}
    with _lock:
        try:
            actions = json.loads(ACTION_FILE.read_text()) if ACTION_FILE.exists() else []
            actions.append(entry)
            ACTION_FILE.write_text(json.dumps(actions[-20:]))
        except (OSError, ValueError, TypeError):
            pass
    return action_id, f"{label.title()} — {target}"


def finish_action(action_id: str, result: dict) -> None:
    with _lock:
        try:
            actions = json.loads(ACTION_FILE.read_text()) if ACTION_FILE.exists() else []
            for action in actions:
                if action.get("id") == action_id:
                    action["status"] = "complete" if result.get("ok") else "failed"
                    action["finished"] = time.time()
                    if not result.get("ok"):
                        action["result"] = str(result.get("error", "Action failed"))[:120]
                    else:
                        action["result"] = "Completed and verified"
                    break
            ACTION_FILE.write_text(json.dumps(actions[-20:]))
        except (OSError, ValueError, TypeError):
            pass


def cue(kind: str) -> None:
    sounds = {
        "heard": "/System/Library/Sounds/Tink.aiff",
        "complete": "/System/Library/Sounds/Pop.aiff",
        "error": "/System/Library/Sounds/Basso.aiff",
    }
    sound = sounds.get(kind)
    if sound and Path(sound).exists() and os.getenv("JARVIS_CUES", "1") == "1":
        subprocess.Popen(
            ["/usr/bin/afplay", sound],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def acknowledge() -> None:
    if os.getenv("JARVIS_PROGRESS_SPEECH", "1") == "1":
        subprocess.Popen(
            ["/usr/bin/say", "On it."],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
