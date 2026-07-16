"""Asynchronous, bounded artifact-generation workers supervised by ORION."""

from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import diagnostics
import git_tools


RUNTIME = Path(os.getenv("ORION_RUNTIME_DIR") or os.getenv("JARVIS_RUNTIME_DIR") or Path.cwd() / ".runtime")
DATABASE = RUNTIME / "agent.db"
CODEX_CANDIDATES = (
    Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    Path.home() / ".local/bin/codex",
)
_lock = threading.RLock()
_processes: dict[str, subprocess.Popen] = {}
_handles: dict[str, object] = {}


@contextmanager
def _connect():
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS generation_jobs (
        id TEXT PRIMARY KEY, worker TEXT NOT NULL, workspace TEXT NOT NULL,
        instruction TEXT NOT NULL, status TEXT NOT NULL, pid INTEGER NOT NULL,
        output_path TEXT NOT NULL, log_path TEXT NOT NULL, result TEXT NOT NULL,
        started REAL NOT NULL, updated REAL NOT NULL, finished REAL
        )"""
    )
    connection.commit()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def codex_path() -> Path | None:
    configured = os.getenv("ORION_CODEX_PATH", "").strip()
    candidates = ([Path(configured).expanduser()] if configured else []) + list(CODEX_CANDIDATES)
    discovered = shutil.which("codex")
    if discovered:
        candidates.append(Path(discovered))
    return next((path for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)


def available_workers() -> dict:
    codex = codex_path()
    return {
        "ok": True,
        "workers": [
            {"name": "Codex", "available": bool(codex), "mode": "workspace-write", "path": str(codex or "")},
            {"name": "CAD", "available": False, "mode": "adapter_required", "path": ""},
        ],
    }


def start_codex_job(repository: str, instruction: str, confirmed: bool) -> dict:
    if not confirmed:
        return {
            "ok": False, "error_code": "confirmation_required", "requires_user": True,
            "error": "Starting a code-generation job can modify project files and requires an explicit request.",
        }
    instruction = instruction.strip()
    if not instruction:
        return {"ok": False, "error_code": "missing_instruction", "requires_user": True, "error": "The generation job needs an objective."}
    worker = codex_path()
    if not worker:
        return {"ok": False, "error_code": "codex_unavailable", "requires_user": True, "error": "Codex is not installed on this Mac."}
    try:
        state = git_tools.status(repository)
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "error_code": "repository_not_found", "requires_user": True, "error": str(exc)}
    workspace = Path(state["path"])
    RUNTIME.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    output_path = RUNTIME / f"generation-{job_id}-result.txt"
    log_path = RUNTIME / f"generation-{job_id}.jsonl"
    command = [
        str(worker), "exec", "--json", "--color", "never", "--sandbox", "workspace-write",
        "--ask-for-approval", "never", "--cd", str(workspace),
        "--output-last-message", str(output_path), instruction,
    ]
    handle = log_path.open("ab")
    try:
        process = subprocess.Popen(
            command, stdout=handle, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except Exception:
        handle.close()
        raise
    now = time.time()
    with _lock:
        _processes[job_id] = process
        _handles[job_id] = handle
        with _connect() as database:
            database.execute(
                "INSERT INTO generation_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, "codex", str(workspace), instruction[:8000], "running", process.pid,
                 str(output_path), str(log_path), "", now, now, None),
            )
    diagnostics.event("generation_started", job_id=job_id, worker="codex", workspace=str(workspace), pid=process.pid)
    return {
        "ok": True, "job_id": job_id, "status": "running", "worker": "Codex",
        "repository": state["repository"], "pid": process.pid,
        "message": "Codex is generating in the repository. ORION will monitor it and notify you when it finishes.",
    }


def poll_jobs() -> list[dict]:
    updates = []
    with _lock, _connect() as database:
        rows = database.execute("SELECT * FROM generation_jobs WHERE status='running'").fetchall()
        for row in rows:
            job_id = row["id"]
            process = _processes.get(job_id)
            return_code = process.poll() if process else None
            if process is None:
                try:
                    os.kill(int(row["pid"]), 0)
                    continue
                except OSError:
                    return_code = 0 if Path(row["output_path"]).exists() else 1
            if return_code is None:
                continue
            handle = _handles.pop(job_id, None)
            if handle:
                handle.close()
            _processes.pop(job_id, None)
            result = ""
            try:
                result = Path(row["output_path"]).read_text(encoding="utf-8", errors="replace")[:12000]
            except OSError:
                pass
            status = "completed" if return_code == 0 else "failed"
            now = time.time()
            database.execute(
                "UPDATE generation_jobs SET status=?,result=?,updated=?,finished=? WHERE id=?",
                (status, result, now, now, job_id),
            )
            update = {"job_id": job_id, "status": status, "workspace": row["workspace"], "result": result}
            updates.append(update)
            diagnostics.event("generation_finished", **update)
    for update in updates:
        try:
            import mac_tools
            message = "The Codex generation job finished." if update["status"] == "completed" else "The Codex generation job needs attention."
            mac_tools.notify("ORION", message)
        except Exception:
            pass
    return updates


def job_status(job_id: str = "") -> dict:
    poll_jobs()
    with _connect() as database:
        if job_id.strip():
            row = database.execute("SELECT * FROM generation_jobs WHERE id=?", (job_id.strip(),)).fetchone()
        else:
            row = database.execute("SELECT * FROM generation_jobs ORDER BY started DESC LIMIT 1").fetchone()
    if not row:
        return {"ok": True, "job": None, "message": "No generation job has been started."}
    item = dict(row)
    item["instruction"] = item["instruction"][:1000]
    item["result"] = item["result"][:2000]
    return {"ok": True, "job": item}


def cancel_job(job_id: str, confirmed: bool) -> dict:
    if not confirmed:
        return {"ok": False, "error_code": "confirmation_required", "requires_user": True, "error": "Cancelling a generation job requires confirmation."}
    with _connect() as database:
        row = database.execute("SELECT * FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["status"] != "running":
            return {"ok": False, "error_code": "job_not_running", "error": "That generation job is not running."}
        try:
            os.killpg(int(row["pid"]), signal.SIGTERM)
        except OSError:
            pass
        database.execute("UPDATE generation_jobs SET status='cancelled',updated=?,finished=? WHERE id=?", (time.time(), time.time(), job_id))
    return {"ok": True, "job_id": job_id, "status": "cancelled"}
