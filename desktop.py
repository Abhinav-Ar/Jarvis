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
HELPER = (
    Path.home()
    / "Applications"
    / "Jarvis Menu.app"
    / "Contents"
    / "MacOS"
    / "JarvisDesktopHelper"
)


def inspect_screen(question: str, application: str = "") -> dict:
    path = Path(tempfile.gettempdir()) / "jarvis-screen.png"
    started = time.perf_counter()
    try:
        if not HELPER.exists():
            return {"ok": False, "error": "The desktop helper is not installed."}
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
            "error": "Desktop control is off. The user must enable it from the Jarvis menu bar.",
        }
    if not HELPER.exists():
        return {"ok": False, "error": "The desktop helper is not installed."}
    if action == "click" and not TARGET_FILE.exists():
        return {"ok": False, "error": "Inspect a named target application before clicking."}
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
                    "error": f"Rejected click outside the display locked to {target['application']}.",
                }
        except (OSError, ValueError, KeyError, TypeError):
            return {"ok": False, "error": "Desktop target lock is invalid; inspect the target application again."}
    if action in {"type", "key"} and not confirmed:
        return {
            "ok": False,
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
