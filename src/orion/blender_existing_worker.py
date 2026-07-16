"""Inspect and safely edit real objects inside an existing Blender document."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import activity
import diagnostics
import execution_supervisor
import mac_tools
import project_workspace as workspace


BINARY = Path("/Applications/Blender.app/Contents/MacOS/Blender")


def _locate(project_name: str = "", file_path: str = "") -> dict:
    if file_path.strip():
        source = Path(file_path).expanduser().resolve()
        home = Path.home().resolve()
        temporary_root = Path("/private/tmp")
        allowed = source.is_relative_to(home) or source.is_relative_to(temporary_root)
        if source.suffix.casefold() != ".blend" or not source.is_file() or not allowed:
            return {
                "ok": False, "error_code": "invalid_blender_file",
                "error": "The Blender file must be an existing .blend document inside your home folder.",
            }
        return {"ok": True, "project": source.stem, "artifact": str(source), "folder": str(source.parent)}
    located = workspace.locate_project("Blender", project_name)
    if located.get("ok"):
        return located
    return located


def _run_blender(source: Path, script_source: str, request_id: str, timeout: float = 300) -> tuple[dict, Path]:
    temporary = Path(tempfile.mkdtemp(prefix="orion-blender-document-"))
    script = temporary / "worker.py"
    script.write_text(script_source, encoding="utf-8")
    result = execution_supervisor.run_cancellable_process(
        [str(BINARY), "--background", str(source), "--python", str(script)],
        request_id=request_id, timeout=timeout,
    )
    return result, temporary


def _inventory_script(output: Path) -> str:
    return f'''import bpy, json, math
from mathutils import Vector
output_path={str(output)!r}
def rounded(values): return [round(float(value),5) for value in values]
def bounds(obj):
    if not hasattr(obj,"bound_box"): return {{"min":rounded(obj.matrix_world.translation),"max":rounded(obj.matrix_world.translation)}}
    points=[obj.matrix_world @ Vector(point) for point in obj.bound_box]
    return {{"min":[round(min(point[i] for point in points),5) for i in range(3)],"max":[round(max(point[i] for point in points),5) for i in range(3)]}}
objects=[]
for obj in bpy.data.objects:
    objects.append({{
        "name":obj.name,"type":obj.type,"parent":obj.parent.name if obj.parent else "",
        "collections":[item.name for item in obj.users_collection],
        "location":rounded(obj.matrix_world.translation),
        "rotation_degrees":rounded([math.degrees(value) for value in obj.rotation_euler]),
        "scale":rounded(obj.scale),"dimensions":rounded(obj.dimensions),"world_bounds":bounds(obj),
        "mesh_vertices":len(obj.data.vertices) if obj.type=="MESH" else 0,
        "modifiers":[{{"name":item.name,"type":item.type}} for item in obj.modifiers],
        "system_role":str(obj.get("orion_system_role","")),
        "design_intent":str(obj.get("orion_design_intent","")),
        "hidden":bool(obj.hide_viewport or obj.hide_render),
    }})
payload={{
    "filepath":bpy.data.filepath,"scene":bpy.context.scene.name,
    "active_object":bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else "",
    "selected_objects":[obj.name for obj in bpy.context.selected_objects],
    "objects":objects,
    "collections":[{{"name":item.name,"objects":[obj.name for obj in item.objects],"children":[child.name for child in item.children]}} for item in bpy.data.collections],
}}
with open(output_path,"w",encoding="utf-8") as handle: json.dump(payload,handle,indent=2)
'''


def inspect_document(project_name: str = "", file_path: str = "", _request_id: str = "") -> dict:
    if not BINARY.is_file():
        return {"ok": False, "error_code": "blender_unavailable", "error": "Blender is not installed."}
    located = _locate(project_name, file_path)
    if not located.get("ok"):
        return located
    source = Path(str(located["artifact"]))
    activity.update("working", "Reading Blender document…", f"Inspecting actual objects in {source.name}; no changes will be made")
    output = Path(tempfile.mkdtemp(prefix="orion-blender-inventory-")) / "inventory.json"
    result, temporary = _run_blender(source, _inventory_script(output), _request_id, timeout=180)
    if result.get("cancelled"):
        return {"ok": False, "cancelled": True, "error_code": "task_cancelled", "error": "Blender inspection was cancelled."}
    if not result.get("ok") or not output.is_file():
        return {
            "ok": False, "error_code": "blender_inventory_failed",
            "error": str(result.get("error") or result.get("stdout") or "Blender could not inspect the document.")[-1200:],
        }
    try:
        inventory = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error_code": "blender_inventory_unreadable", "error": str(exc)}
    objects = list(inventory.get("objects") or [])
    visible = [item for item in objects if not item.get("hidden")]
    parented = [item for item in visible if item.get("parent")]
    inventory["objects"] = objects[:180]
    return {
        "ok": True, "application": "Blender", "project": located.get("project") or source.stem,
        "file_path": str(source), "object_count": len(objects), "visible_object_count": len(visible),
        "parented_object_count": len(parented), "inventory": inventory,
        "_activity_detail": f"Read {len(objects)} actual Blender objects • {len(parented)} parented • {len(inventory.get('collections', []))} collections • document unchanged",
    }


def _save_open_document() -> dict:
    try:
        script = '''tell application "Blender" to activate
delay 0.25
tell application "System Events" to keystroke "s" using command down
delay 0.8
return "saved"'''
        completed = subprocess.run(
            ["/usr/bin/osascript", "-e", script], check=True, capture_output=True, text=True, timeout=5,
        )
        return {"ok": "saved" in completed.stdout.lower()}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}


def _edit_script(plan: dict, source: Path, report: Path, preview: Path) -> str:
    return f'''import bpy, json, math
from mathutils import Vector
plan=json.loads({json.dumps(plan)!r}); source_path={str(source)!r}; report_path={str(report)!r}; preview_path={str(preview)!r}
before_names={{obj.name for obj in bpy.data.objects}}; before_parents={{obj.name:(obj.parent.name if obj.parent else "") for obj in bpy.data.objects}}
def topology(value):
    if value.type=="MESH": return len(value.data.vertices)
    if value.type=="CURVE": return sum(len(spline.bezier_points)+len(spline.points) for spline in value.data.splines)
    return 0
before_topology={{value.name:topology(value) for value in bpy.data.objects}}
def scene_mesh_extent():
    points=[]
    for value in bpy.data.objects:
        if value.type in {{"MESH","CURVE","SURFACE"}} and not value.hide_viewport:
            try: points.extend(value.matrix_world @ Vector(corner) for corner in value.bound_box)
            except Exception: pass
    if not points: return [0.0,0.0,0.0]
    return [max(point[index] for point in points)-min(point[index] for point in points) for index in range(3)]
before_scene_extent=scene_mesh_extent()
changes=[]; failures=[]; hierarchy_changes=[]; alignment_changes=[]; physical_additions=[]; geometry_replacements=[]; topology_changes=[]; modifier_changes=[]
def obj(name):
    value=bpy.data.objects.get(name)
    if value is None: failures.append("Missing object: "+name)
    return value
def collection(name):
    value=bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if value.name not in bpy.context.scene.collection.children: bpy.context.scene.collection.children.link(value)
    return value
def world_bounds(value):
    points=[value.matrix_world @ Vector(point) for point in value.bound_box] if hasattr(value,"bound_box") else [value.matrix_world.translation]
    return [Vector(tuple(min(point[i] for point in points) for i in range(3))),Vector(tuple(max(point[i] for point in points) for i in range(3)))]
def anchor(value,name):
    low,high=world_bounds(value); center=(low+high)/2
    mapping={{"center":center,"min_x":Vector((low.x,center.y,center.z)),"max_x":Vector((high.x,center.y,center.z)),"min_y":Vector((center.x,low.y,center.z)),"max_y":Vector((center.x,high.y,center.z)),"min_z":Vector((center.x,center.y,low.z)),"max_z":Vector((center.x,center.y,high.z))}}
    return mapping.get(name,center)
def offset(value): return Vector(tuple(float(item) for item in value))
def assign_parent(child,parent):
    matrix=child.matrix_world.copy(); child.parent=parent; child.matrix_world=matrix
for item in plan["parents"]:
    parent=bpy.data.objects.get(item["parent"])
    if parent is None and item["create_parent"]:
        parent=bpy.data.objects.new(item["parent"],None); collection(item["collection"] or "ORION Assembly").objects.link(parent); changes.append("Created assembly root "+parent.name); hierarchy_changes.append("Created "+parent.name)
    elif parent is None: failures.append("Missing parent object: "+item["parent"])
    if parent:
        for child_name in item["children"]:
            child=obj(child_name)
            if child and child.parent!=parent: assign_parent(child,parent); changes.append("Parented "+child.name+" to "+parent.name); hierarchy_changes.append(child.name+" -> "+parent.name)
for item in plan["transforms"]:
    value=obj(item["object"])
    if value:
        value.location=tuple(item["location"]); value.rotation_euler=tuple(math.radians(number) for number in item["rotation_degrees"]); value.scale=tuple(item["scale"]); changes.append("Updated transform for "+value.name); alignment_changes.append("Transform "+value.name)
for item in plan["mates"]:
    value=obj(item["object"]); target=obj(item["target"])
    if value and target:
        delta=(anchor(target,item["target_anchor"])+offset(item["offset"]))-anchor(value,item["object_anchor"])
        if delta.length>item["tolerance"]:
            matrix=value.matrix_world.copy(); matrix.translation+=delta; value.matrix_world=matrix; changes.append("Mated "+value.name+" to "+target.name); alignment_changes.append("Mate "+value.name+" -> "+target.name)
def make_material(name,color,family):
    material=bpy.data.materials.get(name) or bpy.data.materials.new(name); text=color.lstrip("#")
    try: rgba=tuple(int(text[index:index+2],16)/255 for index in (0,2,4))+(1,)
    except Exception: rgba=(0.35,0.4,0.48,1)
    material.diffuse_color=rgba; material["orion_material_family"]=family; return material
def vec(value,default): return tuple(float(v) for v in (value if isinstance(value,list) and len(value)==3 else default))
def mesh_object(name,vertices,faces):
    mesh=bpy.data.meshes.new(name+"_Mesh"); mesh.from_pydata(vertices,[],faces); mesh.update(); value=bpy.data.objects.new(name,mesh); bpy.context.collection.objects.link(value); return value
def build_geometry(spec):
    operation=spec["operation"]; name=spec["name"]
    if operation=="primitive":
        kind=spec.get("primitive"); segments=max(8,min(int(spec.get("segments",32)),128))
        if kind=="cube": bpy.ops.mesh.primitive_cube_add()
        elif kind=="cylinder": bpy.ops.mesh.primitive_cylinder_add(vertices=segments)
        elif kind=="sphere": bpy.ops.mesh.primitive_uv_sphere_add(segments=segments,ring_count=max(8,segments//2))
        elif kind=="cone": bpy.ops.mesh.primitive_cone_add(vertices=segments)
        elif kind=="torus": bpy.ops.mesh.primitive_torus_add(major_segments=segments,minor_segments=max(8,segments//3))
        else: failures.append("Unsupported primitive for "+name); return None
        value=bpy.context.object
    elif operation=="mesh":
        vertices=[vec(item,(0,0,0)) for item in spec.get("vertices",[])]; faces=[tuple(int(index) for index in face) for face in spec.get("faces",[])]
        if len(vertices)<3 or not faces: failures.append("Custom mesh needs vertices and faces: "+name); return None
        value=mesh_object(name,vertices,faces)
    elif operation=="extrude_profile":
        points=[(float(point[0]),float(point[1])) for point in spec.get("profile",[])]; depth=max(0.001,float(spec.get("depth",1)))
        if len(points)<3: failures.append("Extruded profile needs at least three points: "+name); return None
        half=depth/2; count=len(points); vertices=[(x,y,-half) for x,y in points]+[(x,y,half) for x,y in points]
        faces=[tuple(reversed(range(count))),tuple(range(count,2*count))]+[(i,(i+1)%count,(i+1)%count+count,i+count) for i in range(count)]
        value=mesh_object(name,vertices,faces)
    elif operation=="lathe_profile":
        profile=[(max(0,float(point[0])),float(point[1])) for point in spec.get("profile",[])]; segments=max(12,min(int(spec.get("segments",48)),128))
        if len(profile)<3: failures.append("Lathed profile needs at least three points: "+name); return None
        vertices=[]; faces=[]
        for ring in range(segments):
            angle=2*math.pi*ring/segments
            for radius,z in profile: vertices.append((radius*math.cos(angle),radius*math.sin(angle),z))
        width=len(profile)
        for ring in range(segments):
            nxt=(ring+1)%segments
            for row in range(width-1): faces.append((ring*width+row,nxt*width+row,nxt*width+row+1,ring*width+row+1))
        value=mesh_object(name,vertices,faces)
    elif operation=="curve_tube":
        path=spec.get("path",[])
        if len(path)<2: failures.append("Curve tube needs at least two path points: "+name); return None
        curve=bpy.data.curves.new(name+"_Curve","CURVE"); curve.dimensions="3D"; curve.bevel_depth=max(0.002,float(spec.get("radius",0.04))); curve.bevel_resolution=max(2,min(int(spec.get("segments",8))//4,8))
        spline=curve.splines.new("BEZIER"); spline.bezier_points.add(len(path)-1)
        for point,coordinate in zip(spline.bezier_points,path): point.co=vec(coordinate,(0,0,0)); point.handle_left_type="AUTO"; point.handle_right_type="AUTO"
        value=bpy.data.objects.new(name,curve); bpy.context.collection.objects.link(value)
    else: failures.append("Unsupported existing-document geometry operation: "+operation); return None
    value.name=name; value.location=vec(spec.get("location"),(0,0,0)); value.rotation_euler=tuple(math.radians(number) for number in vec(spec.get("rotation"),(0,0,0)))
    dimensions=vec(spec.get("dimensions"),(0,0,0))
    if value.type=="MESH" and all(number>0 for number in dimensions): value.dimensions=dimensions
    value["orion_system_role"]=spec.get("system_role",""); value["orion_design_intent"]=spec.get("design_intent",""); value["orion_operation"]=operation
    destination=collection(spec.get("collection") or "ORION Geometry Revisions")
    for current in list(value.users_collection): current.objects.unlink(value)
    destination.objects.link(value)
    if hasattr(value.data,"materials"): value.data.materials.append(make_material(name+" Material",spec.get("color","#667788"),spec.get("material_family","metal")))
    if value.type=="MESH" and float(spec.get("bevel",0))>0:
        modifier=value.modifiers.new("ORION_Geometry_Bevel","BEVEL"); modifier.width=float(spec["bevel"]); modifier.segments=3
    if value.type=="MESH" and int(spec.get("subdivision",0))>0:
        modifier=value.modifiers.new("ORION_Geometry_Subdivision","SUBSURF"); modifier.levels=min(int(spec["subdivision"]),3); modifier.render_levels=modifier.levels
    if value.type=="MESH" and abs(float(spec.get("solidify",0)))>0:
        modifier=value.modifiers.new("ORION_Geometry_Solidify","SOLIDIFY"); modifier.thickness=float(spec["solidify"])
    if bool(spec.get("smooth")) and value.type=="MESH":
        for polygon in value.data.polygons: polygon.use_smooth=True
    if spec.get("role")=="cutter": value.hide_render=True; value.hide_viewport=True
    # Blender defers dimension/rotation evaluation.  Parenting before this update
    # captures an identity matrix and makes the object inherit the parent's scale.
    bpy.context.view_layer.update()
    return value
for item in plan.get("geometry_additions",[]):
    if bpy.data.objects.get(item["name"]): failures.append("Geometry addition already exists: "+item["name"]); continue
    value=build_geometry(item)
    if value: physical_additions.append(value.name); changes.append("Added authored "+item["operation"]+" geometry "+value.name)
for item in plan.get("geometry_replacements",[]):
    previous=bpy.data.objects.get(item["name"])
    if previous is None: failures.append("Missing replacement target: "+item["name"]); continue
    old_topology=topology(previous); old_parent=previous.parent; child_objects=list(previous.children); old_collections=list(previous.users_collection); old_matrix=previous.matrix_world.copy(); old_name=previous.name
    previous.name=old_name+"__ORION_REPLACED"; bpy.data.objects.remove(previous,do_unlink=True)
    replacement=build_geometry(item)
    if replacement:
        # Capture the fully evaluated authored world transform, then preserve it
        # while restoring the original assembly relationship.
        bpy.context.view_layer.update()
        if old_parent and not item.get("parent"): assign_parent(replacement,old_parent)
        for child in child_objects: assign_parent(child,replacement)
        bpy.context.view_layer.update()
        new_topology=topology(replacement); geometry_replacements.append(old_name); topology_changes.append({{"object":old_name,"before":old_topology,"after":new_topology}}); changes.append("Rebuilt geometry for "+old_name+" ("+str(old_topology)+" to "+str(new_topology)+" topology points)")
for item in plan.get("booleans",[]):
    target=obj(item["target"]); cutter=obj(item["cutter"])
    if not target or not cutter or target.type!="MESH" or cutter.type!="MESH": failures.append("Boolean requires two mesh objects: "+item["target"]+" / "+item["cutter"]); continue
    old_topology=topology(target); modifier=target.modifiers.new("ORION_Boolean_"+cutter.name,"BOOLEAN"); modifier.operation=item["operation"]; modifier.solver="EXACT"; modifier.object=cutter
    if item["apply"]:
        bpy.context.view_layer.objects.active=target; target.select_set(True)
        try: bpy.ops.object.modifier_apply(modifier=modifier.name)
        except Exception as exc: failures.append("Could not apply boolean to "+target.name+": "+str(exc))
        target.select_set(False)
        cutter.hide_viewport=True; cutter.hide_render=True
    new_topology=topology(target); topology_changes.append({{"object":target.name,"before":old_topology,"after":new_topology,"operation":item["operation"],"applied":item["apply"]}}); modifier_changes.append("Boolean "+item["operation"]+" on "+target.name); changes.append("Applied physical boolean "+item["operation"]+" to "+target.name)
for item in plan["connectors"]:
    if bpy.data.objects.get(item["name"]): continue
    first=obj(item["from_object"]); second=obj(item["to_object"])
    if not first or not second: continue
    start=anchor(first,item["from_anchor"])+offset(item["start_offset"]); end=anchor(second,item["to_anchor"])+offset(item["end_offset"]); vector=end-start; length=vector.length
    if length<0.0001: failures.append("Connector endpoints coincide: "+item["name"]); continue
    midpoint=(start+end)/2
    if item["shape"]=="cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=max(0.001,item["radius"]),depth=length,location=midpoint); value=bpy.context.object; value.rotation_euler=vector.to_track_quat("Z","Y").to_euler()
    else:
        bpy.ops.mesh.primitive_cube_add(location=midpoint); value=bpy.context.object; value.dimensions=(length,max(0.001,item["width"]),max(0.001,item["depth"])); value.rotation_euler=vector.to_track_quat("X","Z").to_euler()
    value.name=item["name"]; value["orion_system_role"]="connector"; value["orion_design_intent"]=item["design_intent"]
    destination=collection(item["collection"] or "Mechanical Connections")
    for current in list(value.users_collection): current.objects.unlink(value)
    destination.objects.link(value)
    if item["parent"]:
        parent=obj(item["parent"])
        if parent: assign_parent(value,parent)
    if hasattr(value.data,"materials"): value.data.materials.append(make_material(item["name"]+" Material",item["color"],item["material_family"]))
    bevel=value.modifiers.new("ORION_Connector_Bevel","BEVEL"); bevel.width=min(max(item["bevel"],0),max(0.001,length/8)); bevel.segments=3
    changes.append("Added physical connector "+value.name); physical_additions.append(value.name)
for item in plan["modifiers"]:
    value=obj(item["object"])
    if not value: continue
    if value.modifiers.get(item["name"]): continue
    kind=item["type"]
    if kind=="bevel": modifier=value.modifiers.new(item["name"],"BEVEL"); modifier.width=item["amount"]; modifier.segments=item["segments"]
    elif kind=="solidify": modifier=value.modifiers.new(item["name"],"SOLIDIFY"); modifier.thickness=item["amount"]
    else: modifier=value.modifiers.new(item["name"],"SUBSURF"); modifier.levels=item["segments"]; modifier.render_levels=item["segments"]
    changes.append("Added "+kind+" modifier to "+value.name); modifier_changes.append(kind+" on "+value.name)
bpy.context.view_layer.update()
checks=[]
for item in plan["parents"]:
    for child_name in item["children"]:
        child=bpy.data.objects.get(child_name); checks.append({{"check":"parent","object":child_name,"expected":item["parent"],"actual":child.parent.name if child and child.parent else "","passed":bool(child and child.parent and child.parent.name==item["parent"])}})
for item in plan["mates"]:
    value=bpy.data.objects.get(item["object"]); target=bpy.data.objects.get(item["target"]); distance=999.0
    if value and target: distance=(anchor(value,item["object_anchor"])-(anchor(target,item["target_anchor"])+offset(item["offset"]))).length
    checks.append({{"check":"mate","object":item["object"],"target":item["target"],"distance":round(distance,6),"passed":distance<=item["tolerance"]}})
for item in plan["connectors"]: checks.append({{"check":"connector","object":item["name"],"passed":bpy.data.objects.get(item["name"]) is not None}})
for item in plan.get("geometry_additions",[]):
    value=bpy.data.objects.get(item["name"]); checks.append({{"check":"geometry_addition","object":item["name"],"topology":topology(value) if value else 0,"passed":bool(value and topology(value)>0)}})
for item in plan.get("geometry_replacements",[]):
    value=bpy.data.objects.get(item["name"]); delta=next((entry for entry in topology_changes if entry.get("object")==item["name"]),None)
    requested_dimensions=vec(item.get("dimensions"),(0,0,0)); actual_dimensions=tuple(float(number) for number in value.dimensions) if value else (0,0,0); requested_location=Vector(vec(item.get("location"),(0,0,0))); actual_location=value.matrix_world.translation.copy() if value else Vector((999,999,999))
    dimension_errors=[abs(actual-requested)/max(abs(requested),0.001) for actual,requested in zip(actual_dimensions,requested_dimensions)]
    dimensions_match=all(requested<=0 or error<=0.2 for requested,error in zip(requested_dimensions,dimension_errors)); location_error=(actual_location-requested_location).length
    checks.append({{"check":"geometry_replacement","object":item["name"],"topology":topology(value) if value else 0,"requested_dimensions":[round(number,5) for number in requested_dimensions],"actual_dimensions":[round(number,5) for number in actual_dimensions],"location_error":round(location_error,6),"passed":bool(value and delta and topology(value)>0 and dimensions_match and location_error<=0.02)}})
for item in plan.get("booleans",[]):
    target=bpy.data.objects.get(item["target"]); delta=next((entry for entry in topology_changes if entry.get("object")==item["target"] and entry.get("operation")==item["operation"]),None); changed=bool(delta and (not item["apply"] or delta["before"]!=delta["after"])); checks.append({{"check":"boolean","object":item["target"],"operation":item["operation"],"passed":bool(target and changed)}})
scope=plan.get("edit_scope","alignment"); physical_change_count=len(physical_additions)+len(geometry_replacements)+len(plan.get("booleans",[])); authored_geometry_count=len(plan.get("geometry_additions",[]))+len(geometry_replacements)+len(plan.get("booleans",[]))
scope_met=(scope in {{"hierarchy","alignment"}}) or (scope=="structural_repair" and physical_change_count>0) or (scope=="geometry_revision" and authored_geometry_count>0)
if not scope_met: failures.append("Edit scope "+scope+" requires a verified physical or authored geometry change; hierarchy and coordinate edits are insufficient.")
bpy.context.view_layer.update(); after_scene_extent=scene_mesh_extent(); scene_growth=max((after/max(before,0.001) for before,after in zip(before_scene_extent,after_scene_extent)),default=1.0)
scene_bounds_match=scene_growth<=1.5
checks.append({{"check":"scene_bounds","before":[round(number,5) for number in before_scene_extent],"after":[round(number,5) for number in after_scene_extent],"maximum_growth":round(scene_growth,5),"passed":scene_bounds_match}})
passed=not failures and bool(checks) and all(item["passed"] for item in checks) and scope_met
saved=False
if passed:
    if plan["render_preview"]:
        bpy.context.scene.render.filepath=preview_path; bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=source_path); saved=True
else:
    failures.append("Safety validation rejected the edit; the source .blend was not saved.")
report={{"passed":passed,"saved":saved,"edit_scope":scope,"scope_met":scope_met,"changes":changes,"failures":failures,"checks":checks,"hierarchy_changes":hierarchy_changes,"alignment_changes":alignment_changes,"physical_additions":physical_additions,"geometry_replacements":geometry_replacements,"topology_changes":topology_changes,"modifier_changes":modifier_changes,"physical_change_count":physical_change_count,"authored_geometry_count":authored_geometry_count,"before_scene_extent":before_scene_extent,"after_scene_extent":after_scene_extent,"before_object_count":len(before_names),"after_object_count":len(bpy.data.objects),"new_objects":sorted({{obj.name for obj in bpy.data.objects}}-before_names),"changed_parent_count":sum((obj.parent.name if obj.parent else "")!=before_parents.get(obj.name,"") for obj in bpy.data.objects)}}
with open(report_path,"w",encoding="utf-8") as handle: json.dump(report,handle,indent=2)
'''


def edit_document(
    project_name: str, file_path: str, parents: list[dict], transforms: list[dict],
    mates: list[dict], connectors: list[dict], modifiers: list[dict],
    render_preview: bool, save_open_document: bool, confirmed: bool,
    edit_scope: str = "alignment", geometry_additions: list[dict] | None = None,
    geometry_replacements: list[dict] | None = None, booleans: list[dict] | None = None,
    _request_id: str = "",
) -> dict:
    blocked = workspace.require_confirmation(confirmed, "existing Blender document edit")
    if blocked:
        return blocked
    if not BINARY.is_file():
        return {"ok": False, "error_code": "blender_unavailable", "error": "Blender is not installed."}
    geometry_additions = list(geometry_additions or [])
    geometry_replacements = list(geometry_replacements or [])
    booleans = list(booleans or [])
    if edit_scope not in {"hierarchy", "alignment", "structural_repair", "geometry_revision"}:
        return {"ok": False, "error_code": "invalid_blender_edit_scope", "error": "Choose a supported Blender edit scope."}
    if not any((parents, transforms, mates, connectors, modifiers, geometry_additions, geometry_replacements, booleans)):
        return {"ok": False, "error_code": "empty_blender_edit", "error": "At least one concrete object edit is required."}
    if edit_scope == "structural_repair" and not any((connectors, geometry_additions, geometry_replacements, booleans)):
        return {"ok": False, "error_code": "insufficient_structural_edit", "error": "A structural repair must include a physical connector, authored geometry, replacement geometry, or boolean—not only hierarchy or coordinate changes."}
    if edit_scope == "geometry_revision" and not any((geometry_additions, geometry_replacements, booleans)):
        return {"ok": False, "error_code": "insufficient_geometry_edit", "error": "A geometry revision must add, rebuild, or boolean real geometry; transforms and parenting do not remodel an object."}
    located = _locate(project_name, file_path)
    if not located.get("ok"):
        return located
    source = Path(str(located["artifact"]))
    if save_open_document:
        saved = _save_open_document()
        if not saved.get("ok"):
            return {"ok": False, "error_code": "blender_save_failed", "requires_user": True, "error": "The open Blender document could not be saved before editing."}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = source.with_name(f"{source.stem}.orion-backup-{stamp}.blend")
    shutil.copy2(source, backup)
    report = source.parent / "orion-existing-edit-report.json"
    preview = source.parent / "orion-existing-edit-preview.png"
    plan = {
        "parents": parents, "transforms": transforms, "mates": mates,
        "connectors": connectors, "modifiers": modifiers,
        "edit_scope": edit_scope, "geometry_additions": geometry_additions,
        "geometry_replacements": geometry_replacements, "booleans": booleans,
        "render_preview": bool(render_preview),
    }
    operation_count = sum(len(items) for items in (parents, transforms, mates, connectors, modifiers, geometry_additions, geometry_replacements, booleans))
    activity.update("working", "Editing existing Blender document…", f"Backup saved • {edit_scope.replace('_', ' ')} • applying {operation_count} declared changes to {source.name}")
    result, _ = _run_blender(source, _edit_script(plan, source, report, preview), _request_id, timeout=900)
    if result.get("cancelled"):
        return {"ok": False, "cancelled": True, "error_code": "task_cancelled", "error": "The Blender edit was cancelled; the original backup remains available.", "backup": str(backup)}
    if not result.get("ok") or not report.is_file():
        return {"ok": False, "error_code": "blender_existing_edit_failed", "error": str(result.get("error") or result.get("stdout") or "Blender could not apply the edit.")[-1600:], "backup": str(backup)}
    try:
        audit = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error_code": "blender_edit_audit_unreadable", "error": str(exc), "backup": str(backup)}
    if not audit.get("passed"):
        return {"ok": False, "error_code": "blender_edit_verification_failed", "error": "The existing-file edit did not satisfy its declared scope and geometry checks.", "audit": audit, "backup": str(backup)}
    # Prove the saved artifact independently before attempting any GUI reload.
    # A macOS automation failure must never erase a successful document edit.
    disk_check = inspect_document(file_path=str(source), _request_id=_request_id)
    if not disk_check.get("ok"):
        return {
            "ok": False, "error_code": "blender_post_edit_inspection_failed",
            "error": "Blender saved the edit, but ORION could not reopen the file headlessly to verify it.",
            "audit": audit, "backup": str(backup), "file_path": str(source),
        }
    reload_warning = ""
    try:
        closed = mac_tools.quit_application("Blender")
    except Exception as exc:
        closed = {"ok": False, "error": str(exc)}
        reload_warning = "macOS could not close the previous Blender window automatically."
    try:
        opened = mac_tools.open_file_in_application(source, "Blender")
    except Exception as exc:
        opened = {"ok": False, "loaded": False, "error": str(exc)}
    if not opened.get("loaded"):
        reload_warning = (reload_warning + " The edited file is verified on disk but its visible reload could not be confirmed.").strip()
    diagnostics.event("blender_existing_document_edited", request_id=_request_id, project=located.get("project", source.stem), file_path=str(source), changes=len(audit.get("changes", [])), verified=True)
    return {
        "ok": True, "verified": True, "application": "Blender", "project": located.get("project") or source.stem,
        "file_path": str(source), "backup": str(backup), "report": str(report),
        "preview": str(preview) if render_preview and preview.is_file() else "",
        "audit": audit, "disk_verification": {
            "object_count": disk_check.get("object_count", 0),
            "parented_object_count": disk_check.get("parented_object_count", 0),
        },
        "loaded": bool(opened.get("loaded")), "open_result": opened,
        "reload_warning": reload_warning,
        "_activity_detail": f"Edited the existing .blend in place • {audit.get('authored_geometry_count', 0)} authored geometry operations • {audit.get('physical_change_count', 0)} physical changes • {audit.get('changed_parent_count', 0)} hierarchy changes • backup preserved",
    }
