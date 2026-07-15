"""Universal observe-act-verify supervision for every ORION tool call."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import diagnostics
from agent_platform import platform


RUNTIME = Path(os.getenv("ORION_RUNTIME_DIR") or os.getenv("JARVIS_RUNTIME_DIR") or Path.home() / "Library/Application Support/Jarvis/.runtime")
CANCEL_FILE = RUNTIME / "cancel-current-task"
LATEST_FILE = RUNTIME / "execution-state.json"

SAFE_RETRY_TOOLS = {
    "get_weather", "open_search", "system_status", "find_contact", "find_files",
    "git_repositories", "git_status", "installation_status", "generation_status",
    "desktop_inspect", "desktop_accessibility_inspect", "desktop_local_ocr",
    "open_application", "browser_navigate", "desktop_window_arrange",
}


def begin_request(request_id: str) -> None:
    """Clear cancellation left over from an older request, never a live one."""
    try:
        if not CANCEL_FILE.exists():
            return
        payload = _read_json(CANCEL_FILE)
        if not payload or str(payload.get("request_id", "")) != request_id:
            CANCEL_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def request_cancel(request_id: str = "", source: str = "user") -> dict:
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        CANCEL_FILE.write_text(
            json.dumps({"request_id": request_id, "source": source, "created": time.time()}),
            encoding="utf-8",
        )
        diagnostics.event("execution_cancel_requested", request_id=request_id, source=source)
        return {"ok": True, "cancel_requested": True}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def clear_cancel() -> None:
    CANCEL_FILE.unlink(missing_ok=True)


def cancellation_requested(request_id: str = "") -> bool:
    if not CANCEL_FILE.exists():
        return False
    payload = _read_json(CANCEL_FILE)
    target = str(payload.get("request_id", "")) if payload else ""
    return not target or not request_id or target == request_id


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _application_running(name: str) -> bool | None:
    try:
        import psutil
        import mac_tools
        canonical = mac_tools.canonical_application_name(name)
        candidates = set(mac_tools.APP_PROCESS_NAMES.get(canonical, [canonical]))
        return any(process.info.get("name") in candidates for process in psutil.process_iter(["name"]))
    except Exception:
        return None


def snapshot(tool: str, arguments: dict) -> dict:
    """Capture small, local, task-relevant state instead of a full screen dump."""
    state: dict[str, Any] = {"captured": time.time(), "tool": tool}
    try:
        import mac_tools
        state["frontmost_application"] = mac_tools.frontmost_application()
    except Exception:
        pass
    if tool in {"open_application", "quit_application"}:
        name = str(arguments.get("name", ""))
        state["target_application"] = name
        state["target_running"] = _application_running(name)
    elif tool.startswith("git_") and arguments.get("repository"):
        try:
            import git_tools
            state["repository"] = git_tools.status(str(arguments["repository"]))
            state["synchronization"] = git_tools.sync_status(str(arguments["repository"]))
        except Exception as exc:
            state["observation_error"] = str(exc)[:300]
    elif tool in {"install_application", "installation_status"}:
        try:
            import app_installer
            state["installation"] = app_installer.status(
                application=str(arguments.get("application", "")),
                job_id=str(arguments.get("job_id", "")),
            )
        except Exception:
            pass
    elif tool in {"native_project_open", "blender_create_project", "blender_refine_project", "blender_create_advanced_project", "freecad_create_project", "openscad_create_project", "resolve_create_project"}:
        state["project"] = str(arguments.get("project_name", ""))[:200]
        state["application"] = str(arguments.get("application", ""))[:100]
    return state


def verify(tool: str, arguments: dict, result: dict, after: dict) -> dict:
    """Convert weak success claims into explicit evidence contracts."""
    if not result.get("ok"):
        return {"ok": False, "verified": False, "reason": str(result.get("error", "Action failed"))[:500]}
    checks: list[str] = []
    verified = True
    if tool == "open_application":
        verified = bool(result.get("frontmost")) and after.get("target_running") is not False
        checks.append("application_running_and_frontmost")
    elif tool == "quit_application":
        verified = bool(result.get("closed")) and after.get("target_running") is not True
        checks.append("application_process_exited")
    elif tool == "browser_navigate":
        verified = bool(result.get("url")) and result.get("frontmost") is not False
        checks.append("browser_opened_requested_url")
    elif tool == "git_commit":
        verified = bool(result.get("working_tree_clean") or result.get("already_clean"))
        checks.append("working_tree_clean")
    elif tool in {"git_push", "git_commit_and_push"}:
        sync = after.get("synchronization", {})
        verified = sync.get("ahead") in {0, None} and bool(sync.get("working_tree_clean", True))
        checks.extend(["working_tree_clean", "branch_not_ahead_of_remote"])
    elif tool == "native_project_open":
        verified = bool(result.get("loaded"))
        checks.append("exact_native_project_loaded")
    elif tool == "install_application" and result.get("status") == "running":
        verified = True
        checks.append("durable_installation_job_started")
    else:
        checks.append("tool_returned_success_evidence")
    return {
        "ok": verified,
        "verified": verified,
        "checks": checks,
        "reason": "" if verified else "The action returned success but its observable completion contract was not satisfied.",
    }


def _publish(payload: dict) -> None:
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        temporary = LATEST_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(diagnostics.redact(payload), default=str), encoding="utf-8")
        temporary.replace(LATEST_FILE)
    except OSError:
        pass


def execute(
    tool: str, arguments: dict, handler: Callable[[], dict], *,
    task_id: str = "", request_id: str = "",
) -> dict:
    """Observe, checkpoint, act, verify, recover once when safe, and journal."""
    if cancellation_requested(request_id):
        return {
            "ok": False, "cancelled": True, "error_code": "task_cancelled",
            "error": "The task was cancelled before the next action began.",
        }
    risk = platform().risk_for(tool)
    if risk in {"reversible", "consequential"}:
        duplicate = platform().verified_execution(request_id, tool, arguments)
        if duplicate:
            diagnostics.event(
                "duplicate_action_prevented", request_id=request_id, task_id=task_id,
                tool=tool, prior_checkpoint=duplicate.get("id", ""), risk=risk,
            )
            return {
                "ok": True, "duplicate_prevented": True,
                "message": "This exact action was already completed and verified in the current request.",
                "_supervision": {
                    "checkpoint_id": duplicate.get("id", ""), "risk": risk,
                    "attempts": 0, "verified": True,
                    "checks": ["identical_action_already_verified"],
                },
            }
    health = platform().tool_failure_window(tool)
    if int(health.get("failures", 0)) >= 3:
        diagnostics.event(
            "execution_circuit_opened", request_id=request_id, task_id=task_id,
            tool=tool, failures=health.get("failures"),
            latest_error_code=health.get("latest_error_code", ""),
        )
        return {
            "ok": False, "error_code": "tool_circuit_open",
            "alternative_route_required": True, "retryable": False,
            "error": (
                f"{tool.replace('_', ' ')} has failed repeatedly, so ORION stopped using that route "
                "temporarily and must choose a different adapter or wait for the cooldown."
            ),
            "failures": int(health.get("failures", 0)),
            "cooldown_seconds": int(health.get("cooldown_seconds", 120)),
        }
    checkpoint_id = uuid.uuid4().hex
    before = snapshot(tool, arguments)
    platform().begin_execution_checkpoint(
        checkpoint_id, task_id, request_id, tool, risk, arguments, before,
    )
    _publish({"checkpoint_id": checkpoint_id, "task_id": task_id, "request_id": request_id, "tool": tool, "phase": "acting", "risk": risk, "before": before})
    diagnostics.event(
        "execution_checkpoint_created", request_id=request_id, task_id=task_id,
        checkpoint_id=checkpoint_id, tool=tool, risk=risk,
    )
    attempts = 0
    result: dict = {}
    verification: dict = {}
    maximum_attempts = 2 if tool in SAFE_RETRY_TOOLS else 1
    while attempts < maximum_attempts:
        if cancellation_requested(request_id):
            result = {"ok": False, "cancelled": True, "error_code": "task_cancelled", "error": "The task was cancelled before the next attempt."}
            break
        attempts += 1
        try:
            result = dict(handler() or {})
        except Exception as exc:
            result = {"ok": False, "error": str(exc), "error_code": f"{tool}_failed"}
        after = snapshot(tool, arguments)
        verification = verify(tool, arguments, result, after)
        if result.get("ok") and verification.get("verified"):
            break
        retryable = (
            not result.get("recovery_attempted")
            and (bool(result.get("retryable")) or (result.get("ok") and not verification.get("verified")))
        )
        if not retryable or attempts >= maximum_attempts or result.get("requires_user"):
            break
        diagnostics.event(
            "execution_recovery_retry", request_id=request_id, task_id=task_id,
            checkpoint_id=checkpoint_id, tool=tool, attempt=attempts + 1,
            error_code=result.get("error_code", "verification_failed"),
        )
        time.sleep(0.15)
    after = snapshot(tool, arguments)
    verification = verify(tool, arguments, result, after)
    result["_supervision"] = {
        "checkpoint_id": checkpoint_id, "risk": risk, "attempts": attempts,
        "verified": bool(verification.get("verified")), "checks": verification.get("checks", []),
    }
    if result.get("ok") and not verification.get("verified"):
        result.update(
            ok=False, error_code="completion_not_verified", retryable=False,
            error=str(verification.get("reason") or "The outcome could not be verified."),
        )
    if not result.get("ok") and not result.get("cancelled") and tool == "desktop_window_arrange":
        try:
            import desktop
            rollback = desktop.restore_windows(
                applications=list(arguments.get("applications", [])), confirmed=True,
            )
            result["_rollback"] = {
                "attempted": True, "ok": bool(rollback.get("ok")),
                "restored": rollback.get("restored", []),
            }
            diagnostics.event(
                "execution_rollback", request_id=request_id, task_id=task_id,
                checkpoint_id=checkpoint_id, tool=tool, ok=bool(rollback.get("ok")),
                restored=rollback.get("restored", []),
            )
        except Exception as exc:
            result["_rollback"] = {"attempted": True, "ok": False, "error": str(exc)[:300]}
    status = (
        "cancelled" if result.get("cancelled")
        else "needs_user" if result.get("requires_user")
        else "verified" if result.get("ok")
        else "failed"
    )
    platform().finish_execution_checkpoint(
        checkpoint_id, status, after, attempts, str(result.get("error_code", "")),
    )
    _publish({
        "checkpoint_id": checkpoint_id, "task_id": task_id, "request_id": request_id,
        "tool": tool, "phase": status, "risk": risk, "attempts": attempts,
        "verification": verification, "after": after, "updated": time.time(),
    })
    diagnostics.event(
        "execution_supervised", request_id=request_id, task_id=task_id,
        checkpoint_id=checkpoint_id, tool=tool, risk=risk, attempts=attempts,
        status=status, verified=bool(verification.get("verified")),
        error_code=result.get("error_code", ""),
    )
    try:
        from orion_kernel import kernel
        kernel().observe(
            "execution.last_action",
            {"tool": tool, "status": status, "verified": bool(verification.get("verified")), "task_id": task_id, "after": after},
            "execution_supervisor", ttl=3600,
        )
    except Exception:
        pass
    return result
