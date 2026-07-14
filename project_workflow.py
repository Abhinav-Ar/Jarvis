"""Complete local-first project session workflow."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_platform import platform
import git_tools
import mac_tools


def _commit(path: str) -> str:
    result = subprocess.run(
        ["/usr/bin/git", "-C", path, "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, timeout=15,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def start(repository: str) -> dict:
    state = git_tools.status(repository)
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
        return {"ok": False, "error": "No project session is active."}
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
