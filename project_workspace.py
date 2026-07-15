"""Shared durable workspace, safety, progress, and verification for native workers."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

import activity
import diagnostics
import mac_tools


ROOT = Path(os.getenv("ORION_PROJECTS_DIR", str(Path.home() / "Documents/ORION Projects")))


def require_confirmation(confirmed: bool, application: str) -> dict | None:
    if confirmed:
        return None
    return {
        "ok": False, "error_code": "confirmation_required", "requires_user": True,
        "error": f"Creating a {application} project writes new files and requires an explicit request.",
    }


def project(application: str, name: str, request_id: str = "") -> tuple[str, Path, dict]:
    safe = re.sub(r"[^A-Za-z0-9 _.-]+", "", name).strip(" .")[:80]
    if not safe:
        raise ValueError("A project name is required.")
    job_id = uuid.uuid4().hex[:12]
    folder = ROOT / safe / application
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {
        "job_id": job_id, "project": safe, "application": application,
        "request_id": request_id, "created_at": time.time(), "status": "running",
        "folder": str(folder), "artifacts": [],
    }
    write_manifest(folder, manifest)
    return job_id, folder, manifest


def write_manifest(folder: Path, manifest: dict) -> None:
    path = folder / "orion-project.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(path)


def progress(manifest: dict, folder: Path, phase: str, step: int, detail: str = "") -> None:
    manifest.update({"phase": phase, "step": step, "updated_at": time.time()})
    write_manifest(folder, manifest)
    activity.update_background_task(
        manifest["job_id"], f"{manifest['application'].upper()} // {manifest['project'].upper()}",
        phase, status="running", step=step, total_steps=4, detail=detail,
        route="native_worker",
    )
    diagnostics.event(
        "native_project_phase", request_id=manifest.get("request_id", ""),
        job_id=manifest["job_id"], application=manifest["application"], phase=phase, step=step,
    )


def finish(manifest: dict, folder: Path, artifacts: list[Path], error: str = "") -> dict:
    verified = [path for path in artifacts if path.exists() and path.stat().st_size > 0]
    ok = not error and len(verified) == len(artifacts) and bool(artifacts)
    manifest.update({
        "status": "completed" if ok else "failed", "verified": ok,
        "finished_at": time.time(), "artifacts": [str(path) for path in verified],
    })
    if error:
        manifest["error"] = error[:1000]
    write_manifest(folder, manifest)
    activity.update_background_task(
        manifest["job_id"], f"{manifest['application'].upper()} // {manifest['project'].upper()}",
        "Project verified" if ok else "Project needs attention",
        status="completed" if ok else "failed", step=4, total_steps=4,
        detail=f"{len(verified)} artifacts ready" if ok else (error or "Artifact verification failed")[:180],
        route="native_worker",
    )
    diagnostics.event(
        "native_project_finished", level="info" if ok else "error",
        request_id=manifest.get("request_id", ""), job_id=manifest["job_id"],
        application=manifest["application"], verified=ok, artifacts=len(verified), error=error[:500],
    )
    return {
        "ok": ok, "status": manifest["status"], "verified": ok,
        "application": manifest["application"], "project": manifest["project"],
        "job_id": manifest["job_id"], "folder": str(folder),
        "artifacts": [str(path) for path in verified],
        **({"error": error or "Project artifacts could not be verified."} if not ok else {}),
    }


PRIMARY_EXTENSIONS = {
    "Blender": (".blend",),
    "FreeCAD": (".fcstd",),
    "OpenSCAD": (".scad",),
}


def locate_project(application: str, project_name: str = "") -> dict:
    """Locate a verified native project and its primary editable artifact."""
    canonical = mac_tools.canonical_application_name(application)
    extensions = PRIMARY_EXTENSIONS.get(canonical)
    if not extensions:
        return {
            "ok": False, "error_code": "unsupported_native_project",
            "error": f"Opening a saved {canonical} project is not supported yet.",
        }
    candidates: list[tuple[float, dict, Path]] = []
    if ROOT.is_dir():
        for path in ROOT.glob("*/*/orion-project.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("application") != canonical or not manifest.get("verified"):
                continue
            if project_name and str(manifest.get("project", "")).casefold() != project_name.strip().casefold():
                continue
            candidates.append((float(manifest.get("finished_at", 0)), manifest, path.parent))
    if not candidates:
        label = f" named {project_name}" if project_name else ""
        return {
            "ok": False, "error_code": "native_project_not_found",
            "error": f"No verified {canonical} project{label} was found.",
        }
    _, manifest, folder = max(candidates, key=lambda item: item[0])
    artifact_paths = [Path(raw) for raw in manifest.get("artifacts", [])]
    primary = next(
        (path for path in artifact_paths if path.suffix.casefold() in extensions and path.is_file()),
        None,
    )
    if not primary:
        return {
            "ok": False, "error_code": "native_project_artifact_missing",
            "error": f"The verified {canonical} project no longer has its editable source file.",
        }
    return {
        "ok": True, "application": canonical, "project": manifest.get("project", ""),
        "folder": str(folder), "artifact": str(primary), "manifest": manifest,
        "manifest_path": str(folder / "orion-project.json"), "verified_project": True,
    }


def open_project(application: str, project_name: str = "") -> dict:
    """Find and visibly load a verified native project, newest first."""
    located = locate_project(application, project_name)
    if not located.get("ok"):
        return located
    canonical = str(located["application"])
    primary = Path(str(located["artifact"]))
    opened = mac_tools.open_file_in_application(primary, canonical)
    diagnostics.event(
        "native_project_opened" if opened.get("ok") else "native_project_open_failed",
        level="info" if opened.get("ok") else "error", application=canonical,
        project=located.get("project", ""), artifact=str(primary),
        loaded=bool(opened.get("loaded")), error=str(opened.get("error", ""))[:500],
    )
    return {
        **opened, "project": located.get("project", ""), "folder": located.get("folder", ""),
        "artifact": str(primary), "verified_project": True,
    }


def bounded_media_paths(paths: list[str]) -> tuple[list[str], str]:
    home = Path.home().resolve()
    accepted = []
    for raw in paths[:100]:
        path = Path(raw).expanduser().resolve()
        if not path.is_file() or not path.is_relative_to(home):
            return [], f"Media must be an existing file inside {home}."
        accepted.append(str(path))
    return accepted, ""
