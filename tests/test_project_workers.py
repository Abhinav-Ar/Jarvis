import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import blender_worker
import blender_advanced_worker
import blender_existing_worker
import openscad_worker
import project_workspace


class NativeProjectWorkerTests(unittest.TestCase):
    @staticmethod
    def advanced_component(name: str, operation: str = "extrude_profile", primitive: str = "none", collection: str = "Chassis") -> dict:
        return {
            "name": name, "operation": operation, "primitive": primitive,
            "profile": [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5]],
            "path": [], "vertices": [], "faces": [], "dimensions": [1, 1, 1],
            "location": [0, 0, 0], "rotation": [0, 0, 0], "depth": 0.2,
            "radius": 0, "segments": 32, "color": "#778899", "material_family": "metal", "metallic": 0.4,
            "roughness": 0.4, "transmission": 0, "emission": 0, "bevel": 0.02, "subdivision": 0,
            "solidify": 0, "mirror_axis": "none", "array_count": 2,
            "array_offset": [0.1, 0, 0], "smooth": True, "role": "object", "system_role": "detail",
            "design_intent": "Provides a deliberate production requirement and load path.",
            "collection": collection,
        }

    def test_creation_requires_explicit_confirmation(self):
        result = blender_worker.create_project("Test", "", [], False, False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "confirmation_required")

    def test_existing_blender_editor_requires_a_concrete_change(self):
        with patch.object(blender_existing_worker, "BINARY", Path(__file__)):
            result = blender_existing_worker.edit_document(
                "Rover", "", [], [], [], [], [], False, False, True,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "empty_blender_edit")

    def test_existing_blender_geometry_scope_rejects_coordinate_only_work(self):
        with patch.object(blender_existing_worker, "BINARY", Path(__file__)):
            result = blender_existing_worker.edit_document(
                "Rover", "", [],
                [{"object": "Wheel", "location": [0, 0, 0], "rotation_degrees": [0, 0, 0], "scale": [1, 1, 1]}],
                [], [], [], False, False, True, edit_scope="geometry_revision",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "insufficient_geometry_edit")

    def test_existing_blender_script_preserves_and_verifies_named_objects(self):
        plan = {
            "parents": [{"parent": "Assembly", "children": ["Wheel"], "create_parent": True, "collection": "Assembly"}],
            "transforms": [], "mates": [], "connectors": [], "modifiers": [], "render_preview": False,
        }
        source = blender_existing_worker._edit_script(plan, Path("/tmp/test.blend"), Path("/tmp/report.json"), Path("/tmp/preview.png"))
        self.assertIn("before_names", source)
        self.assertIn("assign_parent", source)
        self.assertIn("child.parent!=parent", source)
        self.assertIn('if bpy.data.objects.get(item["name"]): continue', source)
        self.assertIn("bool(checks)", source)
        self.assertIn('bpy.ops.wm.save_as_mainfile', source)
        self.assertIn('"passed":passed', source)

    def test_existing_blender_script_builds_and_audits_real_geometry(self):
        component = self.advanced_component("Wheel")
        plan = {
            "edit_scope": "geometry_revision", "parents": [], "transforms": [], "mates": [],
            "connectors": [], "modifiers": [], "geometry_additions": [],
            "geometry_replacements": [component], "booleans": [], "render_preview": False,
        }
        source = blender_existing_worker._edit_script(
            plan, Path("/tmp/test.blend"), Path("/tmp/report.json"), Path("/tmp/preview.png"),
        )
        self.assertIn("def build_geometry", source)
        self.assertIn('operation=="extrude_profile"', source)
        self.assertIn('"geometry_replacements":geometry_replacements', source)
        self.assertIn("requires a verified physical or authored geometry change", source)
        self.assertIn("Blender defers dimension/rotation evaluation", source)
        self.assertIn('"check":"scene_bounds"', source)
        self.assertIn("if passed:", source)
        self.assertIn('"saved":saved', source)
        self.assertIn("the source .blend was not saved", source)

    def test_refinement_requires_explicit_confirmation(self):
        result = blender_worker.refine_project("Test", "", "desk_perimeter", "#00E5FF", 1.0, True, False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "confirmation_required")

    def test_advanced_blender_requires_explicit_confirmation(self):
        result = blender_advanced_worker.create_project("Test", "", [], [], "#000000", "#00FFFF", True, False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "confirmation_required")

    def test_advanced_blender_rejects_missing_boolean_target(self):
        component = {
            "name": "Shell", "operation": "primitive", "primitive": "cube",
            "profile": [], "path": [], "dimensions": [1, 1, 1],
        }
        error = blender_advanced_worker._validate(
            [component], [{"target": "Shell", "cutter": "Missing", "operation": "DIFFERENCE"}],
        )
        self.assertIn("existing components", error)

    def test_production_rover_rejects_primitive_primary_wheels(self):
        components = [self.advanced_component(f"Structure {index}", collection=f"System {index % 5}") for index in range(12)]
        for index, component in enumerate(components):
            component["color"] = f"#{index + 1:02x}6688"
            component["metallic"] = (index % 5) / 5
        components[0]["operation"] = "curve_tube"
        components[1]["operation"] = "mesh"
        for index in range(6):
            components.append(self.advanced_component(f"Wheel {index}", "primitive", "cylinder", "Wheels"))
        error = blender_advanced_worker._validate_design(
            components, [], {"requirements": [
                "Six-wheel rocker-bogie suspension", "Detailed wheels", "Layered chassis",
                "Sensor mast", "Sample arm", "Cargo platform",
            ]},
        )
        self.assertIn("wheel", error.lower())
        self.assertIn("primitive", error.lower())

    def test_advanced_script_normalizes_canonical_radians_and_reports_live_stages(self):
        script = blender_advanced_worker._script(
            [self.advanced_component("Wheel", "primitive", "cylinder", "Wheels")], [],
            Path("/tmp/test.blend"), Path("/tmp/preview.png"), Path("/tmp/review.json"),
            Path("/tmp/progress.json"), {}, "#000000", "#00FFFF", True,
        )
        compile(script, "orion_advanced_build.py", "exec")
        self.assertIn("rotation_degrees", script)
        self.assertIn("Modeling authored components", script)
        self.assertIn("Running geometry quality review", script)
        self.assertIn("obj.dimensions=requested_dimensions", script)
        self.assertNotIn("obj.scale=vec(spec.get(\"dimensions\"", script)

    def test_validation_returns_every_mesh_problem_in_one_pass(self):
        components = [
            {**self.advanced_component("Wheel Left", "mesh"), "vertices": [], "faces": []},
            {**self.advanced_component("Wheel Right", "mesh"), "vertices": [], "faces": []},
        ]
        errors = blender_advanced_worker._validation_errors(components, [])
        joined = " ".join(errors)
        self.assertIn("Wheel Left", joined)
        self.assertIn("Wheel Right", joined)
        self.assertGreaterEqual(len(errors), 4)

    def test_empty_mesh_with_declared_shape_is_repaired_locally(self):
        wheel = self.advanced_component("Primary Wheel", "mesh", "cylinder", "Wheels")
        wheel["vertices"] = []
        wheel["faces"] = []
        wheel["system_role"] = "wheel"
        latch = self.advanced_component("Service Latch", "mesh", "cube", "Details")
        latch["vertices"] = []
        latch["faces"] = []
        normalized, changes = blender_advanced_worker._normalize_components([wheel, latch])
        self.assertEqual(normalized[0]["operation"], "lathe_profile")
        self.assertGreaterEqual(len(normalized[0]["profile"]), 3)
        self.assertEqual(normalized[1]["operation"], "primitive")
        self.assertEqual(len(changes), 2)

    def test_semantic_roles_make_mobility_checks_independent_of_names(self):
        components = []
        for role, count in (("wheel", 6), ("hub", 6), ("axle", 6), ("tread", 6), ("rocker", 2), ("bogie", 2), ("pivot", 1)):
            for index in range(count):
                component = self.advanced_component(f"Part {role} {index}", "extrude_profile", collection="Mobility")
                component["system_role"] = role
                components.append(component)
        for index in range(12):
            component = self.advanced_component(f"Body {index}", "extrude_profile", collection=f"System {index % 5}")
            component["color"] = f"#{index + 20:02x}6688"
            component["metallic"] = (index % 5) / 5
            components.append(component)
        components[0]["operation"] = "curve_tube"
        components[0]["path"] = [[0, 0, 0], [1, 0, 0]]
        components[1]["operation"] = "mesh"
        components[1]["vertices"] = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        components[1]["faces"] = [[0, 1, 2]]
        errors = blender_advanced_worker._design_errors(components, [], {"requirements": [
            "Six-wheel rocker-bogie suspension", "Detailed wheels", "Layered chassis",
            "Sensor mast", "Sample arm", "Cargo platform",
        ]})
        self.assertFalse(any("mobility interfaces" in error for error in errors))

    def test_six_instance_hub_array_binds_to_each_real_wheel(self):
        wheels = []
        for index, suffix in enumerate(("FL", "FR", "ML", "MR", "RL", "RR")):
            wheel = self.advanced_component(f"Wheel_{suffix}", "mesh", collection="Wheels")
            wheel["system_role"] = "wheel"
            wheel["location"] = [index // 2, -0.4 if index % 2 == 0 else 0.4, 0.25]
            wheels.append(wheel)
        hub = self.advanced_component("Wheel_Hubs", "primitive", "cylinder", "Wheels")
        hub["system_role"] = "hub"
        hub["array_count"] = 6
        axle = self.advanced_component("Wheel_Axles", "primitive", "cylinder", "Suspension")
        axle["system_role"] = "axle"
        axle["array_count"] = 6
        expanded, systems = blender_advanced_worker._expand_reusable_systems(
            wheels + [hub, axle], {"requirements": ["Six-wheel rocker-bogie suspension"]},
        )
        hubs = [item for item in expanded if "hub" in item["name"].lower()]
        axles = [item for item in expanded if "axle" in item["name"].lower()]
        self.assertEqual(len(hubs), 6)
        self.assertEqual(len(axles), 6)
        self.assertEqual([item["location"] for item in hubs], [item["location"] for item in wheels])
        self.assertEqual(systems, ["Wheel_Hubs", "Wheel_Axles"])

    def test_rejected_advanced_spec_is_saved_as_resumable_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            with (
                patch.object(project_workspace, "ROOT", Path(folder)),
                patch.object(blender_advanced_worker, "BINARY", Path(__file__)),
                patch("blender_advanced_worker.design_intelligence.load_brief", return_value=({
                    "brief_id": "brief", "artifact_type": "visual_model", "requirements": [],
                    "manufacturing_process": "visual_only", "selected_concept": "Test",
                    "design_principles": [], "quality_gates": [],
                }, "")),
                patch("project_workspace.activity.update_background_task"),
                patch("project_workspace.diagnostics.event"),
            ):
                result = blender_advanced_worker.create_project(
                    "Rejected Rover", "", [], [], "#000000", "#00ffff", True, True,
                    design_brief_id="brief", _request_id="request",
                )
            self.assertFalse(result["ok"])
            self.assertTrue(result["resumable"])
            self.assertTrue(Path(result["draft_path"]).is_file())
            self.assertEqual(result["design_brief_id"], "brief")

    def test_resume_advanced_project_reuses_exact_saved_draft(self):
        payload = {
            "project_name": "Saved Rover", "description": "Resume me", "design_brief_id": "brief",
            "components": [], "booleans": [], "world_color": "#000", "accent_color": "#0ff", "render": True,
        }
        with (
            patch("blender_advanced_worker.workspace.locate_resumable_draft", return_value={"ok": True, "payload": payload}),
            patch("blender_advanced_worker.create_project", return_value={"ok": True}) as create,
        ):
            result = blender_advanced_worker.resume_project("Saved Rover", True, _request_id="request")
        self.assertTrue(result["ok"])
        create.assert_called_once_with(
            project_name="Saved Rover", description="Resume me", components=[], booleans=[],
            world_color="#000", accent_color="#0ff", render=True, confirmed=True,
            design_brief_id="brief", _request_id="request",
        )

    def test_resume_rejected_draft_returns_issues_without_rebuilding(self):
        payload = {
            "project_name": "Saved Rover", "description": "Resume me", "design_brief_id": "brief",
            "components": [], "booleans": [], "world_color": "#000", "accent_color": "#0ff", "render": True,
            "validation_status": "rejected", "validation_issues": ["Add six axle mounts."],
        }
        with (
            patch("blender_advanced_worker.workspace.locate_resumable_draft", return_value={"ok": True, "payload": payload, "path": "/tmp/draft.json"}),
            patch("blender_advanced_worker.create_project") as create,
        ):
            result = blender_advanced_worker.resume_project("Saved Rover", True, _request_id="request")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "draft_revision_required")
        self.assertIn("axle", result["error"].lower())
        self.assertIn("revision_context", result)
        create.assert_not_called()

    def test_revise_advanced_project_preserves_unaffected_components(self):
        shell = self.advanced_component("Existing Shell")
        wheel = self.advanced_component("Existing Wheel")
        axle = self.advanced_component("New Axle")
        axle["system_role"] = "axle"
        payload = {
            "project_name": "Saved Rover", "description": "Revise me", "design_brief_id": "brief",
            "components": [shell, wheel], "booleans": [], "world_color": "#000", "accent_color": "#0ff", "render": True,
        }
        with (
            patch("blender_advanced_worker.workspace.locate_resumable_draft", return_value={"ok": True, "payload": payload, "path": "/tmp/draft.json"}),
            patch("blender_advanced_worker.create_project", return_value={"ok": True, "project": "Saved Rover"}) as create,
        ):
            result = blender_advanced_worker.revise_project(
                "Saved Rover", additions=[axle], replacements=[], remove_names=[],
                intent_updates=[{"name": "Existing Shell", "design_intent": "Carries the revised primary structural load path."}],
                transform_updates=[], material_updates=[], boolean_additions=[], render=True,
                confirmed=True, _request_id="request",
            )
        self.assertTrue(result["ok"])
        passed = create.call_args.kwargs["components"]
        self.assertEqual([item["name"] for item in passed], ["Existing Shell", "Existing Wheel", "New Axle"])
        self.assertEqual(passed[0]["design_intent"], "Carries the revised primary structural load path.")
        self.assertEqual(result["revision"]["preserved_components"], 2)
        self.assertEqual(create.call_args.kwargs["design_brief_id"], "brief")

    def test_revision_can_update_an_object_added_in_the_same_atomic_patch(self):
        shell = self.advanced_component("Existing Shell")
        addition = self.advanced_component("Clearance Beam")
        payload = {
            "project_name": "Saved Mount", "description": "Revise me", "design_brief_id": "brief",
            "components": [shell], "booleans": [], "world_color": "#000", "accent_color": "#0ff", "render": True,
        }
        with (
            patch("blender_advanced_worker.workspace.locate_resumable_draft", return_value={"ok": True, "payload": payload, "path": "/tmp/draft.json"}),
            patch("blender_advanced_worker.create_project", return_value={"ok": True, "project": "Saved Mount"}) as create,
        ):
            result = blender_advanced_worker.revise_project(
                "Saved Mount", additions=[addition], replacements=[], remove_names=[],
                intent_updates=[{"name": "Clearance Beam", "design_intent": "Defines the verified payload clearance boundary."}],
                transform_updates=[{"name": "Clearance Beam", "dimensions": [2, 1, 1], "location": [0, 0, 1], "rotation": [0, 0, 0]}],
                material_updates=[], boolean_additions=[], render=True, confirmed=True, _request_id="request",
            )
        self.assertTrue(result["ok"])
        merged = {item["name"]: item for item in create.call_args.kwargs["components"]}
        self.assertEqual(merged["Clearance Beam"]["dimensions"], [2, 1, 1])
        self.assertIn("verified payload", merged["Clearance Beam"]["design_intent"])

    def test_initial_concept_quality_ignores_reference_geometry(self):
        components = []
        for index in range(6):
            component = self.advanced_component(f"Mount Part {index}", collection="Mount")
            if index == 0:
                component["operation"] = "curve_tube"
                component["path"] = [[0, 0, 0], [1, 0, 0]]
            component["location"] = [index * 0.1, 0, 0.25]
            component["dimensions"] = [0.2, 0.2, 0.2]
            components.append(component)
        for name in ("Wall", "Stud_Left", "Stud_Right", "Venator_Envelope"):
            reference = self.advanced_component(name, "primitive", "cube", "Environment")
            reference["system_role"] = "structure" if "Stud" in name else "environment"
            reference["dimensions"] = [2.2, 0.1, 1.5]
            components.append(reference)
        brief = {
            "artifact_type": "assembly", "intended_use": "Initial editable concept for visual review",
            "constraints": ["Remain concept-level"], "requirements": ["Mount safely"] * 6,
            "target_dimensions": [1500, 500, 500], "units": "mm",
        }
        errors = blender_advanced_worker._design_errors(components, [], brief)
        self.assertFalse(any("target envelope" in error for error in errors))
        self.assertFalse(any("primitives" in error for error in errors))
        self.assertFalse(any("tertiary" in error for error in errors))
        self.assertEqual(blender_advanced_worker._design_stage(brief), "concept")

    def test_resume_revalidates_rejected_draft_locally_before_cloud_revision(self):
        components = [self.advanced_component(f"Part {index}") for index in range(6)]
        components[0]["operation"] = "curve_tube"
        components[0]["path"] = [[0, 0, 0], [1, 0, 0]]
        payload = {
            "project_name": "Saved Mount", "description": "Resume me", "design_brief_id": "brief",
            "components": components, "booleans": [], "world_color": "#000", "accent_color": "#0ff", "render": True,
            "validation_status": "rejected", "validation_issues": ["A stale preflight error."],
        }
        brief = {
            "artifact_type": "assembly", "intended_use": "Initial editable concept for visual review",
            "constraints": ["Concept-level"], "requirements": ["Mount safely"] * 6,
            "target_dimensions": [], "units": "mm",
        }
        with (
            patch("blender_advanced_worker.workspace.locate_resumable_draft", return_value={"ok": True, "payload": payload, "path": "/tmp/draft.json"}),
            patch("blender_advanced_worker.design_intelligence.load_brief", return_value=(brief, "")),
            patch("blender_advanced_worker.create_project", return_value={"ok": True}) as create,
        ):
            result = blender_advanced_worker.resume_project("Saved Mount", True, _request_id="request")
        self.assertTrue(result["ok"])
        create.assert_called_once()

    def test_recovery_bundle_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = project_workspace.write_recovery(
                root, {"project": "Mount", "application": "Blender", "request_id": "r", "job_id": "j"},
                stage="preflight_repair", status="resumable", draft_path=root / "draft.json",
                issues=[{"code": "test", "message": "Fix it"}], repairs=["normalized"], next_action="Resume locally",
            )
            payload = __import__("json").loads(path.read_text())
            self.assertEqual(payload["stage"], "preflight_repair")
            self.assertEqual(payload["next_action"], "Resume locally")
            self.assertEqual(len(payload["history"]), 1)

    def test_inspect_advanced_project_explains_collection_and_parenting_model(self):
        shell = self.advanced_component("Existing Shell")
        shell["collection"] = "Structure"
        payload = {
            "project_name": "Saved Rover", "design_brief_id": "brief",
            "components": [shell], "booleans": [], "validation_status": "approved",
        }
        with patch(
            "blender_advanced_worker.workspace.locate_resumable_draft",
            return_value={"ok": True, "payload": payload, "path": "/tmp/orion-missing/draft.json"},
        ):
            result = blender_advanced_worker.inspect_project("Saved Rover")
        self.assertTrue(result["ok"])
        self.assertEqual(result["collection_count"], 1)
        self.assertTrue(result["assembly_structure"]["collections_are_organizational"])
        self.assertIn("independent Blender objects", result["assembly_structure"]["explanation"])

    def test_blender_script_generates_physical_accents_and_component_detail(self):
        script = blender_worker._create_script(
            [{"name": "Desk", "type": "cube"}], Path("/tmp/test.blend"),
            Path("/tmp/preview.png"), True, "#F4F7FF", 0.8,
            "desk_perimeter", "#00E5FF", 1.0,
        )
        self.assertIn("ORION_Accent_Front", script)
        self.assertIn("ORION_DeskLeg_", script)
        self.assertIn("ORION_Key_", script)
        self.assertIn('"#F4F7FF" if accent_style != "none"', script)

    def test_openscad_rejects_external_includes(self):
        with patch.object(openscad_worker, "BINARY", Path(__file__)):
            result = openscad_worker.create_project("Unsafe", "", "include </tmp/private.scad>; cube(1);", True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "unsafe_scad_source")

    def test_openscad_project_is_compiled_and_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def compile_model(command, **kwargs):
                output = Path(command[command.index("-o") + 1])
                output.write_text("""solid orion
facet normal 0 0 1
 outer loop
  vertex 0 0 0
  vertex 0 1 0
  vertex 1 0 0
 endloop
endfacet
facet normal 0 1 0
 outer loop
  vertex 0 0 0
  vertex 1 0 0
  vertex 0 0 1
 endloop
endfacet
facet normal 1 0 0
 outer loop
  vertex 0 0 0
  vertex 0 0 1
  vertex 0 1 0
 endloop
endfacet
facet normal 1 1 1
 outer loop
  vertex 1 0 0
  vertex 0 1 0
  vertex 0 0 1
 endloop
endfacet
endsolid orion
""")
                return Mock(returncode=0, stdout="Geometry cache size: 1")

            with (
                patch.object(project_workspace, "ROOT", root),
                patch.object(openscad_worker, "BINARY", Path(__file__)),
                patch("openscad_worker.design_intelligence.load_brief", return_value=({
                    "brief_id": "abc123abc123", "selected_concept": "Test",
                    "quality_gates": [], "print_settings": {}, "artifact_type": "3d_print",
                    "manufacturing_process": "fdm_3d_print", "design_principles": [],
                }, "")),
                patch("openscad_worker.subprocess.run", side_effect=compile_model),
                patch("project_workspace.activity.update_background_task"),
                patch("project_workspace.diagnostics.event"),
                patch("project_workspace.open_project", return_value={"ok": True, "loaded": True}),
            ):
                result = openscad_worker.create_project("Phone Stand", "A stand", "cube([10,20,3]);", True)
            self.assertTrue(result["ok"])
            self.assertTrue(any(path.endswith(".scad") for path in result["artifacts"]))
            self.assertTrue(any(path.endswith(".stl") for path in result["artifacts"]))

    def test_media_paths_cannot_escape_user_home(self):
        accepted, error = project_workspace.bounded_media_paths(["/etc/hosts"])
        self.assertEqual(accepted, [])
        self.assertTrue(error)

    def test_open_project_loads_exact_verified_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project_folder = root / "Neon Desk" / "Blender"
            project_folder.mkdir(parents=True)
            scene = project_folder / "Neon Desk.blend"
            scene.write_bytes(b"BLENDER")
            manifest = {
                "project": "Neon Desk", "application": "Blender", "verified": True,
                "finished_at": 10, "artifacts": [str(scene)],
            }
            (project_folder / "orion-project.json").write_text(__import__("json").dumps(manifest))
            with (
                patch.object(project_workspace, "ROOT", root),
                patch("project_workspace.mac_tools.open_file_in_application", return_value={
                    "ok": True, "loaded": True, "application": "Blender", "path": str(scene),
                }) as opener,
                patch("project_workspace.diagnostics.event"),
            ):
                result = project_workspace.open_project("Blender", "Neon Desk")
            self.assertTrue(result["ok"])
            self.assertTrue(result["loaded"])
            opener.assert_called_once_with(scene, "Blender")


if __name__ == "__main__":
    unittest.main()
