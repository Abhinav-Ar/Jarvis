"""Low-latency user-visible activity state and local feedback cues."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path


RUNTIME = Path(os.getenv("JARVIS_RUNTIME_DIR", Path.home() / "Library/Application Support/Jarvis/.runtime"))
STATE_FILE = RUNTIME / "activity.json"


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
