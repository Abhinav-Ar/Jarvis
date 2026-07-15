"""Safe procedural Blender modeling DSL for detailed hard-surface scenes."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import design_intelligence
import execution_supervisor
import project_workspace as workspace


BINARY = Path("/Applications/Blender.app/Contents/MacOS/Blender")
OPERATIONS = {"primitive", "mesh", "extrude_profile", "lathe_profile", "curve_tube", "terrain"}
PRIMITIVES = {"none", "cube", "cylinder", "sphere", "cone", "torus"}
WHEEL_HARDWARE_TOKENS = ("hub", "tread", "grouser", "fastener", "bolt", "mount", "axle", "knuckle", "pivot")


def _is_primary_wheel_name(name: str) -> bool:
    lowered = name.lower()
    return "wheel" in lowered and not any(token in lowered for token in WHEEL_HARDWARE_TOKENS)


def create_project(
    project_name: str, description: str, components: list[dict], booleans: list[dict],
    world_color: str, accent_color: str, render: bool, confirmed: bool,
    design_brief_id: str = "",
    _request_id: str = "",
) -> dict:
    blocked = workspace.require_confirmation(confirmed, "advanced Blender")
    if blocked:
        return blocked
    if not BINARY.is_file():
        return {"ok": False, "error_code": "blender_unavailable", "error": "Blender is not installed."}
    brief, brief_error = design_intelligence.load_brief(design_brief_id, project_name)
    if brief_error:
        return {"ok": False, "error_code": "design_brief_required", "error": brief_error}
    components, expanded = _expand_reusable_systems(components, brief or {})
    _, folder, manifest = workspace.project("Blender", project_name, _request_id)
    scene = folder / f"{manifest['project']}.blend"
    preview = folder / "preview.png"
    review = folder / "design-review.json"
    build_progress = folder / "build-progress.json"
    script = folder / "orion_advanced_build.py"
    manifest.update({
        "description": description[:3000], "modeling_mode": "advanced_procedural",
        "components": components, "booleans": booleans, "world_color": world_color,
        "accent_color": accent_color, "render": bool(render),
        "expanded_reusable_systems": expanded,
    })
    design_intelligence.attach(manifest, brief or {})
    workspace.progress(manifest, folder, "Validating the complete production specification", 1, "Checking every component, repeated assembly, material family, and design requirement together", total_steps=9)
    draft = folder / f"rejected-or-resumable-spec-{manifest['job_id']}.json"
    draft.write_text(json.dumps({
        "project_name": project_name, "description": description, "design_brief_id": design_brief_id,
        "components": components, "booleans": booleans, "world_color": world_color,
        "accent_color": accent_color, "render": render,
    }, indent=2), encoding="utf-8")
    structural = _validation_errors(components, booleans)
    quality = _design_errors(components, booleans, brief or {})
    errors = structural + quality
    if errors:
        message = "The specification needs these corrections before Blender can build it:\n- " + "\n- ".join(errors)
        finished = workspace.finish(manifest, folder, [draft], message)
        return {
            **finished, "ok": False,
            "error_code": "invalid_advanced_scene" if structural else "design_quality_gate_failed",
            "error": message, "validation_issues": errors, "resumable": True,
            "draft_path": str(draft), "design_brief_id": design_brief_id,
        }
    workspace.progress(manifest, folder, "Compiling the selected concept", 1, f"{len(components)} components and {len(booleans)} construction relationships", total_steps=9)
    script.write_text(_script(components, booleans, scene, preview, review, build_progress, brief or {}, world_color, accent_color, render), encoding="utf-8")
    workspace.progress(manifest, folder, "Starting Blender geometry engine", 2, "Preparing a visible, named production assembly", total_steps=9)
    progress_state = {"updated": 0.0, "step": 2, "announced": set()}
    def relay_progress() -> None:
        try:
            changed = build_progress.stat().st_mtime
            if changed <= progress_state["updated"]:
                return
            payload = json.loads(build_progress.read_text(encoding="utf-8"))
            step = max(2, min(8, int(payload.get("step", 2))))
            progress_state.update({"updated": changed, "step": step})
            workspace.progress(
                manifest, folder, str(payload.get("phase", "Building Blender project")), step,
                str(payload.get("detail", ""))[:240], total_steps=9,
            )
            milestone = {
                3: "The design is approved. I’m assembling the authored geometry now.",
                7: "The model is assembled. I’m rendering the presentation view now.",
                8: "The render is ready. I’m checking the physical assembly and finish quality before I accept it.",
            }.get(step)
            if milestone and step not in progress_state["announced"]:
                progress_state["announced"].add(step)
                workspace.activity.announce(milestone, key=f"blender:{manifest['job_id']}:{step}", minimum_interval=1.0)
        except (OSError, ValueError, TypeError):
            return
    result = execution_supervisor.run_cancellable_process(
        [str(BINARY), "--background", "--python", str(script)],
        request_id=_request_id, timeout=900, progress_callback=relay_progress,
    )
    try:
        (folder / "advanced-worker.log").write_text(str(result.get("stdout", ""))[-80000:], encoding="utf-8")
    except OSError:
        pass
    if result.get("cancelled"):
        finished = workspace.finish(manifest, folder, [scene], "Cancelled by the user before Blender finished.")
        return {**finished, "ok": False, "cancelled": True, "error_code": "task_cancelled", "error": "Advanced Blender generation was cancelled."}
    output = str(result.get("stdout", ""))
    if not result.get("ok") or "Traceback (most recent call last)" in output:
        error = str(result.get("error") or f"Advanced Blender modeling failed with status {result.get('returncode')}.")
        return workspace.finish(manifest, folder, [scene], error)
    relay_progress()
    workspace.progress(manifest, folder, "Verifying the exact saved project", 9, "Checking geometry, physical assembly, materials, render, and editable source", total_steps=9)
    expected = [scene, review] + ([preview] if render else [])
    missing = [path.name for path in expected if not path.exists() or path.stat().st_size == 0]
    review_payload: dict = {}
    try:
        review_payload = json.loads(review.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    review_issues = [str(item) for item in review_payload.get("issues", [])]
    quality_error = ""
    if review_payload and not review_payload.get("passed"):
        quality_error = "Quality review rejected the scene: " + "; ".join(review_issues[:6])
    finished = workspace.finish(
        manifest, folder, expected,
        f"Blender did not produce: {', '.join(missing)}." if missing else quality_error,
    )
    if finished.get("ok"):
        finished["design_review"] = review_payload or {"passed": False, "issues": ["Design review report could not be read."]}
        opened = workspace.open_project("Blender", manifest["project"])
        finished.update({"opened": bool(opened.get("ok")), "loaded": bool(opened.get("loaded")), "open_result": opened})
    return finished


def resume_project(project_name: str, confirmed: bool, _request_id: str = "") -> dict:
    blocked = workspace.require_confirmation(confirmed, "advanced Blender")
    if blocked:
        return blocked
    located = workspace.locate_resumable_draft("Blender", project_name)
    if not located.get("ok"):
        return located
    payload = dict(located.get("payload") or {})
    required = {"project_name", "description", "components", "booleans", "world_color", "accent_color", "render"}
    missing = sorted(required - payload.keys())
    if missing:
        return {
            "ok": False, "error_code": "resumable_draft_incomplete",
            "error": "The saved Blender draft is missing: " + ", ".join(missing),
        }
    return create_project(
        project_name=str(payload["project_name"]), description=str(payload["description"]),
        components=list(payload["components"]), booleans=list(payload["booleans"]),
        world_color=str(payload["world_color"]), accent_color=str(payload["accent_color"]),
        render=bool(payload["render"]), confirmed=True,
        design_brief_id=str(payload.get("design_brief_id", "")), _request_id=_request_id,
    )


def _validate(components: list[dict], booleans: list[dict]) -> str:
    errors = _validation_errors(components, booleans)
    return "\n- ".join(errors)


def _validation_errors(components: list[dict], booleans: list[dict]) -> list[str]:
    errors: list[str] = []
    if not components or len(components) > 120:
        errors.append("Use 1–120 procedural components.")
    names: set[str] = set()
    for item in components:
        name = str(item.get("name", "")).strip()
        operation = str(item.get("operation", ""))
        primitive = str(item.get("primitive", "none"))
        if not name or name in names:
            errors.append(f"Every component needs a unique non-empty name; check {name or 'the unnamed component'}.")
        if operation not in OPERATIONS or primitive not in PRIMITIVES:
            errors.append(f"Unsupported modeling operation on {name}.")
        if operation in {"extrude_profile", "lathe_profile"} and not 3 <= len(item.get("profile", [])) <= 64:
            errors.append(f"{name} needs a profile with 3–64 points.")
        if operation == "mesh" and not 3 <= len(item.get("vertices", [])) <= 256:
            errors.append(f"{name} needs 3–256 mesh vertices.")
        if operation == "mesh" and not item.get("faces"):
            errors.append(f"{name} needs explicit mesh faces.")
        if operation == "curve_tube" and not 2 <= len(item.get("path", [])) <= 64:
            errors.append(f"{name} needs a path with 2–64 local points.")
        names.add(name)
    for item in booleans[:50]:
        if item.get("target") not in names or item.get("cutter") not in names:
            errors.append(f"Boolean {item.get('target')} / {item.get('cutter')} must name existing components.")
        if item.get("operation") not in {"DIFFERENCE", "UNION", "INTERSECT"}:
            errors.append(f"Unsupported boolean operation on {item.get('target')}.")
    return list(dict.fromkeys(errors))


def _validate_design(components: list[dict], booleans: list[dict], brief: dict) -> str:
    errors = _design_errors(components, booleans, brief)
    return "\n- ".join(errors)


def _design_errors(components: list[dict], booleans: list[dict], brief: dict) -> list[str]:
    errors: list[str] = []
    if brief.get("artifact_type") in {"functional_part", "3d_print"}:
        errors.append("Dimensional functional and 3D-print parts must be built in FreeCAD or OpenSCAD, not Blender alone.")
    visible = [item for item in components if item.get("role") != "cutter"]
    if len(visible) < 12:
        errors.append("The selected concept needs at least 12 purposeful visible components; this specification is still a blockout.")
    operations = {str(item.get("operation")) for item in visible}
    if len(operations) < 3 or operations == {"primitive"}:
        errors.append("Use at least three modeling strategies so the design is not merely assembled primitives.")
    if not any(float(item.get("bevel", 0)) > 0 or int(item.get("subdivision", 0)) > 0 for item in visible):
        errors.append("Resolve edge treatment with bevels or subdivision instead of leaving every form mechanically raw.")
    if any(len(str(item.get("design_intent", "")).strip()) < 12 for item in visible):
        errors.append("Every visible component must state which requirement or design principle it satisfies.")
    if not booleans and not any(int(item.get("array_count", 1)) > 1 for item in visible):
        errors.append("Use at least one real construction relationship such as a boolean or deliberate repeated system.")
    requirements = " ".join(str(item) for item in brief.get("requirements", [])).lower()
    high_detail = len(brief.get("requirements", [])) >= 6
    if high_detail:
        hardware_terms = ("hub", "axle", "knuckle", "fastener", "bolt", "vent", "latch", "seam", "cable", "guard", "warning", "restraint", "indicator")
        major = [item for item in visible if not any(term in str(item.get("name", "")).lower() for term in hardware_terms)]
        primitive_ratio = sum(item.get("operation") == "primitive" for item in major) / max(1, len(major))
        if primitive_ratio > 0.45:
            errors.append(f"This production scene is still {primitive_ratio:.0%} primitives. Replace major forms with custom meshes, profiles, lathes, curves, or boolean-built assemblies.")
        collections = {str(item.get("collection", "")).strip().lower() for item in visible if str(item.get("collection", "")).strip()}
        if len(collections) < 5:
            errors.append("Organize the production scene into at least five named functional collections.")
        material_signatures = {
            (str(item.get("color", "")).lower(), round(float(item.get("metallic", 0)), 2), round(float(item.get("roughness", 0.45)), 2), round(float(item.get("emission", 0)), 2))
            for item in visible
        }
        if len(material_signatures) < 5:
            errors.append("Use at least five genuinely distinct material treatments for production-detail separation.")
    if "six-wheel" in requirements or "six wheel" in requirements or "rocker-bogie" in requirements:
        wheel_parts = [item for item in visible if _is_primary_wheel_name(str(item.get("name", "")))]
        if len(wheel_parts) != 6:
            errors.append("A six-wheel mobility brief requires exactly six separately positioned primary wheel assemblies.")
        if any(item.get("operation") == "primitive" for item in wheel_parts):
            errors.append("Primary rover wheels cannot be untouched cylinder primitives; use lathed or custom wheel meshes with separately positioned hubs and tread hardware.")
        names = [str(item.get("name", "")).lower() for item in visible]
        hubs = sum("hub" in name for name in names)
        axles = sum(any(token in name for token in ("axle", "knuckle", "wheel mount")) for name in names)
        tread_instances = sum(
            max(1, min(32, int(item.get("array_count", 1))))
            for item in visible if any(token in str(item.get("name", "")).lower() for token in ("tread", "grouser"))
        )
        rockers = sum("rocker" in name for name in names)
        bogies = sum("bogie" in name for name in names)
        balancing = sum(any(token in name for token in ("pivot", "linkage", "differential")) for name in names)
        if hubs < 6 or axles < 6 or tread_instances < 6 or rockers < 2 or bogies < 2 or balancing < 1:
            errors.append(
                f"Resolve the mobility interfaces: found {hubs}/6 hubs, {axles}/6 axle or knuckle mounts, {tread_instances}/6 tread or grouser systems, "
                f"{rockers}/2 rockers, {bogies}/2 bogies, and {balancing}/1 balancing pivot or differential."
            )
    detail_terms = ("latch", "vent", "fastener", "bolt", "seam", "panel", "cable", "guard", "warning", "restraint", "grouser")
    authored_details = sum(
        max(1, min(32, int(item.get("array_count", 1))))
        for item in visible if any(term in str(item.get("name", "")).lower() for term in detail_terms)
    )
    if high_detail and authored_details < 10:
        errors.append("The scene lacks tertiary production detail. Add at least ten positioned fasteners, seams, latches, guards, vents, restraints, cabling, markings, or equivalent authored details.")
    return list(dict.fromkeys(errors))


def _expand_reusable_systems(components: list[dict], brief: dict) -> tuple[list[dict], list[str]]:
    """Bind six-instance wheel hardware arrays to actual wheel transforms."""
    result = [deepcopy(item) for item in components]
    requirements = " ".join(str(item) for item in brief.get("requirements", [])).lower()
    if not any(token in requirements for token in ("six-wheel", "six wheel", "rocker-bogie")):
        return result, []
    primary = [
        item for item in result
        if _is_primary_wheel_name(str(item.get("name", "")))
    ]
    if len(primary) != 6:
        return result, []
    bind_tokens = ("hub", "axle", "knuckle", "wheel mount", "wheel_mount", "suspension pivot", "wheel tread", "wheel_tread")
    expanded: list[str] = []
    rebuilt: list[dict] = []
    for item in result:
        name = str(item.get("name", "")).lower()
        if int(item.get("array_count", 1)) == 6 and any(token in name for token in bind_tokens):
            base = str(item.get("name", "Component")).rstrip("s_")
            for wheel in primary:
                clone = deepcopy(item)
                suffix = str(wheel.get("name", "wheel")).replace("Wheel", "").strip(" _-") or str(len(rebuilt) + 1)
                clone["name"] = f"{base}_{suffix}"
                clone["location"] = list(wheel.get("location", [0, 0, 0]))
                clone["rotation"] = list(wheel.get("rotation", [0, 0, 0]))
                clone["array_count"] = 1
                clone["array_offset"] = [0, 0, 0]
                clone["design_intent"] = str(clone.get("design_intent", "")) + f" Positioned at {wheel.get('name', 'wheel')} as a reusable assembly instance."
                rebuilt.append(clone)
            expanded.append(str(item.get("name", "component")))
        else:
            rebuilt.append(item)
    return rebuilt, expanded


def _script(
    components: list[dict], booleans: list[dict], scene_path: Path,
    preview: Path, review_path: Path, progress_path: Path, brief: dict, world_color: str, accent_color: str, render: bool,
) -> str:
    return f'''import bpy, json, math, os, time
from mathutils import Vector
components=json.loads({json.dumps(components)!r}); boolean_specs=json.loads({json.dumps(booleans)!r}); design_brief=json.loads({json.dumps(brief)!r})
progress_path={str(progress_path)!r}
def report(step,phase,detail):
    temporary=progress_path+".tmp"
    with open(temporary,"w",encoding="utf-8") as handle: json.dump({{"step":step,"phase":phase,"detail":detail,"updated":time.time()}},handle)
    os.replace(temporary,progress_path)
def vec(value,default): return tuple(float(v) for v in (value if isinstance(value,list) and len(value)==3 else default))
def rotation_degrees(value):
    result=[]
    canonical=(math.pi/2,math.pi,3*math.pi/2,2*math.pi)
    for raw in vec(value,(0,0,0)):
        number=float(raw)
        if any(abs(abs(number)-item)<0.025 for item in canonical): number=math.degrees(number)
        result.append(number)
    return tuple(result)
def rgba(value):
    text=str(value or "#7DA7D9").lstrip("#")
    try: return tuple(int(text[i:i+2],16)/255 for i in (0,2,4))+(1,)
    except Exception: return (0.3,0.5,0.8,1)
def material(spec):
    mat=bpy.data.materials.new(spec["name"]+"_Material"); color=rgba(spec.get("color")); mat.diffuse_color=color; mat.use_nodes=True
    bsdf=mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value=color; bsdf.inputs["Metallic"].default_value=float(spec.get("metallic",0)); bsdf.inputs["Roughness"].default_value=float(spec.get("roughness",0.45))
        emission=bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission"); strength=bsdf.inputs.get("Emission Strength")
        if emission: emission.default_value=color
        if strength: strength.default_value=float(spec.get("emission",0))
    return mat
def mesh_object(name,verts,faces):
    mesh=bpy.data.meshes.new(name+"_Mesh"); mesh.from_pydata(verts,[],faces); mesh.update(); obj=bpy.data.objects.new(name,mesh); bpy.context.collection.objects.link(obj); return obj
def custom_mesh(spec):
    verts=[vec(item,(0,0,0)) for item in spec.get("vertices",[])]; faces=[tuple(int(index) for index in face) for face in spec.get("faces",[])]; return mesh_object(spec["name"],verts,faces)
def primitive(spec):
    kind=spec.get("primitive"); location=vec(spec.get("location"),(0,0,0)); segments=max(8,min(int(spec.get("segments",32)),128))
    if kind=="cube": bpy.ops.mesh.primitive_cube_add(location=location)
    elif kind=="cylinder": bpy.ops.mesh.primitive_cylinder_add(vertices=segments,location=location)
    elif kind=="sphere": bpy.ops.mesh.primitive_uv_sphere_add(segments=segments,ring_count=max(8,segments//2),location=location)
    elif kind=="cone": bpy.ops.mesh.primitive_cone_add(vertices=segments,location=location)
    elif kind=="torus": bpy.ops.mesh.primitive_torus_add(major_segments=segments,minor_segments=max(8,segments//3),location=location)
    return bpy.context.object
def extrude(spec):
    points=[(float(p[0]),float(p[1])) for p in spec["profile"]]; depth=max(0.001,float(spec.get("depth",1))); half=depth/2; count=len(points)
    verts=[(x,y,-half) for x,y in points]+[(x,y,half) for x,y in points]; faces=[tuple(reversed(range(count))),tuple(range(count,2*count))]
    faces += [(i,(i+1)%count,(i+1)%count+count,i+count) for i in range(count)]
    return mesh_object(spec["name"],verts,faces)
def lathe(spec):
    profile=[(max(0,float(p[0])),float(p[1])) for p in spec["profile"]]; segments=max(12,min(int(spec.get("segments",48)),128)); verts=[]; faces=[]
    for index in range(segments):
        angle=2*math.pi*index/segments
        for radius,z in profile: verts.append((radius*math.cos(angle),radius*math.sin(angle),z))
    width=len(profile)
    for ring in range(segments):
        nxt=(ring+1)%segments
        for row in range(width-1): faces.append((ring*width+row,nxt*width+row,nxt*width+row+1,ring*width+row+1))
    return mesh_object(spec["name"],verts,faces)
def curve_tube(spec):
    curve=bpy.data.curves.new(spec["name"]+"_Curve","CURVE"); curve.dimensions="3D"; curve.bevel_depth=max(0.002,float(spec.get("radius",0.04))); curve.bevel_resolution=max(2,min(int(spec.get("segments",8))//4,8)); spline=curve.splines.new("BEZIER"); path=spec["path"]; spline.bezier_points.add(len(path)-1)
    for point,co in zip(spline.bezier_points,path): point.co=vec(co,(0,0,0)); point.handle_left_type="AUTO"; point.handle_right_type="AUTO"
    obj=bpy.data.objects.new(spec["name"],curve); bpy.context.collection.objects.link(obj); return obj
def terrain(spec):
    dx,dy,dz=vec(spec.get("dimensions"),(20,20,1)); size=max(8,min(int(spec.get("segments",32)),64)); verts=[]; faces=[]
    for y in range(size):
        for x in range(size):
            px=(x/(size-1)-0.5)*dx; py=(y/(size-1)-0.5)*dy; noise=(math.sin(px*0.73)+math.sin(py*0.51)+math.sin((px+py)*0.31))*dz*0.12; verts.append((px,py,noise))
    for y in range(size-1):
        for x in range(size-1): i=y*size+x; faces.append((i,i+1,i+1+size,i+size))
    return mesh_object(spec["name"],verts,faces)
def build(spec):
    operation=spec["operation"]
    if operation=="primitive": obj=primitive(spec)
    elif operation=="mesh": obj=custom_mesh(spec)
    elif operation=="extrude_profile": obj=extrude(spec)
    elif operation=="lathe_profile": obj=lathe(spec)
    elif operation=="curve_tube": obj=curve_tube(spec)
    else: obj=terrain(spec)
    obj.name=spec["name"]; obj.location=vec(spec.get("location"),(0,0,0)); obj.rotation_euler=tuple(math.radians(v) for v in rotation_degrees(spec.get("rotation")))
    requested_dimensions=vec(spec.get("dimensions"),(0,0,0))
    if operation in {{"primitive","mesh","extrude_profile","lathe_profile"}} and all(value>0 for value in requested_dimensions):
        obj.dimensions=requested_dimensions
    if hasattr(obj.data,"materials"): obj.data.materials.append(material(spec))
    if obj.type=="MESH" and float(spec.get("bevel",0))>0:
        mod=obj.modifiers.new("ORION_Bevel","BEVEL"); mod.width=min(float(spec["bevel"]),0.5); mod.segments=3
    if obj.type=="MESH" and int(spec.get("subdivision",0))>0:
        mod=obj.modifiers.new("ORION_Subdivision","SUBSURF"); mod.levels=min(int(spec["subdivision"]),3); mod.render_levels=mod.levels
    if obj.type=="MESH" and abs(float(spec.get("solidify",0)))>0:
        mod=obj.modifiers.new("ORION_Solidify","SOLIDIFY"); mod.thickness=max(-1.0,min(float(spec["solidify"]),1.0))
    axis=str(spec.get("mirror_axis","none"))
    if obj.type=="MESH" and axis in {{"x","y","z"}}:
        mod=obj.modifiers.new("ORION_Mirror","MIRROR"); mod.use_axis[0]=axis=="x"; mod.use_axis[1]=axis=="y"; mod.use_axis[2]=axis=="z"
    if int(spec.get("array_count",1))>1:
        mod=obj.modifiers.new("ORION_Array","ARRAY"); mod.count=min(int(spec["array_count"]),64); mod.use_relative_offset=False; mod.constant_offset_displace=vec(spec.get("array_offset"),(1,0,0))
    if bool(spec.get("smooth")) and obj.type=="MESH":
        for polygon in obj.data.polygons: polygon.use_smooth=True
    obj["orion_role"]=spec.get("role","object"); obj["orion_operation"]=operation; obj["orion_design_intent"]=spec.get("design_intent",""); return obj
report(2,"Initializing scene","Clearing the default scene and establishing metric scale")
bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
bpy.context.scene.unit_settings.system="METRIC"; bpy.context.scene.unit_settings.length_unit="METERS"
objects={{}}
total=max(1,len(components))
for index,spec in enumerate(components,1):
    objects[spec["name"]]=build(spec)
    if index==1 or index==total or index % max(1,total//6)==0:
        report(3,"Modeling authored components",f"{{index}}/{{total}} • {{spec['name']}} • {{spec['operation']}}")
report(4,"Resolving construction relationships",f"Applying {{len(boolean_specs)}} booleans plus reusable modifier systems")
for spec in boolean_specs:
    target=objects[spec["target"]]; cutter=objects[spec["cutter"]]; mod=target.modifiers.new("ORION_Boolean_"+spec["cutter"],"BOOLEAN"); mod.operation=spec["operation"]; mod.solver="EXACT"; mod.object=cutter; cutter.hide_render=True; cutter.hide_viewport=True
report(5,"Organizing production assembly","Building named functional collections and object hierarchy")
for spec in components:
    obj=objects[spec["name"]]; collection_name=str(spec.get("collection") or "Assembly").strip() or "Assembly"
    collection=bpy.data.collections.get(collection_name) or bpy.data.collections.new(collection_name)
    if collection.name not in bpy.context.scene.collection.children: bpy.context.scene.collection.children.link(collection)
    if obj.name not in collection.objects: collection.objects.link(obj)
    for existing in list(obj.users_collection):
        if existing!=collection: existing.objects.unlink(obj)
# Frame all visible modeled geometry automatically.
visible=[o for o in objects.values() if o.get("orion_role")!="cutter" and o.get("orion_operation")!="terrain"]
points=[]
for obj in visible:
    if obj.type=="MESH": points.extend([obj.matrix_world @ Vector(corner) for corner in obj.bound_box])
center=sum(points,Vector())/len(points) if points else Vector(); extent=max((p-center).length for p in points) if points else 5
report(6,"Composing final presentation","Framing the complete assembly and separating key, fill, and environment light")
bpy.ops.object.camera_add(location=(center.x+extent*2.2,center.y-extent*2.8,center.z+extent*1.8)); camera=bpy.context.object; camera.name="ORION_Advanced_Camera"; camera.data.lens=55; camera.rotation_euler=(center-camera.location).to_track_quat("-Z","Y").to_euler(); bpy.context.scene.camera=camera
bpy.ops.object.light_add(type="SUN",location=(0,0,extent*2)); sun=bpy.context.object; sun.name="ORION_Moon_Key"; sun.rotation_euler=(math.radians(28),math.radians(-22),math.radians(35)); sun.data.energy=2.0; sun.data.color=(0.78,0.86,1.0)
bpy.ops.object.light_add(type="AREA",location=(center.x-extent,center.y-extent*0.5,center.z+extent)); fill=bpy.context.object; fill.name="ORION_Area_Fill"; fill.data.energy=max(500,extent*130); fill.data.shape="DISK"; fill.data.size=max(4,extent); fill.data.color=(0.55,0.68,1.0); fill.rotation_euler=(center-fill.location).to_track_quat("-Z","Y").to_euler()
scene=bpy.context.scene; engines={{item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}}; scene.render.engine="BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"; scene.render.resolution_x=1280; scene.render.resolution_y=720; scene.render.resolution_percentage=100; scene.render.image_settings.file_format="PNG"; scene.render.filepath={str(preview)!r}
scene.world.use_nodes=True; background=scene.world.node_tree.nodes.get("Background"); background.inputs["Color"].default_value=rgba({world_color!r}); background.inputs["Strength"].default_value=0.08; scene.view_settings.exposure=-0.25
try: scene.view_settings.look="AgX - Medium High Contrast"
except Exception: pass
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=="VIEW_3D": area.spaces.active.shading.type="MATERIAL"; area.spaces.active.region_3d.view_perspective="CAMERA"
if {bool(render)!r}:
    report(7,"Rendering polished preview","Rendering the camera view; this can be the longest stage")
    bpy.ops.render.render(write_still=True)
report(8,"Running geometry quality review","Checking wheel orientation, ground contact, assembly connections, material separation, collections, and authored complexity")
bpy.ops.wm.save_as_mainfile(filepath={str(scene_path)!r})
visible_objects=[o for o in objects.values() if not o.hide_render and o.get("orion_role")!="cutter"]
primary_wheels=[o for o in visible_objects if "wheel" in o.name.lower() and not any(token in o.name.lower() for token in ("hub","tread","grouser","fastener","bolt","mount","axle","knuckle","pivot"))]
issues=[]
hardware_terms=("hub","axle","knuckle","fastener","bolt","vent","latch","seam","cable","guard","warning","restraint","indicator")
major_objects=[o for o in visible_objects if not any(term in o.name.lower() for term in hardware_terms)]
primitive_ratio=sum(o.get("orion_operation")=="primitive" for o in major_objects)/max(1,len(major_objects))
if len(design_brief.get("requirements",[]))>=6 and primitive_ratio>0.45: issues.append(f"{{primitive_ratio:.0%}} of visible components remain primitive-based")
if len(primary_wheels)==6:
    bad_axes=[]; bad_contact=[]
    for wheel in primary_wheels:
        axis=(wheel.matrix_world.to_3x3() @ Vector((0,0,1))).normalized()
        if abs(axis.y)<0.72: bad_axes.append(wheel.name)
        lowest=min((wheel.matrix_world @ Vector(corner)).z for corner in wheel.bound_box)
        if abs(lowest)>0.09: bad_contact.append(f"{{wheel.name}} ({{lowest:+.2f}}m)")
    if bad_axes: issues.append("Wheel axle orientation is wrong: "+", ".join(bad_axes))
    if bad_contact: issues.append("Wheel contact is implausible: "+", ".join(bad_contact))
else: issues.append(f"Expected six primary wheels, found {{len(primary_wheels)}}")
functional_collections={{str(spec.get("collection","")).strip() for spec in components if str(spec.get("collection","")).strip()}}
if len(functional_collections)<5: issues.append(f"Only {{len(functional_collections)}} functional collections were authored")
material_signatures={{(tuple(round(v,3) for v in mat.diffuse_color),round(float(mat.node_tree.nodes.get('Principled BSDF').inputs['Metallic'].default_value),2) if mat.use_nodes else 0) for obj in visible_objects for mat in getattr(obj.data,'materials',[])}}
if len(material_signatures)<5: issues.append(f"Only {{len(material_signatures)}} distinct material treatments are visible")
review={{
    "passed": not issues,
    "issues": issues,
    "brief_id": design_brief.get("brief_id",""),
    "selected_concept": design_brief.get("selected_concept",""),
    "visible_components": len(visible_objects),
    "modeling_operations": sorted(set(o.get("orion_operation","") for o in visible_objects)),
    "modifier_count": sum(len(o.modifiers) for o in visible_objects),
    "mesh_vertices": sum(len(o.data.vertices) for o in visible_objects if o.type=="MESH"),
    "primitive_ratio": round(primitive_ratio,3),
    "functional_collections": sorted(functional_collections),
    "primary_wheels": [o.name for o in primary_wheels],
    "traceability": [{{"component":o.name,"design_intent":o.get("orion_design_intent","")}} for o in visible_objects],
    "quality_gates": design_brief.get("quality_gates",[]),
    "limitations": ["Visual composition still requires human review of the rendered preview before fabrication or publication."],
}}
with open({str(review_path)!r},"w",encoding="utf-8") as handle: json.dump(review,handle,indent=2)
'''
