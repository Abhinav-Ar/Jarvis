"""DaVinci Resolve project, media pool, and timeline creation via the official API."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import project_workspace as workspace


APP = Path("/Applications/DaVinci Resolve/DaVinci Resolve.app")
API = Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting")
LIB = APP / "Contents/Libraries/Fusion/fusionscript.so"


def create_project(project_name: str, timeline_name: str, media_paths: list[str], width: int, height: int, fps: int, confirmed: bool, _request_id: str = "") -> dict:
    blocked = workspace.require_confirmation(confirmed, "DaVinci Resolve")
    if blocked:
        return blocked
    if not APP.is_dir() or not (API / "Modules/DaVinciResolveScript.py").is_file():
        return {"ok": False, "error_code": "resolve_api_unavailable", "error": "DaVinci Resolve's scripting API is not installed."}
    media, error = workspace.bounded_media_paths(media_paths)
    if error:
        return {"ok": False, "error_code": "invalid_media_path", "error": error}
    width, height = max(640, min(int(width), 7680)), max(480, min(int(height), 4320))
    fps = int(fps) if int(fps) in {23, 24, 25, 29, 30, 50, 59, 60} else 24
    job_id, folder, manifest = workspace.project("DaVinci Resolve", project_name, _request_id)
    manifest.update({"timeline": timeline_name[:100], "media": media, "resolution": [width, height], "fps": fps})
    workspace.progress(manifest, folder, "Connecting to Resolve", 1, "Official local scripting API")
    subprocess.run(["/usr/bin/open", str(APP)], check=False)
    os.environ["RESOLVE_SCRIPT_API"] = str(API); os.environ["RESOLVE_SCRIPT_LIB"] = str(LIB)
    sys.path.insert(0, str(API / "Modules"))
    try:
        import DaVinciResolveScript as dvr_script
        resolve = None
        for _ in range(60):
            resolve = dvr_script.scriptapp("Resolve")
            if resolve:
                break
            time.sleep(0.5)
        if not resolve:
            return workspace.finish(manifest, folder, [folder / "orion-project.json"], "Resolve did not expose its local scripting API. Enable Local scripting in Resolve Preferences.")
        manager = resolve.GetProjectManager(); existing = manager.GetProjectListInCurrentFolder() or []
        if manifest["project"] in existing:
            return workspace.finish(manifest, folder, [folder / "orion-project.json"], "A Resolve project with this name already exists.")
        workspace.progress(manifest, folder, "Creating edit project", 2, f"{width}×{height} at {fps} fps")
        project = manager.CreateProject(manifest["project"], str(folder))
        if not project:
            return workspace.finish(manifest, folder, [folder / "orion-project.json"], "Resolve could not create the project.")
        project.SetSetting("timelineResolutionWidth", str(width)); project.SetSetting("timelineResolutionHeight", str(height)); project.SetSetting("timelineFrameRate", str(fps))
        pool = project.GetMediaPool(); clips = pool.ImportMedia(media) if media else []
        timeline = pool.CreateTimelineFromClips(timeline_name or "Main Timeline", clips) if clips else pool.CreateEmptyTimeline(timeline_name or "Main Timeline")
        if not timeline or not manager.SaveProject():
            return workspace.finish(manifest, folder, [folder / "orion-project.json"], "Resolve could not verify the saved timeline.")
        resolve.OpenPage("edit")
        workspace.progress(manifest, folder, "Verifying project and timeline", 3, f"Imported {len(clips)} media items")
        manifest["resolve_project_saved"] = True; workspace.write_manifest(folder, manifest)
        return workspace.finish(manifest, folder, [folder / "orion-project.json"])
    except Exception as exc:
        return workspace.finish(manifest, folder, [folder / "orion-project.json"], str(exc))
