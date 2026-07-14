"""Complete local-first project session workflow."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_platform import platform
import git_tools
import mac_tools
import desktop
import activity


def _commit(path: str) -> str:
    result = subprocess.run(
        ["/usr/bin/git", "-C", path, "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, timeout=15,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def start(repository: str) -> dict:
    activity.set_execution_path(
        f"Open and restore the {repository} project context",
        ["Inspect repository state", "Index authorized project context", "Open project applications", "Stage the workspace", "Verify the session"],
    )
    try:
        state = git_tools.status(repository)
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "error_code": "project_not_found", "requires_user": True, "error": str(exc)}
    if not state.get("ok"):
        return state
    path = state["path"]
    session = platform().start_project_session(
        state["repository"], path, state["branch"], _commit(path), state,
    )
    platform().index_paths([Path(path)], maximum_files=300)
    opened = []
    for application in ("GitHub Desktop", "Visual Studio Code"):
        if mac_tools.application_exists(application):
            try:
                mac_tools.open_application(application)
                opened.append(application)
            except Exception:
                pass
    if opened:
        arranged = desktop.arrange_windows(opened[:2], confirmed=True)
        activity.record_step("stage_project_workspace", ", ".join(opened[:2]), arranged)
    return {
        **session, "branch": state["branch"], "path": path,
        "changed_files": len(state["changed_files"]), "opened": opened,
        "message": "Project session started and local context indexed.",
    }


def resume(repository: str) -> dict:
    previous = platform().latest_project_session(repository).get("session")
    result = start(repository)
    if result.get("ok") and previous:
        result["previous_notes"] = previous.get("notes", "")
        result["previous_status"] = previous.get("status", "")
    return result


def status() -> dict:
    active = platform().active_project_session().get("session")
    if not active:
        return {"ok": True, "active": False, "message": "No project session is active."}
    state = git_tools.status(active["path"])
    return {
        "ok": True, "active": True, "session_id": active["id"],
        "repository": active["repository"], "branch": state.get("branch", active["branch"]),
        "changed_files": len(state.get("changed_files", [])),
        "diff_summary": state.get("diff_summary", ""), "started": active["started"],
    }


def close(notes: str = "") -> dict:
    active = platform().active_project_session().get("session")
    if not active:
        return {"ok": False, "error_code": "no_active_project", "requires_user": True, "error": "No project session is active."}
    state = git_tools.status(active["path"])
    if not state.get("ok"):
        return state
    changed = len(state["changed_files"])
    summary = notes.strip() or (
        f"Ended on {state['branch']} with {changed} uncommitted file{'s' if changed != 1 else ''}."
    )
    closed = platform().close_project_session(active["id"], _commit(active["path"]), state, summary)
    platform().remember(f"project:{active['repository']}:last_session", summary, source="project_session")
    return {
        **closed, "repository": active["repository"], "branch": state["branch"],
        "changed_files": changed, "warning": "Uncommitted work remains." if changed else "",
        "summary": summary,
    }
