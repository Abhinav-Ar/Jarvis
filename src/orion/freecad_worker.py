"""Engineering-led parametric FreeCAD generation through the Part kernel."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import design_intelligence
import project_workspace as workspace


BINARY = Path("/Applications/FreeCAD.app/Contents/MacOS/FreeCAD")
ALLOWED_TYPES = {"box", "cylinder", "sphere", "cone", "profile_extrusion", "revolved_profile"}
ALLOWED_OPERATIONS = {"body", "add", "cut", "intersect"}


def create_project(
    project_name: str, description: str, parts: list[dict], export_format: str,
    confirmed: bool, design_brief_id: str = "", _request_id: str = "",
) -> dict:
    blocked = workspace.require_confirmation(confirmed, "FreeCAD")
    if blocked:
        return blocked
    if not BINARY.is_file():
        return {"ok": False, "error_code": "freecad_unavailable", "error": "FreeCAD is not installed."}
    brief, brief_error = design_intelligence.load_brief(design_brief_id, project_name)
    if brief_error:
        return {"ok": False, "error_code": "design_brief_required", "error": brief_error}
    error = _validate(parts)
    if error:
        return {"ok": False, "error_code": "invalid_part_spec", "error": error}
    fmt = export_format.lower() if export_format.lower() in {"step", "stl"} else "step"
    _, folder, manifest = workspace.project("FreeCAD", project_name, _request_id)
    native = folder / f"{manifest['project']}.FCStd"
    exported = folder / f"{manifest['project']}.{fmt}"
    verification = folder / "engineering-verification.json"
    script = folder / "orion_build.py"
    manifest.update({"description": description[:3000], "spec": parts, "export_format": fmt})
    design_intelligence.attach(manifest, brief or {})
    workspace.progress(manifest, folder, "Building engineering specification", 1, f"{len(parts)} construction features with explicit design intent")
    script.write_text(_script(parts, native, exported, verification, brief or {}), encoding="utf-8")
    workspace.progress(manifest, folder, "Solving feature tree", 2, "Profiles, revolves, booleans, placements, and edge treatments")
    try:
        result = subprocess.run(
            [str(BINARY), "-c", str(script)], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=900, check=False,
        )
        (folder / "worker.log").write_text(result.stdout[-80000:], encoding="utf-8")
        if result.returncode != 0 or "Traceback (most recent call last)" in result.stdout:
            return workspace.finish(manifest, folder, [native, exported, verification], f"FreeCAD modeling failed with status {result.returncode}.")
        workspace.progress(manifest, folder, "Verifying engineering output", 3, f"Checking valid solids, volume, dimensions, and {fmt.upper()} export")
        try:
            report = json.loads(verification.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = {"passed": False, "issues": ["Verification report is missing."]}
        error = "" if report.get("passed") else "; ".join(report.get("issues", [])) or "CAD solid verification failed."
        finished = workspace.finish(manifest, folder, [native, exported, verification], error)
        finished["engineering_verification"] = report
        if finished.get("ok"):
            opened = workspace.open_project("FreeCAD", manifest["project"])
            finished.update({"opened": bool(opened.get("ok")), "loaded": bool(opened.get("loaded")), "open_result": opened})
        return finished
    except (OSError, subprocess.SubprocessError) as exc:
        return workspace.finish(manifest, folder, [native, exported, verification], str(exc))


def _validate(parts: list[dict]) -> str:
    if not parts or len(parts) > 100:
        return "Use 1–100 supported engineering features."
    names: set[str] = set()
    for item in parts:
        name = str(item.get("name", "")).strip()
        kind = str(item.get("type", "")).lower()
        operation = str(item.get("operation", "body")).lower()
        if not name or name in names:
            return "Every feature needs a unique name."
        if kind not in ALLOWED_TYPES or operation not in ALLOWED_OPERATIONS:
            return f"Unsupported feature or operation on {name}."
        if kind in {"profile_extrusion", "revolved_profile"} and not 3 <= len(item.get("profile", [])) <= 64:
            return f"{name} needs a closed engineering profile with 3–64 points."
        target = str(item.get("target", "")).strip()
        if operation != "body" and target not in names:
            return f"{name} must target an earlier body for its {operation} operation."
        if len(item.get("dimensions", [])) != 3 or any(float(value) <= 0 for value in item.get("dimensions", [])):
            return f"{name} needs three positive dimensions."
        names.add(name)
    if not any(item.get("operation") in {"cut", "add", "intersect"} for item in parts) and len(parts) < 3:
        return "A finished engineering design needs multiple features or a resolved boolean relationship."
    return ""


def _script(parts: list[dict], native: Path, exported: Path, verification: Path, brief: dict) -> str:
    payload = json.dumps(parts)
    return f'''import FreeCAD as App, Part, json, math
parts=json.loads({payload!r}); brief=json.loads({json.dumps(brief)!r}); doc=App.newDocument("ORION_Engineering_Project")
shapes={{}}; features={{}}; roots=[]
def vector3(value,default):
    value=list(value or [])
    return (value+[default[0],default[1],default[2]])[:3]
def build_shape(spec):
    kind=str(spec.get("type","box")).lower(); d=[float(v) for v in vector3(spec.get("dimensions"),(10,10,10))]
    if kind=="box": shape=Part.makeBox(d[0],d[1],d[2])
    elif kind=="cylinder": shape=Part.makeCylinder(d[0],d[1])
    elif kind=="sphere": shape=Part.makeSphere(d[0])
    elif kind=="cone": shape=Part.makeCone(d[0],d[1],d[2])
    else:
        profile=[(float(p[0]),float(p[1])) for p in spec.get("profile",[])]
        points=[App.Vector(x,y,0) for x,y in profile]
        wire=Part.makePolygon(points+[points[0]])
        face=Part.Face(wire)
        shape=face.extrude(App.Vector(0,0,d[2])) if kind=="profile_extrusion" else face.revolve(App.Vector(0,0,0),App.Vector(0,1,0),360)
    rotation=vector3(spec.get("rotation"),(0,0,0))
    for axis,angle in zip((App.Vector(1,0,0),App.Vector(0,1,0),App.Vector(0,0,1)),rotation):
        if float(angle): shape.rotate(App.Vector(0,0,0),axis,float(angle))
    position=vector3(spec.get("position"),(0,0,0)); shape.translate(App.Vector(*map(float,position)))
    fillet=max(0.0,float(spec.get("fillet",0)))
    if fillet and shape.Edges:
        try: shape=shape.makeFillet(fillet,shape.Edges)
        except Exception: pass
    return shape
for index,spec in enumerate(parts):
    name=str(spec.get("name") or f"Feature_{{index+1}}"); source=build_shape(spec); operation=str(spec.get("operation","body")); target=str(spec.get("target", ""))
    source_obj=doc.addObject("PartDesign::Feature",name+"_Source" if operation!="body" else name); source_obj.Shape=source
    source_obj.addProperty("App::PropertyString","ORIONOperation"); source_obj.ORIONOperation=operation
    source_obj.addProperty("App::PropertyString","ORIONDesignIntent"); source_obj.ORIONDesignIntent=str(spec.get("design_intent",brief.get("intent","")))
    if operation=="body": result=source; result_obj=source_obj; roots.append(name)
    else:
        base=shapes[target]
        result=base.fuse(source) if operation=="add" else (base.cut(source) if operation=="cut" else base.common(source))
        source_obj.Visibility=False; result_obj=doc.addObject("PartDesign::Feature",name); result_obj.Shape=result
        result_obj.addProperty("App::PropertyString","ORIONOperation"); result_obj.ORIONOperation=operation
        result_obj.addProperty("App::PropertyString","ORIONTarget"); result_obj.ORIONTarget=target
        if target in features: features[target].Visibility=False
        if target in roots: roots.remove(target)
        roots.append(name)
    shapes[name]=result; features[name]=result_obj
doc.recompute(); export_objects=[features[name] for name in roots]; doc.saveAs({str(native)!r}); Part.export(export_objects,{str(exported)!r})
issues=[]; solids=sum(len(obj.Shape.Solids) for obj in export_objects); volume=sum(float(obj.Shape.Volume) for obj in export_objects)
valid=all(not obj.Shape.isNull() and obj.Shape.isValid() for obj in export_objects)
if not valid: issues.append("One or more generated shapes are invalid.")
if solids<1: issues.append("No closed solid was produced.")
if volume<=0: issues.append("The resulting design has no measurable volume.")
bounds=[]
for obj in export_objects:
    box=obj.Shape.BoundBox; bounds.append({{"name":obj.Name,"dimensions":[box.XLength,box.YLength,box.ZLength],"volume":obj.Shape.Volume,"solids":len(obj.Shape.Solids)}})
report={{"passed":not issues,"brief_id":brief.get("brief_id",""),"selected_concept":brief.get("selected_concept",""),"root_bodies":len(export_objects),"solid_count":solids,"volume":volume,"features":len(parts),"bounds":bounds,"issues":issues,"quality_gates":brief.get("quality_gates",[]),"limitations":["Load simulation and slicer-specific support analysis require a dedicated follow-up before fabrication."]}}
with open({str(verification)!r},"w",encoding="utf-8") as handle: json.dump(report,handle,indent=2)
App.closeDocument(doc.Name)
'''
