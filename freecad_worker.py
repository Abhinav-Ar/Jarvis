"""Parametric FreeCAD part generation through the native Part workbench API."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import project_workspace as workspace


BINARY = Path("/Applications/FreeCAD.app/Contents/MacOS/FreeCAD")
ALLOWED_TYPES = {"box", "cylinder", "sphere", "cone"}


def create_project(project_name: str, description: str, parts: list[dict], export_format: str, confirmed: bool, _request_id: str = "") -> dict:
    blocked = workspace.require_confirmation(confirmed, "FreeCAD")
    if blocked:
        return blocked
    if not BINARY.is_file():
        return {"ok": False, "error_code": "freecad_unavailable", "error": "FreeCAD is not installed."}
    if not parts or len(parts) > 100 or any(str(item.get("type", "")).lower() not in ALLOWED_TYPES for item in parts):
        return {"ok": False, "error_code": "invalid_part_spec", "error": "Use 1–100 supported parametric parts."}
    fmt = export_format.lower() if export_format.lower() in {"step", "stl"} else "step"
    job_id, folder, manifest = workspace.project("FreeCAD", project_name, _request_id)
    native = folder / f"{manifest['project']}.FCStd"; exported = folder / f"{manifest['project']}.{fmt}"
    script = folder / "orion_build.py"; manifest.update({"description": description[:2000], "spec": parts, "export_format": fmt})
    workspace.progress(manifest, folder, "Building parametric specification", 1, f"{len(parts)} editable solids")
    script.write_text(_script(parts, native, exported), encoding="utf-8")
    workspace.progress(manifest, folder, "Generating FreeCAD document", 2, "Native geometry kernel is running")
    try:
        result = subprocess.run([str(BINARY), "-c", str(script)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600, check=False)
        (folder / "worker.log").write_text(result.stdout[-50000:], encoding="utf-8")
        if result.returncode != 0:
            return workspace.finish(manifest, folder, [native, exported], f"FreeCAD exited with status {result.returncode}.")
        workspace.progress(manifest, folder, "Verifying CAD exports", 3, f"Checking editable document and {fmt.upper()}")
        return workspace.finish(manifest, folder, [native, exported])
    except (OSError, subprocess.SubprocessError) as exc:
        return workspace.finish(manifest, folder, [native, exported], str(exc))


def _script(parts: list[dict], native: Path, exported: Path) -> str:
    payload = json.dumps(parts)
    return f'''import FreeCAD as App, Part, json
parts=json.loads({payload!r}); doc=App.newDocument("ORION_Project"); objects=[]
for i,spec in enumerate(parts):
    kind=str(spec.get("type","box")).lower(); p=spec.get("position",[0,0,0]); d=spec.get("dimensions",[10,10,10])
    p=(list(p)+[0,0,0])[:3]; d=(list(d)+[10,10,10])[:3]
    if kind=="box": shape=Part.makeBox(float(d[0]),float(d[1]),float(d[2]))
    elif kind=="cylinder": shape=Part.makeCylinder(float(d[0]),float(d[1]))
    elif kind=="sphere": shape=Part.makeSphere(float(d[0]))
    else: shape=Part.makeCone(float(d[0]),float(d[1]),float(d[2]))
    obj=doc.addObject("PartDesign::Feature",str(spec.get("name") or f"Part_{{i+1}}")); obj.addProperty("App::PropertyString","ORIONType"); obj.ORIONType=kind; obj.Shape=shape; obj.Placement.Base=App.Vector(*map(float,p)); objects.append(obj)
doc.recompute(); doc.saveAs({str(native)!r}); Part.export(objects,{str(exported)!r}); App.closeDocument(doc.Name)
'''
