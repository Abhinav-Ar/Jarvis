"""Safe, observable macOS application installation jobs for ORION."""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import diagnostics
import activity


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


def _publish_task(record: dict, phase: str, step: int, status: str = "running", detail: str = "") -> None:
    activity.update_background_task(
        str(record.get("job_id", "installation")),
        f"INSTALLING {str(record.get('application', 'APPLICATION')).upper()}",
        phase,
        status=status,
        step=step,
        total_steps=4,
        detail=detail,
        route=str(record.get("route", "")),
    )


def _installed(cask: str, app_bundle: str, brew: str = "") -> bool:
    if app_bundle and any((root / app_bundle).exists() for root in (Path("/Applications"), Path.home() / "Applications")):
        return True
    if brew:
        return subprocess.run(
            [brew, "list", "--cask", cask], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        ).returncode == 0
    return False


def _official_cask(brew: str, cask: str) -> tuple[bool, str, str, str]:
    try:
        result = subprocess.run(
            [brew, "info", "--cask", "--json=v2", cask], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45, check=False,
        )
        if result.returncode != 0:
            return False, "", "", ""
        data = json.loads(result.stdout)
        records = data.get("casks", [])
        if not records:
            return False, "", "", ""
        bundle = ""
        for artifact in records[0].get("artifacts", []):
            if isinstance(artifact, dict) and artifact.get("app"):
                value = artifact["app"]
                bundle = str(value[0] if isinstance(value, list) else value)
                break
        return True, bundle, str(records[0].get("url", "")), str(records[0].get("homepage", ""))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return False, "", "", ""


def install(application: str, confirmed: bool, _request_id: str = "", _task_id: str = "") -> dict:
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
    if JOBS.exists():
        for path in sorted(JOBS.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                active = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if active.get("cask") == cask and active.get("status") in {
                "starting", "running", "installing", "browser_downloading", "installing_download",
            }:
                return {
                    "ok": True, "status": active["status"], "job_id": active.get("job_id"),
                    "application": active.get("application", display_name), "cask": cask,
                    "verified": False, "existing_job": True,
                    "message": f"Installation of {display_name} is already in progress.",
                }
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
    valid_cask, discovered_bundle, download_url, homepage = _official_cask(brew, cask)
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
        "request_id": _request_id, "task_id": _task_id,
        "download_url": download_url, "homepage": homepage, "route": "homebrew",
    }
    _write(job_id, payload)
    _publish_task(payload, "Preparing trusted source", 1, detail="Validating package and installation route")
    with log_path.open("ab") as output:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker", job_id],
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True,
        )
    payload.update({"status": "running", "pid": process.pid})
    _write(job_id, payload)
    diagnostics.event(
        "installation_job_started", request_id=_request_id, task_id=_task_id,
        job_id=job_id, application=display_name, cask=cask, pid=process.pid,
    )
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
        resolved = _resolve(str(record.get("application", "")))
        brew = _brew()
        if resolved and brew and _installed(resolved[0], str(record.get("bundle", resolved[1])), brew):
            record.update({"status": "completed", "verified": True})
            _write(str(record["job_id"]), record)
        return {"ok": True, **record}
    resolved = _resolve(application) if application else None
    if resolved:
        brew = _brew()
        verified = bool(brew) and _installed(resolved[0], resolved[1], brew)
        return {"ok": True, "application": application, "status": "installed" if verified else "not_installed", "verified": verified}
    return {"ok": False, "error_code": "installation_not_found", "error": "No matching installation job was found."}


def status_summary(application: str = "") -> str:
    result = status(application=application)
    if not result.get("ok"):
        return str(result.get("error", "I couldn't find an installation job."))
    name = str(result.get("application") or application or "The application")
    state = str(result.get("status", ""))
    if result.get("verified") and state in {"completed", "installed"}:
        return f"{name} is installed and verified."
    if state in {"starting", "running", "installing", "browser_downloading", "installing_download"}:
        route = " through Safari" if result.get("route") == "official_browser" else ""
        return f"{name} is still installing{route}."
    if state == "failed":
        return f"{name} is not installed. The installation failed: {result.get('error', 'unknown error')}"
    return f"{name} is not installed."


def poll_jobs() -> list[dict]:
    """Return newly terminal jobs once so ORION's world model can retain them."""
    updates: list[dict] = []
    if not JOBS.exists():
        return updates
    for path in JOBS.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("status") not in {"completed", "failed"} or record.get("supervisor_observed"):
            continue
        record["supervisor_observed"] = time.time()
        _write(str(record["job_id"]), record)
        updates.append({
            "job_id": record.get("job_id"), "application": record.get("application"),
            "status": record.get("status"), "verified": bool(record.get("verified")),
            "route": record.get("route"), "error": record.get("error", ""),
            "request_id": record.get("request_id", ""), "task_id": record.get("task_id", ""),
        })
    return updates


def _browser_install(record: dict) -> tuple[bool, str]:
    url = str(record.get("download_url", ""))
    homepage = str(record.get("homepage", ""))
    if not url.startswith("https://"):
        return False, "The trusted package metadata did not include an HTTPS download URL."
    parsed_name = Path(urlparse(url).path).name
    if not parsed_name.lower().endswith(".dmg"):
        return False, "The official browser fallback was not a macOS disk image."
    downloads = Path.home() / "Downloads"
    target = downloads / parsed_name
    fallback_started = time.time()
    record.update({"status": "browser_downloading", "route": "official_browser", "fallback_started_at": fallback_started})
    _write(str(record["job_id"]), record)
    _publish_task(record, "Downloading from official site", 2, detail=f"Safari recovery • {urlparse(url).netloc}")
    diagnostics.event(
        "installation_browser_fallback_started", request_id=str(record.get("request_id", "")),
        job_id=record["job_id"], application=record["application"], host=urlparse(url).netloc,
    )
    opened = subprocess.run(["/usr/bin/open", "-a", "Safari", url], check=False).returncode == 0
    if not opened:
        return False, "Safari could not open the official download."
    timeout = max(5, int(os.getenv("ORION_INSTALL_BROWSER_TIMEOUT", "600")))
    stable_size = -1
    stable_polls = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        if target.is_file() and target.stat().st_mtime >= fallback_started - 5:
            size = target.stat().st_size
            stable_polls = stable_polls + 1 if size == stable_size and size > 1_000_000 else 0
            stable_size = size
            if stable_polls >= 2 and not (downloads / f"{parsed_name}.download").exists():
                break
        time.sleep(2)
    else:
        if homepage.startswith("https://"):
            subprocess.run(["/usr/bin/open", "-a", "Safari", homepage], check=False)
        return False, "Safari opened the official site, but the Blender download did not finish in time."

    record["status"] = "installing_download"
    record["download_path"] = str(target)
    _write(str(record["job_id"]), record)
    _publish_task(record, "Installing downloaded application", 3, detail="Mounting and copying the verified application")
    attached = subprocess.run(
        ["/usr/bin/hdiutil", "attach", "-nobrowse", "-readonly", "-plist", str(target)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if attached.returncode != 0:
        return False, "The downloaded disk image could not be mounted."
    mount_points: list[Path] = []
    try:
        data = plistlib.loads(attached.stdout)
        for entity in data.get("system-entities", []):
            if entity.get("mount-point"):
                mount_points.append(Path(entity["mount-point"]))
        bundle_name = str(record.get("bundle", ""))
        source = next(
            (candidate for mount in mount_points for candidate in mount.rglob(bundle_name) if candidate.is_dir()),
            None,
        ) if bundle_name else None
        if not source:
            return False, "The expected application was not present in the downloaded disk image."
        destination = Path("/Applications") / source.name
        copied = subprocess.run(["/usr/bin/ditto", str(source), str(destination)], check=False)
        if copied.returncode != 0:
            return False, "macOS would not copy the application into Applications."
        return destination.exists(), "" if destination.exists() else "The application copy could not be verified."
    finally:
        for mount in reversed(mount_points):
            subprocess.run(["/usr/bin/hdiutil", "detach", str(mount)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def _finish_supervised_task(record: dict, verified: bool, error: str = "") -> None:
    task_id = str(record.get("task_id", ""))
    if not task_id:
        return
    try:
        from agent_platform import platform
        agent = platform()
        agent.record_task_event(
            task_id, 2, "installation_completion", "succeeded" if verified else "failed",
            "Application installed and verified." if verified else error,
            {"job_id": record.get("job_id"), "application": record.get("application"), "route": record.get("route"), "verified": verified},
        )
        agent.finish_task(task_id, "completed" if verified else "failed", "Application installed and verified." if verified else error, "" if verified else "installation_failed")
    except Exception as exc:
        diagnostics.event("installation_task_sync_failed", level="warning", job_id=record.get("job_id", ""), error=str(exc))


def _worker(job_id: str) -> int:
    path = _job_path(job_id)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        brew = _brew()
        cask = str(record["cask"])
        bundle = str(record.get("bundle", ""))
        display_name = str(record["application"])
        if not brew:
            raise RuntimeError("Homebrew became unavailable before installation started.")
        record["status"] = "installing"
        _write(job_id, record)
        _publish_task(record, "Downloading trusted package", 2, detail="Homebrew installation is running")
        completed = subprocess.run([brew, "install", "--cask", cask], check=False)
        verified = completed.returncode == 0 and _installed(cask, bundle, brew)
        error = ""
        if not verified:
            try:
                output = Path(record["log"]).read_text(encoding="utf-8", errors="replace")
            except OSError:
                output = ""
            if "403" in output or "401" in output or "Download failed" in output:
                verified, error = _browser_install(record)
            else:
                error = f"{display_name} did not pass installation verification."
        record.update({
            "status": "completed" if verified else "failed", "verified": verified,
            "return_code": completed.returncode, "finished_at": time.time(),
        })
        if not verified:
            record["error"] = error or f"{display_name} did not pass installation verification."
        _write(job_id, record)
        _publish_task(
            record,
            "Installation verified" if verified else "Installation needs attention",
            4,
            status="completed" if verified else "failed",
            detail="Ready in Applications" if verified else str(record.get("error", "Installation failed")),
        )
        _finish_supervised_task(record, verified, str(record.get("error", "")))
        diagnostics.event(
            "installation_job_finished", level="info" if verified else "error",
            request_id=str(record.get("request_id", "")), task_id=str(record.get("task_id", "")),
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
        if 'record' in locals():
            _publish_task(record, "Installation needs attention", 4, status="failed", detail=str(exc))
        diagnostics.event(
            "installation_job_failed", level="error",
            request_id=str(record.get("request_id", "")) if 'record' in locals() else "",
            task_id=str(record.get("task_id", "")) if 'record' in locals() else "",
            job_id=job_id, application=display_name if 'display_name' in locals() else "",
            cask=cask if 'cask' in locals() else "", error=str(exc),
        )
        return 1


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--worker":
    raise SystemExit(_worker(sys.argv[2]))
