"""Structured Blender project creation and refinement through Blender's Python API."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import project_workspace as workspace
import execution_supervisor


BINARY = Path("/Applications/Blender.app/Contents/MacOS/Blender")
ALLOWED_TYPES = {"cube", "sphere", "cylinder", "cone", "torus", "text"}


def create_project(
    project_name: str, description: str, objects: list[dict], render: bool,
    confirmed: bool, lighting_color: str = "#F4F7FF", lighting_strength: float = 1.0,
    accent_style: str = "none", accent_color: str = "#22D3EE",
    accent_strength: float = 1.0, _request_id: str = "",
) -> dict:
    blocked = workspace.require_confirmation(confirmed, "Blender")
    if blocked:
        return blocked
    if not BINARY.is_file():
        return {"ok": False, "error_code": "blender_unavailable", "error": "Blender is not installed."}
    if not objects or len(objects) > 50 or any(str(item.get("type", "")).lower() not in ALLOWED_TYPES for item in objects):
        return {"ok": False, "error_code": "invalid_scene_spec", "error": "Use 1–50 supported Blender objects."}
    if accent_style not in {"none", "desk_perimeter", "under_desk", "monitor_backlight"}:
        return {"ok": False, "error_code": "invalid_accent_style", "error": "Choose a supported accent-light placement."}
    job_id, folder, manifest = workspace.project("Blender", project_name, _request_id)
    scene = folder / f"{manifest['project']}.blend"
    preview = folder / "preview.png"
    script = folder / "orion_build.py"
    lighting_strength = max(0.1, min(float(lighting_strength), 1.6))
    accent_strength = max(0.1, min(float(accent_strength), 3.0))
    manifest.update({
        "description": description[:2000], "spec": objects, "render": bool(render),
        "lighting_color": lighting_color, "lighting_strength": lighting_strength,
        "accent_style": accent_style, "accent_color": accent_color,
        "accent_strength": accent_strength,
    })
    workspace.progress(manifest, folder, "Building detailed scene", 1, f"{len(objects)} authored components plus procedural detail")
    script.write_text(
        _create_script(
            objects, scene, preview, render, lighting_color, lighting_strength,
            accent_style, accent_color, accent_strength,
        ),
        encoding="utf-8",
    )
    workspace.progress(manifest, folder, "Generating native Blender scene", 2, "Geometry, bevels, materials, practical lights, camera, and render")
    result = _run_blender(["--background", "--python", str(script)], folder / "worker.log", _request_id)
    if result.get("cancelled"):
        finished = workspace.finish(manifest, folder, [scene], "Cancelled by the user before Blender finished.")
        return {**finished, "ok": False, "cancelled": True, "error_code": "task_cancelled", "error": "Blender generation was cancelled."}
    if result.get("error"):
        return workspace.finish(manifest, folder, [scene], result["error"])
    workspace.progress(manifest, folder, "Verifying editable project", 3, "Checking .blend and final preview")
    expected = [scene] + ([preview] if render else [])
    missing = [path.name for path in expected if not path.exists() or path.stat().st_size == 0]
    finished = workspace.finish(
        manifest, folder, expected,
        f"Blender did not produce: {', '.join(missing)}." if missing else "",
    )
    return _open_finished(finished, manifest["project"])


def refine_project(
    project_name: str, description: str, accent_style: str, accent_color: str,
    accent_strength: float, render: bool, confirmed: bool, _request_id: str = "",
) -> dict:
    """Safely refine a verified ORION Blender project without rebuilding its authored objects."""
    blocked = workspace.require_confirmation(confirmed, "Blender")
    if blocked:
        return blocked
    if accent_style not in {"none", "desk_perimeter", "under_desk", "monitor_backlight"}:
        return {"ok": False, "error_code": "invalid_accent_style", "error": "Choose a supported accent-light placement."}
    located = workspace.locate_project("Blender", project_name)
    if not located.get("ok"):
        return located
    folder = Path(str(located["folder"]))
    scene = Path(str(located["artifact"]))
    preview = folder / "preview.png"
    script = folder / "orion_refine.py"
    backup = folder / f"{scene.stem}.before-refine-{int(time.time())}.blend"
    shutil.copy2(scene, backup)
    manifest = dict(located["manifest"])
    manifest.update({
        "job_id": uuid.uuid4().hex[:12], "request_id": _request_id,
        "status": "running", "verified": False, "updated_at": time.time(),
        "refinement": description[:2000], "accent_style": accent_style,
        "accent_color": accent_color,
        "accent_strength": max(0.1, min(float(accent_strength), 3.0)),
    })
    workspace.write_manifest(folder, manifest)
    workspace.progress(manifest, folder, "Inspecting existing Blender project", 1, "Preserving authored geometry and replacing generated lighting")
    script.write_text(
        _refine_script(scene, preview, render, accent_style, accent_color, manifest["accent_strength"]),
        encoding="utf-8",
    )
    workspace.progress(manifest, folder, "Applying project refinement", 2, description[:180])
    result = _run_blender(["--background", str(scene), "--python", str(script)], folder / "refine-worker.log", _request_id)
    if result.get("cancelled"):
        finished = workspace.finish(manifest, folder, [scene, backup], "Cancelled by the user before refinement finished.")
        return {**finished, "ok": False, "cancelled": True, "error_code": "task_cancelled", "error": "Blender refinement was cancelled.", "backup": str(backup)}
    if result.get("error"):
        return workspace.finish(manifest, folder, [scene], result["error"])
    workspace.progress(manifest, folder, "Verifying refined project", 3, "Checking editable source and refreshed preview")
    expected = [scene] + ([preview] if render else [])
    missing = [path.name for path in expected if not path.exists() or path.stat().st_size == 0]
    finished = workspace.finish(
        manifest, folder, expected,
        f"Blender did not produce: {', '.join(missing)}." if missing else "",
    )
    finished["refined"] = bool(finished.get("ok"))
    finished["backup"] = str(backup)
    return _open_finished(finished, str(located["project"]))


def _run_blender(arguments: list[str], log_path: Path, request_id: str = "") -> dict:
    result = execution_supervisor.run_cancellable_process(
        [str(BINARY), *arguments], request_id=request_id, timeout=600,
    )
    try:
        log_path.write_text(str(result.get("stdout", ""))[-50000:], encoding="utf-8")
    except OSError:
        pass
    if result.get("cancelled"):
        return {"error": "Blender was cancelled.", "cancelled": True}
    output = str(result.get("stdout", ""))
    if not result.get("ok") or "Traceback (most recent call last)" in output:
        return {"error": str(result.get("error") or f"Blender exited with status {result.get('returncode')}.")}
    return {"error": ""}


def _open_finished(finished: dict, project_name: str) -> dict:
    if finished.get("ok"):
        opened = workspace.open_project("Blender", project_name)
        finished.update({
            "opened": bool(opened.get("ok")), "loaded": bool(opened.get("loaded")),
            "open_result": opened,
        })
    return finished


def _create_script(
    objects: list[dict], scene_path: Path, preview: Path, render: bool,
    lighting_color: str, lighting_strength: float, accent_style: str,
    accent_color: str, accent_strength: float,
) -> str:
    payload = json.dumps(objects)
    return _shared_script_header(payload, accent_style, accent_color, accent_strength) + f'''
lighting_color = {lighting_color!r}; lighting_strength = {lighting_strength!r}
bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
created = []
for index, spec in enumerate(objects):
    name = str(spec.get("name") or f"Object_{{index+1}}")
    if accent_style != "none" and "accent" in name.lower() and "light" in name.lower():
        continue
    obj = add_primitive(str(spec.get("type", "cube")).lower(), vec(spec.get("location"), (0,0,0)), str(spec.get("text") or name))
    obj.name = name; obj.dimensions = vec(spec.get("dimensions"), (2,2,2)); obj.rotation_euler = tuple(math.radians(x) for x in vec(spec.get("rotation"), (0,0,0)))
    bpy.context.view_layer.objects.active = obj
    if hasattr(obj.data, "materials"): obj.data.materials.append(make_material(name + "_Material", spec.get("color"), spec.get("metallic", 0.1), spec.get("roughness", 0.4)))
    add_bevel(obj); created.append(obj)
desk = expand_desk_and_keyboard(created)
add_accent(desk, accent_style, accent_color, accent_strength)
add_environment(desk, lighting_color, lighting_strength)
configure_scene(desk, {str(preview)!r})
if {bool(render)!r}: bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath={str(scene_path)!r})
'''


def _refine_script(
    scene_path: Path, preview: Path, render: bool, accent_style: str,
    accent_color: str, accent_strength: float,
) -> str:
    return _shared_script_header("[]", accent_style, accent_color, accent_strength) + f'''
for obj in list(bpy.data.objects):
    lowered = obj.name.lower()
    if lowered.startswith("orion_accent") or lowered == "accentlight":
        bpy.data.objects.remove(obj, do_unlink=True)
created = list(bpy.context.scene.objects)
normalize_existing_materials(created)
desk = expand_desk_and_keyboard(created)
add_accent(desk, accent_style, accent_color, accent_strength)
for obj in bpy.data.objects:
    if obj.type == "LIGHT" and obj.name.startswith("ORION_") and not obj.name.startswith("ORION_Accent"):
        obj.data.color = (0.92, 0.96, 1.0)
        obj.data.energy = min(float(obj.data.energy), 950.0 if "Key" in obj.name else 450.0)
add_environment(desk, "#F4F7FF", 0.85, replace=False)
configure_scene(desk, {str(preview)!r})
if {bool(render)!r}: bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath={str(scene_path)!r})
'''


def _shared_script_header(payload: str, accent_style: str, accent_color: str, accent_strength: float) -> str:
    return f'''import bpy, json, math
from mathutils import Vector
objects = json.loads({payload!r})
accent_style = {accent_style!r}; accent_color = {accent_color!r}; accent_strength = {accent_strength!r}
def vec(value, default):
    return tuple(float(x) for x in (value if isinstance(value, list) and len(value) == 3 else default))
def rgba(value):
    text = str(value or "#6FC3FF").lstrip("#")
    try: return tuple(int(text[i:i+2], 16)/255 for i in (0,2,4)) + (1,)
    except Exception: return (0.2,0.6,1.0,1.0)
def make_material(name, value, metallic=0.1, roughness=0.4, emission=0.0):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    color = rgba(value); material.diffuse_color = color; material.metallic = float(metallic); material.roughness = float(roughness); material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        if bsdf.inputs.get("Base Color"): bsdf.inputs["Base Color"].default_value = color
        if bsdf.inputs.get("Metallic"): bsdf.inputs["Metallic"].default_value = float(metallic)
        if bsdf.inputs.get("Roughness"): bsdf.inputs["Roughness"].default_value = float(roughness)
        emission_input = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
        strength_input = bsdf.inputs.get("Emission Strength")
        if emission_input: emission_input.default_value = color
        if strength_input: strength_input.default_value = float(emission)
    return material
def add_primitive(kind, location, text="ORION"):
    if kind == "cube": bpy.ops.mesh.primitive_cube_add(location=location)
    elif kind == "sphere": bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, location=location)
    elif kind == "cylinder": bpy.ops.mesh.primitive_cylinder_add(vertices=64, location=location)
    elif kind == "cone": bpy.ops.mesh.primitive_cone_add(vertices=64, location=location)
    elif kind == "torus": bpy.ops.mesh.primitive_torus_add(major_segments=64, minor_segments=24, location=location)
    elif kind == "text": bpy.ops.object.text_add(location=location); bpy.context.object.data.body = text
    return bpy.context.object
def add_bevel(obj):
    if obj.type != "MESH": return
    minimum = min(max(float(v), 0.001) for v in obj.dimensions)
    modifier = obj.modifiers.get("ORION_Bevel") or obj.modifiers.new("ORION_Bevel", "BEVEL")
    modifier.width = min(0.04, minimum * 0.18); modifier.segments = 3
def normalize_existing_materials(created):
    for obj in created:
        if obj.type != "MESH": continue
        add_bevel(obj)
        for material in getattr(obj.data,"materials",[]):
            if not material: continue
            base=material.diffuse_color; metallic=material.metallic; roughness=material.roughness
            if "desk" in obj.name.lower() and "leg" not in obj.name.lower(): metallic=max(float(metallic),0.68); roughness=min(float(roughness),0.32)
            material.use_nodes=True; bsdf=material.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                if bsdf.inputs.get("Base Color"): bsdf.inputs["Base Color"].default_value=base
                if bsdf.inputs.get("Metallic"): bsdf.inputs["Metallic"].default_value=metallic
                if bsdf.inputs.get("Roughness"): bsdf.inputs["Roughness"].default_value=roughness
def make_box(name, dimensions, location, material, bevel=True):
    bpy.ops.mesh.primitive_cube_add(location=location); obj=bpy.context.object; obj.name=name; obj.dimensions=dimensions
    obj.data.materials.append(material)
    if bevel: add_bevel(obj)
    return obj
def expand_desk_and_keyboard(created):
    desks = [o for o in created if o.type == "MESH" and "desk" in o.name.lower() and "leg" not in o.name.lower()]
    desk = max(desks, key=lambda o: float(o.dimensions.x*o.dimensions.y), default=None)
    if desk and not any("leg" in o.name.lower() for o in created):
        dx,dy,dz = map(float, desk.dimensions); leg_h=max(1.25, dx*0.27); leg_w=max(0.09, min(dx,dy)*0.06)
        mat=make_material("ORION_DeskLeg_Material", "#252A31", 0.7, 0.28)
        for index,(sx,sy) in enumerate(((-1,-1),(-1,1),(1,-1),(1,1)),1):
            x=desk.location.x+sx*(dx/2-leg_w*1.6); y=desk.location.y+sy*(dy/2-leg_w*1.6); z=desk.location.z-dz/2-leg_h/2
            make_box(f"ORION_DeskLeg_{{index}}", (leg_w,leg_w,leg_h), (x,y,z), mat)
    keyboards = [o for o in created if o.type == "MESH" and "keyboard" in o.name.lower() and ("body" in o.name.lower() or "base" in o.name.lower())]
    keyboard=max(keyboards, key=lambda o: float(o.dimensions.x*o.dimensions.y), default=None)
    if keyboard and not any(o.type == "MESH" and o.name.startswith("ORION_Key_") for o in bpy.data.objects):
        for obj in list(bpy.data.objects):
            if obj.name.lower() in {{"keycaps", "keyboardkeys"}}: bpy.data.objects.remove(obj, do_unlink=True)
        dx,dy,dz=map(float,keyboard.dimensions); rows,cols=5,14; gap=min(dx/cols,dy/rows)*0.16
        kw=(dx*0.9-(cols-1)*gap)/cols; kh=(dy*0.78-(rows-1)*gap)/rows
        mat=make_material("ORION_Keycap_Material", "#171B22", 0.25, 0.36)
        for row in range(rows):
            for col in range(cols):
                x=keyboard.location.x-dx*0.45+kw/2+col*(kw+gap); y=keyboard.location.y-dy*0.39+kh/2+row*(kh+gap); z=keyboard.location.z+dz/2+0.022
                make_box(f"ORION_Key_{{row+1}}_{{col+1}}", (kw,kh,0.035), (x,y,z), mat)
    return desk
def add_accent(desk, style, value, strength):
    if style == "none" or not desk: return
    color=rgba(value)[:3]; material=make_material("ORION_Accent_Material", value, 0.0, 0.22, 7.0*strength)
    dx,dy,dz=map(float,desk.dimensions); x,y,z=map(float,desk.location); strip=0.025
    if style in {{"desk_perimeter", "under_desk"}}:
        level=z-dz/2-0.035 if style=="under_desk" else z
        make_box("ORION_Accent_Front",(dx+0.04,strip,0.035),(x,y-dy/2-strip/2,level),material,False)
        make_box("ORION_Accent_Back",(dx+0.04,strip,0.035),(x,y+dy/2+strip/2,level),material,False)
        make_box("ORION_Accent_Left",(strip,dy,0.035),(x-dx/2-strip/2,y,level),material,False)
        make_box("ORION_Accent_Right",(strip,dy,0.035),(x+dx/2+strip/2,y,level),material,False)
        for index,(px,py) in enumerate(((x-dx/2,y-dy/2),(x+dx/2,y-dy/2),(x-dx/2,y+dy/2),(x+dx/2,y+dy/2)),1):
            bpy.ops.object.light_add(type="POINT",location=(px,py,level-0.08)); light=bpy.context.object; light.name=f"ORION_AccentGlow_{{index}}"; light.data.color=color; light.data.energy=18*strength; light.data.shadow_soft_size=0.35
    elif style == "monitor_backlight":
        monitors=[o for o in bpy.data.objects if o.type=="MESH" and "monitor" in o.name.lower() and "screen" in o.name.lower()]
        monitor=max(monitors,key=lambda o: float(o.dimensions.x*o.dimensions.z),default=None)
        if monitor: make_box("ORION_Accent_Monitor",(monitor.dimensions.x*0.9,0.025,monitor.dimensions.z*0.82),(monitor.location.x,monitor.location.y+monitor.dimensions.y/2+0.02,monitor.location.z),material,False)
def point(obj,target): obj.rotation_euler=(Vector(target)-obj.location).to_track_quat("-Z","Y").to_euler()
def add_environment(desk, light_value, strength, replace=True):
    if replace:
        for obj in list(bpy.data.objects):
            if obj.type in {{"LIGHT","CAMERA"}} and not obj.name.startswith("ORION_Accent"): bpy.data.objects.remove(obj,do_unlink=True)
    center=Vector(desk.location) if desk else Vector((0,0,0)); dx=float(desk.dimensions.x) if desk else 4.0; target=(center.x,center.y,center.z+0.35)
    # Practical accents stay colored; general illumination remains neutral when accents are requested.
    light_rgb=rgba("#F4F7FF" if accent_style != "none" else light_value)[:3]
    if not any(o.name=="ORION_Key_Light" for o in bpy.data.objects):
        bpy.ops.object.light_add(type="AREA",location=(dx*0.85,-dx*0.75,dx*1.15)); key=bpy.context.object; key.name="ORION_Key_Light"; key.data.energy=850*strength; key.data.color=light_rgb; key.data.shape="DISK"; key.data.size=max(3.0,dx*0.8); point(key,target)
        bpy.ops.object.light_add(type="AREA",location=(-dx*0.75,dx*0.3,dx*0.7)); fill=bpy.context.object; fill.name="ORION_Fill_Light"; fill.data.energy=360*strength; fill.data.color=(0.75,0.84,1.0); fill.data.size=max(2.0,dx*0.65); point(fill,target)
    cameras=[o for o in bpy.data.objects if o.type=="CAMERA"]
    camera=cameras[0] if cameras else None
    if not camera:
        bpy.ops.object.camera_add(location=(max(6.5,dx*1.45),-max(7.5,dx*1.65),max(4.8,dx*1.05))); camera=bpy.context.object
    camera.name="ORION_Camera"; camera.data.lens=52; point(camera,target); bpy.context.scene.camera=camera
def configure_scene(desk, preview_path):
    scene=bpy.context.scene; engines={{item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}}
    scene.render.engine="BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else ("BLENDER_EEVEE" if "BLENDER_EEVEE" in engines else "BLENDER_WORKBENCH")
    scene.render.resolution_x=1280; scene.render.resolution_y=720; scene.render.resolution_percentage=100; scene.render.image_settings.file_format="PNG"; scene.render.filepath=preview_path
    scene.world.use_nodes=True; background=scene.world.node_tree.nodes.get("Background")
    if background: background.inputs["Color"].default_value=(0.008,0.012,0.025,1); background.inputs["Strength"].default_value=0.12
    scene.view_settings.exposure=-0.35
    try: scene.view_settings.look="AgX - Medium High Contrast"
    except Exception: pass
    if desk and not bpy.data.objects.get("ORION_Floor"):
        dx=float(desk.dimensions.x); bottom=min((o.location.z-o.dimensions.z/2 for o in bpy.data.objects if "DeskLeg" in o.name),default=desk.location.z-desk.dimensions.z/2-1.3)
        floor=make_box("ORION_Floor",(dx*3.6,dx*3.6,0.08),(desk.location.x,desk.location.y,bottom-0.05),make_material("ORION_Floor_Material","#080B12",0.05,0.62),False)
    scene.use_nodes=True; tree=getattr(scene,"node_tree",None)
    if tree is None: tree=getattr(scene,"compositing_node_group",None)
    if tree:
        nodes=tree.nodes; links=tree.links; nodes.clear(); layers=nodes.new("CompositorNodeRLayers"); glare=nodes.new("CompositorNodeGlare"); glare.glare_type="FOG_GLOW"; glare.quality="HIGH"; glare.threshold=1.0; glare.size=6; composite=nodes.new("CompositorNodeComposite"); links.new(layers.outputs["Image"],glare.inputs["Image"]); links.new(glare.outputs["Image"],composite.inputs["Image"])
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=="VIEW_3D": area.spaces.active.shading.type="MATERIAL"; area.spaces.active.region_3d.view_perspective="CAMERA"
'''
