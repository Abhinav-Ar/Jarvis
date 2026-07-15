"""OpenSCAD source projects with deterministic native STL compilation."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import project_workspace as workspace


BINARY = Path("/Applications/OpenSCAD-2021.01.app/Contents/MacOS/OpenSCAD")


def create_project(project_name: str, description: str, source: str, confirmed: bool, _request_id: str = "") -> dict:
    blocked = workspace.require_confirmation(confirmed, "OpenSCAD")
    if blocked:
        return blocked
    if not BINARY.is_file():
        return {"ok": False, "error_code": "openscad_unavailable", "error": "OpenSCAD is not installed."}
    if not source.strip() or len(source) > 100000 or re.search(r"\b(?:include|use)\s*<", source, re.I):
        return {"ok": False, "error_code": "unsafe_scad_source", "error": "OpenSCAD source must be self-contained and under 100,000 characters."}
    job_id, folder, manifest = workspace.project("OpenSCAD", project_name, _request_id)
    scad = folder / f"{manifest['project']}.scad"; stl = folder / f"{manifest['project']}.stl"
    manifest.update({"description": description[:2000], "source_characters": len(source)})
    workspace.progress(manifest, folder, "Writing parametric source", 1, "Self-contained OpenSCAD model")
    scad.write_text(source, encoding="utf-8")
    workspace.progress(manifest, folder, "Compiling solid geometry", 2, "OpenSCAD CGAL pipeline")
    try:
        result = subprocess.run([str(BINARY), "-o", str(stl), str(scad)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600, check=False)
        (folder / "worker.log").write_text(result.stdout[-50000:], encoding="utf-8")
        if result.returncode != 0:
            return workspace.finish(manifest, folder, [scad, stl], f"OpenSCAD exited with status {result.returncode}.")
        workspace.progress(manifest, folder, "Verifying printable model", 3, "Checking source and STL output")
        return workspace.finish(manifest, folder, [scad, stl])
    except (OSError, subprocess.SubprocessError) as exc:
        return workspace.finish(manifest, folder, [scad, stl], str(exc))
