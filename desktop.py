"""Permission-gated macOS screen inspection and bounded input actions."""

from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import time
from pathlib import Path

from openai import OpenAI
import diagnostics


RUNTIME_DIR = Path.home() / "Library" / "Application Support" / "Jarvis" / ".runtime"
CONTROL_FLAG = RUNTIME_DIR / "desktop-control-enabled"
HELPER = (
    Path.home()
    / "Applications"
    / "Jarvis Menu.app"
    / "Contents"
    / "MacOS"
    / "JarvisDesktopHelper"
)


def inspect_screen(question: str) -> dict:
    path = Path(tempfile.gettempdir()) / "jarvis-screen.png"
    started = time.perf_counter()
    try:
        if not HELPER.exists():
            return {"ok": False, "error": "The desktop helper is not installed."}
        capture = subprocess.run(
            [str(HELPER), "screenshot", str(path)], check=True,
            capture_output=True, text=True, timeout=30,
        )
        display_mapping = capture.stdout.strip()
        diagnostics.event(
            "desktop_capture_completed",
            duration_ms=round((time.perf_counter() - started) * 1000),
            mapping=display_mapping,
        )
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
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
