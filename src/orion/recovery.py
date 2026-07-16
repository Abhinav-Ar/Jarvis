"""Structured local failure classification and bounded deterministic recovery."""

from __future__ import annotations

from typing import Callable

import diagnostics
import mac_tools


def normalize(result: dict | None, *, action: str = "") -> dict:
    result = dict(result or {})
    if action == "open_application" and result.get("ok") and result.get("frontmost") is False:
        result.update(ok=False, error_code="application_not_frontmost", retryable=True, error="The application opened but did not become frontmost.")
    if result.get("ok") or result.get("error_code"):
        return result
    text = str(result.get("error", "")).lower()
    rules = (
        (("no active device", "connect device"), "playback_device_unavailable", True, False),
        (("permission", "accessibility"), "permission_required", False, True),
        (("still open", "unsaved"), "unsaved_changes_dialog", False, True),
        (("not found", "no accessible"), "target_not_found", False, True),
        (("disabled",), "control_disabled", True, False),
        (("timed out", "timeout"), "timeout", True, False),
        (("network", "resolve host", "failed to connect"), "network_unavailable", True, False),
        (("confirmation",), "confirmation_required", False, True),
    )
    for markers, code, retryable, requires_user in rules:
        if any(marker in text for marker in markers):
            result.update(error_code=code, retryable=retryable, requires_user=requires_user)
            break
    else:
        result.update(error_code=f"{action}_failed" if action else "action_failed", retryable=False, requires_user=False)
    return result


def execute(action: str, arguments: dict, handler: Callable[..., dict]) -> dict:
    """Run one tool and apply only known, safe, single-retry repairs."""
    try:
        result = normalize(handler(**arguments), action=action)
    except Exception as exc:
        result = normalize({"ok": False, "error": str(exc)}, action=action)
    repaired = ""
    if not result.get("ok") and result.get("retryable"):
        if action == "open_application":
            repaired = "reactivate_application"
        elif action.startswith("spotify_") or action == "spotify_control":
            activation = mac_tools.open_application("Spotify")
            if activation.get("ok"):
                repaired = "activate_spotify_device"
        if repaired:
            diagnostics.event("local_recovery_started", tool=action, repair=repaired, error_code=result.get("error_code"))
            try:
                retry = normalize(handler(**arguments), action=action)
            except Exception as exc:
                retry = normalize({"ok": False, "error": str(exc)}, action=action)
            retry["recovery_attempted"] = repaired
            retry["initial_error_code"] = result.get("error_code", "")
            diagnostics.event("local_recovery_finished", tool=action, repair=repaired, ok=bool(retry.get("ok")))
            return retry
    return result


def should_escalate(result: dict) -> bool:
    """Unknown failures may use a model; known user/permission blockers may not."""
    return not result.get("ok") and not result.get("requires_user") and not result.get("error_code")
