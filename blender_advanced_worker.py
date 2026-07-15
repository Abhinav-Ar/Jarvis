"""Safe procedural Blender modeling DSL for detailed hard-surface scenes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import design_intelligence
import project_workspace as workspace


BINARY = Path("/Applications/Blender.app/Contents/MacOS/Blender")
OPERATIONS = {"primitive", "mesh", "extrude_profile", "lathe_profile", "curve_tube", "terrain"}
PRIMITIVES = {"none", "cube", "cylinder", "sphere", "cone", "torus"}


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
    error = _validate(components, booleans)
    if error:
        return {"ok": False, "error_code": "invalid_advanced_scene", "error": error}
    error = _validate_design(components, booleans, brief or {})
    if error:
        return {"ok": False, "error_code": "design_quality_gate_failed", "error": error}
    _, folder, manifest = workspace.project("Blender", project_name, _request_id)
    scene = folder / f"{manifest['project']}.blend"
    preview = folder / "preview.png"
    review = folder / "design-review.json"
    script = folder / "orion_advanced_build.py"
    manifest.update({
        "description": description[:3000], "modeling_mode": "advanced_procedural",
        "components": components, "booleans": booleans, "world_color": world_color,
        "accent_color": accent_color, "render": bool(render),
    })
    design_intelligence.attach(manifest, brief or {})
    workspace.progress(manifest, folder, "Compiling procedural model", 1, f"{len(components)} components and {len(booleans)} boolean relationships")
    script.write_text(_script(components, booleans, scene, preview, review, brief or {}, world_color, accent_color, render), encoding="utf-8")
    workspace.progress(manifest, folder, "Executing advanced Blender model", 2, "Profiles, curves, terrain, modifiers, materials, and assembly")
    try:
        result = subprocess.run(
            [str(BINARY), "--background", "--python", str(script)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=900, check=False,
        )
        (folder / "advanced-worker.log").write_text(result.stdout[-80000:], encoding="utf-8")
        if result.returncode != 0 or "Traceback (most recent call last)" in result.stdout:
            return workspace.finish(manifest, folder, [scene], f"Advanced Blender modeling failed with status {result.returncode}.")
    except (OSError, subprocess.SubprocessError) as exc:
        return workspace.finish(manifest, folder, [scene], str(exc))
    workspace.progress(manifest, folder, "Verifying topology and render", 3, "Checking editable source and preview artifacts")
    expected = [scene, review] + ([preview] if render else [])
    missing = [path.name for path in expected if not path.exists() or path.stat().st_size == 0]
    finished = workspace.finish(
        manifest, folder, expected,
        f"Blender did not produce: {', '.join(missing)}." if missing else "",
    )
    if finished.get("ok"):
        try:
            finished["design_review"] = json.loads(review.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            finished["design_review"] = {"passed": False, "issues": ["Design review report could not be read."]}
        opened = workspace.open_project("Blender", manifest["project"])
        finished.update({"opened": bool(opened.get("ok")), "loaded": bool(opened.get("loaded")), "open_result": opened})
    return finished


def _validate(components: list[dict], booleans: list[dict]) -> str:
    if not components or len(components) > 120:
        return "Use 1–120 procedural components."
    names: set[str] = set()
    for item in components:
        name = str(item.get("name", "")).strip()
        operation = str(item.get("operation", ""))
        primitive = str(item.get("primitive", "none"))
        if not name or name in names:
            return "Every component needs a unique non-empty name."
        if operation not in OPERATIONS or primitive not in PRIMITIVES:
            return f"Unsupported modeling operation on {name}."
        if operation in {"extrude_profile", "lathe_profile"} and not 3 <= len(item.get("profile", [])) <= 64:
            return f"{name} needs a profile with 3–64 points."
        if operation == "mesh" and not 3 <= len(item.get("vertices", [])) <= 256:
            return f"{name} needs 3–256 mesh vertices."
        if operation == "mesh" and not item.get("faces"):
            return f"{name} needs explicit mesh faces."
        if operation == "curve_tube" and not 2 <= len(item.get("path", [])) <= 64:
            return f"{name} needs a path with 2–64 points."
        names.add(name)
    for item in booleans[:50]:
        if item.get("target") not in names or item.get("cutter") not in names:
            return "Boolean targets and cutters must name existing components."
        if item.get("operation") not in {"DIFFERENCE", "UNION", "INTERSECT"}:
            return "Unsupported boolean operation."
    return ""


def _validate_design(components: list[dict], booleans: list[dict], brief: dict) -> str:
    if brief.get("artifact_type") in {"functional_part", "3d_print"}:
        return "Dimensional functional and 3D-print parts must be built in FreeCAD or OpenSCAD, not Blender alone."
    visible = [item for item in components if item.get("role") != "cutter"]
    if len(visible) < 12:
        return "The selected concept needs at least 12 purposeful visible components; this specification is still a blockout."
    operations = {str(item.get("operation")) for item in visible}
    if len(operations) < 3 or operations == {"primitive"}:
        return "Use at least three modeling strategies so the design is not merely assembled primitives."
    if not any(float(item.get("bevel", 0)) > 0 or int(item.get("subdivision", 0)) > 0 for item in visible):
        return "Resolve edge treatment with bevels or subdivision instead of leaving every form mechanically raw."
    if any(len(str(item.get("design_intent", "")).strip()) < 12 for item in visible):
        return "Every visible component must state which requirement or design principle it satisfies."
    if not booleans and not any(int(item.get("array_count", 1)) > 1 for item in visible):
        return "Use at least one real construction relationship such as a boolean or deliberate repeated system."
    return ""


def _script(
    components: list[dict], booleans: list[dict], scene_path: Path,
    preview: Path, review_path: Path, brief: dict, world_color: str, accent_color: str, render: bool,
) -> str:
    return f'''import bpy, json, math
from mathutils import Vector
components=json.loads({json.dumps(components)!r}); boolean_specs=json.loads({json.dumps(booleans)!r}); design_brief=json.loads({json.dumps(brief)!r})
def vec(value,default): return tuple(float(v) for v in (value if isinstance(value,list) and len(value)==3 else default))
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
    obj=bpy.context.object; obj.dimensions=vec(spec.get("dimensions"),(1,1,1)); return obj
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
    obj.name=spec["name"]; obj.location=vec(spec.get("location"),(0,0,0)); obj.rotation_euler=tuple(math.radians(v) for v in vec(spec.get("rotation"),(0,0,0)))
    if operation not in {{"primitive","terrain"}}: obj.scale=vec(spec.get("dimensions"),(1,1,1))
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
bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
objects={{spec["name"]:build(spec) for spec in components}}
for spec in boolean_specs:
    target=objects[spec["target"]]; cutter=objects[spec["cutter"]]; mod=target.modifiers.new("ORION_Boolean_"+spec["cutter"],"BOOLEAN"); mod.operation=spec["operation"]; mod.solver="EXACT"; mod.object=cutter; cutter.hide_render=True; cutter.hide_viewport=True
# Frame all visible modeled geometry automatically.
visible=[o for o in objects.values() if o.get("orion_role")!="cutter" and o.get("orion_operation")!="terrain"]
points=[]
for obj in visible:
    if obj.type=="MESH": points.extend([obj.matrix_world @ Vector(corner) for corner in obj.bound_box])
center=sum(points,Vector())/len(points) if points else Vector(); extent=max((p-center).length for p in points) if points else 5
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
if {bool(render)!r}: bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath={str(scene_path)!r})
visible_objects=[o for o in objects.values() if not o.hide_render and o.get("orion_role")!="cutter"]
review={{
    "passed": True,
    "brief_id": design_brief.get("brief_id",""),
    "selected_concept": design_brief.get("selected_concept",""),
    "visible_components": len(visible_objects),
    "modeling_operations": sorted(set(o.get("orion_operation","") for o in visible_objects)),
    "modifier_count": sum(len(o.modifiers) for o in visible_objects),
    "mesh_vertices": sum(len(o.data.vertices) for o in visible_objects if o.type=="MESH"),
    "traceability": [{{"component":o.name,"design_intent":o.get("orion_design_intent","")}} for o in visible_objects],
    "quality_gates": design_brief.get("quality_gates",[]),
    "limitations": ["Visual composition still requires human review of the rendered preview before fabrication or publication."],
}}
with open({str(review_path)!r},"w",encoding="utf-8") as handle: json.dump(review,handle,indent=2)
'''
