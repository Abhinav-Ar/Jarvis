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


def _setting(name: str, default: str = "") -> str:
    return os.getenv(f"ORION_{name}", os.getenv(f"JARVIS_{name}", default))


RUNTIME = Path(_setting("RUNTIME_DIR", str(Path.home() / "Library/Application Support/Jarvis/.runtime")))
STATE_FILE = RUNTIME / "activity.json"
CHAT_FILE = RUNTIME / "chat.json"
ACTION_FILE = RUNTIME / "actions.json"
PLAN_FILE = RUNTIME / "ui-plan.json"
BACKGROUND_TASK_FILE = RUNTIME / "background-task.json"
SESSION_UI_FILE = RUNTIME / "session-ui-active"
TEXT_COMMAND_DIR = RUNTIME / "text-commands"
_lock = threading.Lock()
_announcement_lock = threading.Lock()
_last_announcements: dict[str, float] = {}
_announcement_process: subprocess.Popen | None = None


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
        PLAN_FILE.write_text("{}", encoding="utf-8")
        (RUNTIME / "active-task.json").unlink(missing_ok=True)
        (RUNTIME / "hud-preview").unlink(missing_ok=True)
        SESSION_UI_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def begin_session_ui() -> None:
    """Open the conversational HUD only after an actionable request exists."""
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        SESSION_UI_FILE.touch()
    except OSError:
        pass


def end_session_ui() -> None:
    try:
        SESSION_UI_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def text_command_pending() -> bool:
    try:
        return TEXT_COMMAND_DIR.is_dir() and any(TEXT_COMMAND_DIR.glob("*.json"))
    except OSError:
        return False


def take_text_command() -> str:
    """Atomically consume the oldest command submitted by the native HUD."""
    try:
        if not TEXT_COMMAND_DIR.is_dir():
            return ""
        for path in sorted(TEXT_COMMAND_DIR.glob("*.json"), key=lambda item: (item.stat().st_mtime, item.name)):
            claimed = path.with_suffix(".processing")
            try:
                path.replace(claimed)
            except OSError:
                continue
            try:
                payload = json.loads(claimed.read_text(encoding="utf-8"))
                text = str(payload.get("text", "")).strip()[:8000]
            except (OSError, ValueError, TypeError):
                text = ""
            finally:
                claimed.unlink(missing_ok=True)
            if text:
                return text
    except OSError:
        pass
    return ""


def clear_text_commands() -> None:
    try:
        if TEXT_COMMAND_DIR.is_dir():
            for path in TEXT_COMMAND_DIR.iterdir():
                if path.suffix in {".json", ".processing"}:
                    path.unlink(missing_ok=True)
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


def set_execution_path(goal: str, steps: list[str]) -> None:
    """Publish a local workflow plan for the HUD without requiring a model plan."""
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        PLAN_FILE.write_text(
            json.dumps({"goal": goal, "steps": steps, "updated": time.time()}),
            encoding="utf-8",
        )
    except OSError:
        pass


def update_background_task(
    task_id: str,
    title: str,
    phase: str,
    *,
    status: str = "running",
    step: int = 1,
    total_steps: int = 4,
    detail: str = "",
    route: str = "",
) -> None:
    """Publish a truthful, compact status for work that outlives a voice turn."""
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        previous: dict = {}
        if BACKGROUND_TASK_FILE.exists():
            try:
                previous = json.loads(BACKGROUND_TASK_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = {}
        now = time.time()
        started = previous.get("started", now) if previous.get("id") == task_id else now
        payload = {
            "id": task_id,
            "title": title,
            "phase": phase,
            "status": status,
            "step": max(1, min(int(step), max(1, int(total_steps)))),
            "total_steps": max(1, int(total_steps)),
            "detail": detail,
            "route": route,
            "started": started,
            "updated": now,
        }
        temporary = BACKGROUND_TASK_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(BACKGROUND_TASK_FILE)
    except (OSError, TypeError, ValueError):
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
        "blender_create_project": "GENERATE BLENDER PROJECT",
        "blender_refine_project": "REFINE BLENDER PROJECT",
        "blender_create_advanced_project": "PROCEDURAL MODELING",
        "blender_resume_advanced_project": "RESUME PROCEDURAL MODEL",
        "native_project_open": "LOAD NATIVE PROJECT",
        "freecad_create_project": "GENERATE FREECAD PROJECT",
        "openscad_create_project": "COMPILE OPENSCAD PROJECT",
        "resolve_create_project": "BUILD RESOLVE PROJECT",
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
    elif name in {"desktop_window_arrange", "desktop_window_restore"}:
        target = ", ".join(arguments.get("applications", [])) or "application windows"
    elif name.startswith("spotify_"):
        target = str(arguments.get("name") or arguments.get("query") or arguments.get("action") or "Spotify")
    elif name in {"blender_create_project", "blender_refine_project", "blender_create_advanced_project", "blender_resume_advanced_project", "freecad_create_project", "openscad_create_project", "resolve_create_project"}:
        target = str(arguments.get("project_name") or "native project")
    elif name == "native_project_open":
        target = f"{arguments.get('project_name') or 'latest project'} in {arguments.get('application') or 'native app'}"
    elif name == "get_weather":
        target = str(arguments.get("location", "current location"))
    else:
        target = str(arguments.get("target") or "authorized request")
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
    milestone_speech = {
        "desktop_inspect": "I’m checking the active screens now.",
        "git_commit_and_push": "I’ve reached the Git operation. I’m committing, pushing, and then verifying it.",
        "spotify_create_discovery_playlist": "I’m analyzing your recent listening before I build the playlist.",
        "project_session_start": "I’m opening the project and rebuilding its working context.",
    }
    if name in milestone_speech:
        announce(milestone_speech[name], key=f"tool:{name}")
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
                        supervision = result.get("_supervision", {}) if isinstance(result.get("_supervision"), dict) else {}
                        verified_detail = ""
                        if supervision.get("verified"):
                            checks = ", ".join(str(item).replace("_", " ") for item in supervision.get("checks", [])[:2])
                            attempts = int(supervision.get("attempts", 1) or 1)
                            verified_detail = f"Verified{f' after {attempts} attempts' if attempts > 1 else ''}{f' • {checks}' if checks else ''}"
                        action["result"] = str(
                            result.get("_activity_detail") or result.get("summary") or
                            result.get("message") or verified_detail or "Completed and verified"
                        )[:160]
                    break
            ACTION_FILE.write_text(json.dumps(actions[-20:]))
        except (OSError, ValueError, TypeError):
            pass


def record_step(label: str, target: str, result: dict) -> None:
    """Add deterministic workflow evidence to the same feed as model tools."""
    action_id, _ = begin_action(label, {"target": target})
    finish_action(action_id, {**result, "_activity_detail": target})


def announce(message: str, key: str = "", minimum_interval: float = 8.0) -> None:
    """Speak only meaningful milestones, with de-duplication to avoid chatter."""
    if _setting("PROGRESS_SPEECH", "1") != "1" or not message.strip():
        return
    identity = key or message.lower().strip()
    global _announcement_process
    with _announcement_lock:
        now = time.monotonic()
        if now - _last_announcements.get(identity, 0.0) < minimum_interval:
            return
        _last_announcements[identity] = now
        if _announcement_process is not None and _announcement_process.poll() is None:
            _announcement_process.terminate()
        _announcement_process = subprocess.Popen(
            ["/usr/bin/say", message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def stop_announcements() -> None:
    """Give final responses exclusive ownership of speech output."""
    global _announcement_process
    with _announcement_lock:
        if _announcement_process is not None and _announcement_process.poll() is None:
            _announcement_process.terminate()
        _announcement_process = None


def cue(kind: str) -> None:
    sounds = {
        "heard": "/System/Library/Sounds/Tink.aiff",
        "complete": "/System/Library/Sounds/Pop.aiff",
        "error": "/System/Library/Sounds/Basso.aiff",
    }
    sound = sounds.get(kind)
    if sound and Path(sound).exists() and _setting("CUES", "1") == "1":
        subprocess.Popen(
            ["/usr/bin/afplay", sound],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def acknowledge() -> None:
    if _setting("PROGRESS_SPEECH", "1") == "1":
        announce("On it.", key="acknowledge", minimum_interval=2.0)
