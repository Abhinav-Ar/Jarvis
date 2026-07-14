"""Safe, observable macOS application installation jobs for ORION."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import diagnostics


RUNTIME = Path(os.getenv("ORION_RUNTIME_DIR") or os.getenv("JARVIS_RUNTIME_DIR") or Path.home() / "Library/Application Support/Jarvis/.runtime")
JOBS = RUNTIME / "installations"
APPLICATIONS = {
    "blender": ("blender", "Blender.app"),
    "freecad": ("freecad", "FreeCAD.app"),
    "open scad": ("openscad", "OpenSCAD.app"),
    "openscad": ("openscad", "OpenSCAD.app"),
}


def _brew() -> str:
    for candidate in (shutil.which("brew"), "/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return ""


def _resolve(application: str) -> tuple[str, str, str] | None:
    normalized = " ".join(application.lower().strip().split())
    known = APPLICATIONS.get(normalized)
    if known:
        return known[0], known[1], application.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9 .+_-]{0,60}", normalized):
        return None
    # Homebrew receives one inert argv value, never shell text. Its official cask
    # metadata is checked before a job starts.
    cask = re.sub(r"[^a-z0-9+]+", "-", normalized).strip("-")
    return (cask, "", application.strip()) if cask else None


def _job_path(job_id: str) -> Path:
    return JOBS / f"{job_id}.json"


def _write(job_id: str, payload: dict) -> None:
    JOBS.mkdir(parents=True, exist_ok=True)
    path = _job_path(job_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _installed(cask: str, app_bundle: str, brew: str = "") -> bool:
    if app_bundle and any((root / app_bundle).exists() for root in (Path("/Applications"), Path.home() / "Applications")):
        return True
    if brew:
        return subprocess.run(
            [brew, "list", "--cask", cask], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        ).returncode == 0
    return False


def _official_cask(brew: str, cask: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [brew, "info", "--cask", "--json=v2", cask], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45, check=False,
        )
        if result.returncode != 0:
            return False, ""
        data = json.loads(result.stdout)
        records = data.get("casks", [])
        if not records:
            return False, ""
        bundle = ""
        for artifact in records[0].get("artifacts", []):
            if isinstance(artifact, dict) and artifact.get("app"):
                value = artifact["app"]
                bundle = str(value[0] if isinstance(value, list) else value)
                break
        return True, bundle
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return False, ""


def install(application: str, confirmed: bool) -> dict:
    resolved = _resolve(application)
    if not resolved:
        return {
            "ok": False, "error_code": "application_not_allowlisted", "requires_user": False,
            "error": f"{application} is not in ORION's trusted installer catalog.",
            "recovery": "Use an official installer manually or add a reviewed Homebrew cask mapping.",
        }
    cask, bundle, display_name = resolved
    brew = _brew()
    if brew and _installed(cask, bundle, brew):
        return {"ok": True, "status": "installed", "application": display_name, "cask": cask, "verified": True}
    if not confirmed:
        return {
            "ok": False, "error_code": "confirmation_required", "requires_user": True,
            "confirmation_required": True,
            "error": f"Installing {display_name} changes this Mac and may download a large application.",
        }
    if not brew:
        return {
            "ok": False, "error_code": "homebrew_unavailable", "requires_user": True,
            "error": "Homebrew is not available, so ORION cannot perform the trusted installation.",
        }
    valid_cask, discovered_bundle = _official_cask(brew, cask)
    if not valid_cask:
        return {
            "ok": False, "error_code": "application_not_found", "requires_user": False,
            "error": f"I couldn't find a trusted Homebrew application matching {display_name}.",
            "recovery": "Use the exact application name or install it from the publisher's official site.",
        }
    bundle = discovered_bundle or bundle
    JOBS.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    log_path = JOBS / f"{job_id}.log"
    payload = {
        "job_id": job_id, "application": display_name, "cask": cask,
        "bundle": bundle, "status": "starting", "started_at": time.time(),
        "log": str(log_path), "verified": False,
    }
    _write(job_id, payload)
    with log_path.open("ab") as output:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker", job_id, brew, cask, bundle, display_name],
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True,
        )
    payload.update({"status": "running", "pid": process.pid})
    _write(job_id, payload)
    diagnostics.event("installation_job_started", job_id=job_id, application=display_name, cask=cask, pid=process.pid)
    return {
        "ok": True, "status": "running", "job_id": job_id,
        "application": display_name, "cask": cask, "verified": False,
        "message": f"Installation of {display_name} started.",
    }


def status(application: str = "", job_id: str = "") -> dict:
    if job_id and re.fullmatch(r"[a-f0-9]{12}", job_id):
        paths = [_job_path(job_id)]
    else:
        paths = sorted(JOBS.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True) if JOBS.exists() else []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if application and application.lower() not in str(record.get("application", "")).lower():
            continue
        return {"ok": True, **record}
    resolved = _resolve(application) if application else None
    if resolved:
        brew = _brew()
        verified = bool(brew) and _installed(resolved[0], resolved[1], brew)
        return {"ok": True, "application": application, "status": "installed" if verified else "not_installed", "verified": verified}
    return {"ok": False, "error_code": "installation_not_found", "error": "No matching installation job was found."}


def _worker(job_id: str, brew: str, cask: str, bundle: str, display_name: str) -> int:
    path = _job_path(job_id)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        record["status"] = "installing"
        _write(job_id, record)
        completed = subprocess.run([brew, "install", "--cask", cask], check=False)
        verified = completed.returncode == 0 and _installed(cask, bundle, brew)
        record.update({
            "status": "completed" if verified else "failed", "verified": verified,
            "return_code": completed.returncode, "finished_at": time.time(),
        })
        if not verified:
            record["error"] = f"{display_name} did not pass installation verification."
        _write(job_id, record)
        diagnostics.event(
            "installation_job_finished", level="info" if verified else "error",
            job_id=job_id, application=display_name, cask=cask,
            verified=verified, return_code=completed.returncode,
        )
        title = f"{display_name} installed" if verified else f"{display_name} installation failed"
        message = "ORION verified the application in Applications." if verified else "Open the ORION installation log for details."
        subprocess.run(["/usr/bin/osascript", "-e", f'display notification {json.dumps(message)} with title {json.dumps(title)}'], check=False)
        return 0 if verified else 1
    except Exception as exc:
        try:
            _write(job_id, {"job_id": job_id, "application": display_name, "cask": cask, "status": "failed", "verified": False, "error": str(exc), "finished_at": time.time()})
        except OSError:
            pass
        diagnostics.event("installation_job_failed", level="error", job_id=job_id, application=display_name, cask=cask, error=str(exc))
        return 1


if __name__ == "__main__" and len(sys.argv) == 7 and sys.argv[1] == "--worker":
    raise SystemExit(_worker(*sys.argv[2:]))
