"""Rotated, structured, privacy-aware diagnostic events for Jarvis."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any


RUNTIME = Path(os.getenv("JARVIS_RUNTIME_DIR", Path.home() / "Library/Application Support/Jarvis/.runtime"))
EVENT_FILE = RUNTIME / "events.jsonl"
MAX_BYTES = int(os.getenv("JARVIS_DIAGNOSTIC_MAX_BYTES", "5000000"))
BACKUPS = int(os.getenv("JARVIS_DIAGNOSTIC_BACKUPS", "5"))
_lock = threading.Lock()


def _redact(value: Any, key: str = "") -> Any:
    if any(word in key.lower() for word in ("key", "secret", "token", "password", "authorization")):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED_API_KEY]", value)
        return value[:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:500]


def redact(value: Any) -> Any:
    """Public redaction helper for other persistent local journals."""
    return _redact(value)


def _rotate() -> None:
    if not EVENT_FILE.exists() or EVENT_FILE.stat().st_size < MAX_BYTES:
        return
    oldest = EVENT_FILE.with_suffix(f".jsonl.{BACKUPS}")
    oldest.unlink(missing_ok=True)
    for index in range(BACKUPS - 1, 0, -1):
        source = EVENT_FILE.with_suffix(f".jsonl.{index}")
        if source.exists():
            source.replace(EVENT_FILE.with_suffix(f".jsonl.{index + 1}"))
    EVENT_FILE.replace(EVENT_FILE.with_suffix(".jsonl.1"))


def event(name: str, *, level: str = "info", request_id: str = "", **fields: Any) -> None:
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "epoch": time.time(),
        "level": level,
        "event": name,
        "request_id": request_id,
        "pid": os.getpid(),
        **_redact(fields),
    }
    with _lock:
        try:
            RUNTIME.mkdir(parents=True, exist_ok=True)
            _rotate()
            with EVENT_FILE.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass
