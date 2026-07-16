"""Permission-gated macOS screen inspection and bounded input actions."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from openai import OpenAI
import diagnostics
import mac_tools
from agent_platform import platform


RUNTIME_DIR = Path.home() / "Library" / "Application Support" / "Jarvis" / ".runtime"
CONTROL_FLAG = RUNTIME_DIR / "desktop-control-enabled"
TARGET_FILE = RUNTIME_DIR / "last-desktop-target.json"
WINDOW_STATE_FILE = RUNTIME_DIR / "window-layouts.json"
HELPER = (
    Path.home()
    / "Applications"
    / "Jarvis Menu.app"
    / "Contents"
    / "MacOS"
    / "JarvisDesktopHelper"
)


def _helper_json(arguments: list[str], timeout: int = 20) -> dict:
    try:
        result = subprocess.run(
            [str(HELPER), *arguments], check=True, capture_output=True,
            text=True, timeout=timeout,
        )
        return json.loads(result.stdout.strip() or '{"ok":true}')
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        lowered = detail.lower()
        if "accessibility permission" in lowered:
            code = "accessibility_permission_required"
        elif "disabled" in lowered:
            code = "control_disabled"
        elif "no accessible" in lowered:
            code = "control_not_found"
        elif "no movable window" in lowered or "no window for fullscreen" in lowered:
            code = "window_unavailable"
        elif "fullscreen" in lowered:
            code = "fullscreen_recovery_failed"
        else:
            code = "accessibility_action_failed"
        return {"ok": False, "error": detail, "error_code": code, "retryable": code in {"control_not_found", "window_unavailable"}}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "error_code": "desktop_helper_failed"}


def accessibility_snapshot(application: str, selector: str = "") -> dict:
    """Inspect labelled controls locally without a screenshot or model call."""
    if not HELPER.exists():
        return {"ok": False, "error_code": "helper_not_installed", "error": "The desktop helper is not installed."}
    activation = mac_tools.open_application(application)
    if not activation.get("frontmost"):
        return {"ok": False, "error_code": "application_not_frontmost", "retryable": True, "error": f"{application} could not be brought forward."}
    arguments = ["inspect-ui", application]
    if selector:
        arguments.append(selector)
    return _helper_json(arguments)


def local_ocr(application: str) -> dict:
    """Read visible application text on-device with Apple's Vision framework."""
    if not HELPER.exists():
        return {"ok": False, "error_code": "helper_not_installed", "error": "The desktop helper is not installed."}
    activation = mac_tools.open_application(application)
    if not activation.get("frontmost"):
        return {"ok": False, "error_code": "application_not_frontmost", "retryable": True, "error": f"{application} could not be brought forward."}
    return _helper_json(["ocr-app", application], timeout=30)


def accessibility_press(application: str, selector: str, confirmed: bool = False) -> dict:
    if not CONTROL_FLAG.exists():
        return {"ok": False, "error_code": "control_disabled", "error": "Desktop control is off."}
    if not confirmed:
        return {"ok": False, "error_code": "confirmation_required", "confirmation_required": True, "error": "Pressing this control requires explicit authorization."}
    result = accessibility_snapshot(application, selector)
    if not result.get("ok"):
        return result
    matches = result.get("elements", [])
    if not matches:
        return {"ok": False, "error_code": "control_not_found", "retryable": True, "error": f"No labelled control matched {selector}."}
    if not any(element.get("enabled") for element in matches):
        return {"ok": False, "error_code": "control_disabled", "retryable": True, "error": f"The {selector} control is disabled."}
    return _helper_json(["press-ui", application, selector])


def accessibility_set(application: str, selector: str, text: str, confirmed: bool = False) -> dict:
    if not CONTROL_FLAG.exists():
        return {"ok": False, "error_code": "control_disabled", "error": "Desktop control is off."}
    if not confirmed:
        return {"ok": False, "error_code": "confirmation_required", "confirmation_required": True, "error": "Filling this field requires explicit authorization."}
    forbidden = ("password", "passcode", "security code", "credit card", "token", "secret")
    if any(word in selector.lower() for word in forbidden):
        return {"ok": False, "error_code": "sensitive_field", "requires_user": True, "error": "ORION will not fill sensitive fields."}
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return _helper_json(["set-ui", application, selector, encoded])


def _window_states() -> dict:
    try:
        return json.loads(WINDOW_STATE_FILE.read_text(encoding="utf-8")) if WINDOW_STATE_FILE.exists() else {}
    except (OSError, ValueError, TypeError):
        return {}


def arrange_windows(applications: list[str], confirmed: bool = False) -> dict:
    """Stage one or two application windows beside the HUD and remember their frames."""
    if not CONTROL_FLAG.exists():
        return {"ok": False, "error_code": "control_disabled", "error": "Desktop control is off."}
    if not confirmed:
        return {"ok": False, "error_code": "confirmation_required", "confirmation_required": True, "error": "Window arrangement requires explicit authorization."}
    names = list(dict.fromkeys(mac_tools.canonical_application_name(value) for value in applications if value.strip()))[:2]
    if not names:
        return {"ok": False, "error_code": "missing_application", "requires_user": True, "error": "At least one application is required."}
    states = _window_states()
    results: list[dict] = []
    display_id = ""
    if len(names) == 2:
        display_result = _helper_json(["list-displays", "all"])
        displays = display_result.get("displays", []) if display_result.get("ok") else []
        if displays:
            # A two-app workspace should use the display that can provide the
            # most useful balanced canvas. This also avoids squeezing a second
            # app beside an application with a large minimum window width.
            preferred = max(
                displays,
                key=lambda item: float(item.get("frame", {}).get("width", 0))
                * float(item.get("frame", {}).get("height", 0)),
            )
            display_id = str(preferred.get("id", ""))
    for index, name in enumerate(names):
        opened = mac_tools.open_application(name)
        if not opened.get("ok"):
            return opened
        snapshot = _helper_json(["window-state", name])
        if snapshot.get("ok") and name not in states:
            original = dict(snapshot.get("frame", {}))
            original["fullscreen"] = bool(snapshot.get("fullscreen"))
            states[name] = original
            try:
                WINDOW_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                WINDOW_STATE_FILE.write_text(json.dumps(states), encoding="utf-8")
            except OSError:
                pass
        layout = "focus" if len(names) == 1 else ("tile-left" if index == 0 else "tile-right-adaptive")
        if index == 1 and results and results[0].get("display_frame") and results[0].get("frame"):
            display = results[0]["display_frame"]
            first = results[0]["frame"]
            x = float(first["x"]) + float(first["width"]) + 10
            width = float(display["x"]) + float(display["width"]) - 12 - x
            arguments = [
                "window-place", name, str(x), str(float(display["y"]) + 34),
                str(max(240, width)), str(max(180, float(display["height"]) - 58)),
            ]
        else:
            fallback_layout = "focus" if len(names) == 1 else ("tile-left" if index == 0 else "tile-right")
            arguments = ["window-layout", name, fallback_layout, "0"]
            if display_id:
                arguments.append(display_id)
        result = _helper_json(arguments)
        if not result.get("ok") and result.get("retryable"):
            time.sleep(0.35)
            mac_tools.open_application(name)
            result = _helper_json(arguments)
            result["recovery_attempted"] = "reactivate_and_normalize_window"
        if not result.get("ok"):
            diagnostics.event(
                "window_layout_failed", level="warning", application=name, layout=layout,
                error_code=result.get("error_code", ""), error=result.get("error", ""),
                recovery=result.get("recovery_attempted", ""),
            )
            return result
        display_id = str(result.get("display_id", display_id))
        if name not in states:
            original = dict(result.get("original", {}))
            original["fullscreen"] = bool(result.get("exited_fullscreen"))
            states[name] = original
        results.append(result)
        diagnostics.event(
            "window_layout_verified", application=name, layout=layout,
            display_id=result.get("display_id"), frame=result.get("frame", {}),
            exited_fullscreen=bool(result.get("exited_fullscreen")),
        )
    if len(results) == 2 and results[0].get("display_frame"):
        display = results[0]["display_frame"]
        first, second = results[0].get("frame", {}), results[1].get("frame", {})
        display_right = float(display["x"]) + float(display["width"])
        overlap = min(float(first.get("x", 0)) + float(first.get("width", 0)), float(second.get("x", 0)) + float(second.get("width", 0))) - max(float(first.get("x", 0)), float(second.get("x", 0)))
        first_width = float(first.get("width", 0))
        second_width = float(second.get("width", 0))
        balance_ratio = max(first_width, second_width) / max(1, min(first_width, second_width))
        invalid_horizontal = (
            overlap > 18
            or float(second.get("x", 0)) + second_width > display_right + 18
            or balance_ratio > 1.25
        )
        if invalid_horizontal:
            # Negotiate a vertical stage when the apps' own minimum widths make a
            # non-overlapping horizontal split impossible on this display.
            x = float(display["x"]) + 12
            y = float(display["y"]) + 34
            width = float(display["width"]) - 24
            usable_height = float(display["height"]) - 58
            half = (usable_height - 10) / 2
            top = _helper_json(["window-place", names[0], str(x), str(y), str(width), str(half)])
            bottom = _helper_json(["window-place", names[1], str(x), str(y + half + 10), str(width), str(half)])
            if not top.get("ok") or not bottom.get("ok"):
                failed = top if not top.get("ok") else bottom
                diagnostics.event("window_layout_failed", level="warning", application="; ".join(names), layout="vertical_fallback", error=failed.get("error", ""))
                return failed
            top["layout"] = "stack-top"
            bottom["layout"] = "stack-bottom"
            results = [top, bottom]
            diagnostics.event(
                "window_layout_recovered", applications=names,
                recovery="balanced_vertical_constraint_layout", previous_width_ratio=round(balance_ratio, 2),
                frames=[top.get("frame", {}), bottom.get("frame", {})],
            )
    try:
        WINDOW_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        WINDOW_STATE_FILE.write_text(json.dumps(states), encoding="utf-8")
    except OSError:
        pass
    return {"ok": True, "applications": names, "display_id": display_id, "windows": results, "layout": "focus" if len(names) == 1 else ("stack" if results[0].get("layout") == "stack-top" else "tile")}


def restore_windows(applications: list[str] | None = None, confirmed: bool = False) -> dict:
    """Restore windows moved by Jarvis to their pre-session frames."""
    if not confirmed:
        return {"ok": False, "error_code": "confirmation_required", "confirmation_required": True, "error": "Window restoration requires explicit authorization."}
    states = _window_states()
    requested = set(applications or states.keys())
    restored: list[str] = []
    failures: list[str] = []
    for name, frame in list(states.items()):
        if name not in requested:
            continue
        if not all(key in frame for key in ("x", "y", "width", "height")):
            continue
        if not mac_tools.application_exists(name):
            states.pop(name, None)
            continue
        if frame.get("fullscreen"):
            # A fullscreen frame includes the menu-bar area and cannot be restored
            # as an ordinary window. Restore the semantic state directly instead.
            result = _helper_json(["window-fullscreen", name, "true"])
            if not result.get("ok"):
                time.sleep(0.75)
                result = _helper_json(["window-fullscreen", name, "true"])
                result["recovery_attempted"] = "wait_for_space_transition"
        else:
            result = _helper_json([
                "window-frame", name, str(frame["x"]), str(frame["y"]),
                str(frame["width"]), str(frame["height"]),
            ])
        if result.get("ok"):
            restored.append(name)
            states.pop(name, None)
            diagnostics.event(
                "window_layout_restored", application=name,
                fullscreen=bool(frame.get("fullscreen")), frame=frame,
            )
        else:
            diagnostics.event(
                "window_layout_restore_failed", level="warning", application=name,
                fullscreen=bool(frame.get("fullscreen")), error=result.get("error", ""),
                recovery=result.get("recovery_attempted", ""),
            )
            failures.append(name)
    try:
        WINDOW_STATE_FILE.write_text(json.dumps(states), encoding="utf-8")
    except OSError:
        pass
    return {"ok": not failures, "restored": restored, "failed": failures}


def inspect_screen(question: str, application: str = "") -> dict:
    path = Path(tempfile.gettempdir()) / "jarvis-screen.png"
    started = time.perf_counter()
    try:
        if not HELPER.exists():
            return {"ok": False, "error_code": "helper_not_installed", "error": "The desktop helper is not installed."}
        helper_arguments = [str(HELPER), "screenshot", str(path)]
        if application.strip():
            activation = mac_tools.open_application(application.strip())
            if not activation.get("frontmost"):
                return {"ok": False, "error": f"{application} could not be brought to the foreground."}
            helper_arguments = [str(HELPER), "screenshot-app", str(path), application.strip()]
        capture = subprocess.run(
            helper_arguments, check=True,
            capture_output=True, text=True, timeout=30,
        )
        display_mapping = capture.stdout.strip()
        mapping = json.loads(display_mapping)
        if application.strip() and mapping.get("displays"):
            target = {"application": application.strip(), "display": mapping["displays"][0]}
            TARGET_FILE.write_text(json.dumps(target), encoding="utf-8")
        else:
            TARGET_FILE.unlink(missing_ok=True)
        diagnostics.event(
            "desktop_capture_completed",
            duration_ms=round((time.perf_counter() - started) * 1000),
            mapping=display_mapping,
        )
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        agent = platform()
        allowed, reason = agent.cloud_allowed("vision")
        if not allowed:
            return {"ok": False, "error": reason}
        client = OpenAI()
        response = client.responses.create(
            model=os.getenv("OPENAI_VISION_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.4-mini")),
            reasoning={"effort": "none"},
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Analyze this current macOS screenshot for the user's request. "
                                "Describe only what is relevant. When interaction is requested, "
                                "identify the screen number and include physical global coordinates "
                                "for relevant controls by applying the supplied montage mapping. "
                                "Never transcribe passwords, authentication codes, payment details, "
                                "or private keys. Display mapping: " + display_mapping +
                                ". Target application: " + (application or "all displays") +
                                ". Request: " + question
                            ),
                        },
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{encoded}",
                            "detail": "high",
                        },
                    ],
                }
            ],
        )
        agent.record_cloud(
            "vision", os.getenv("OPENAI_VISION_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.4-mini")), response
        )
        diagnostics.event(
            "desktop_vision_completed",
            duration_ms=round((time.perf_counter() - started) * 1000),
            analysis_chars=len(response.output_text),
        )
        return {"ok": True, "analysis": response.output_text.strip()}
    finally:
        path.unlink(missing_ok=True)


def perform_action(
    action: str,
    x: int,
    y: int,
    text: str,
    key: str,
    amount: int,
    confirmed: bool,
) -> dict:
    if not CONTROL_FLAG.exists():
        return {
            "ok": False,
            "error_code": "control_disabled",
            "error": "Desktop control is off. The user must enable it from the ORION menu bar.",
        }
    if not HELPER.exists():
        return {"ok": False, "error_code": "helper_not_installed", "error": "The desktop helper is not installed."}
    if action == "click" and not TARGET_FILE.exists():
        return {"ok": False, "error_code": "inspection_required", "retryable": True, "error": "Inspect a named target application before clicking."}
    if action == "click" and TARGET_FILE.exists():
        try:
            target = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
            display = target["display"]
            inside = (
                float(display["global_x"]) <= x <= float(display["global_x"]) + float(display["global_width"])
                and float(display["global_y"]) <= y <= float(display["global_y"]) + float(display["global_height"])
            )
            if not inside:
                return {
                    "ok": False,
                    "error_code": "display_lock_violation",
                    "error": f"Rejected click outside the display locked to {target['application']}.",
                }
        except (OSError, ValueError, KeyError, TypeError):
            return {"ok": False, "error_code": "inspection_required", "retryable": True, "error": "Desktop target lock is invalid; inspect the target application again."}
    if action in {"type", "key"} and not confirmed:
        return {
            "ok": False,
            "error_code": "confirmation_required",
            "confirmation_required": True,
            "error": "Typing and keyboard submission require explicit user confirmation.",
        }
    arguments = [str(HELPER), action]
    if action == "click":
        arguments += [str(int(x)), str(int(y))]
    elif action == "type":
        arguments += [base64.b64encode(text.encode("utf-8")).decode("ascii")]
    elif action == "key":
        arguments += [key.lower()]
    elif action == "scroll":
        arguments += [str(int(amount))]
    else:
        return {"ok": False, "error": f"Unsupported desktop action: {action}"}
    subprocess.run(arguments, check=True, timeout=15)
    return {"ok": True, "action": action}
