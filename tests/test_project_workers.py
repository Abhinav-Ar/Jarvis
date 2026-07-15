import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import blender_worker
import blender_advanced_worker
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
            "radius": 0, "segments": 32, "color": "#778899", "metallic": 0.4,
            "roughness": 0.4, "emission": 0, "bevel": 0.02, "subdivision": 0,
            "solidify": 0, "mirror_axis": "none", "array_count": 2,
            "array_offset": [0.1, 0, 0], "smooth": True, "role": "object",
            "design_intent": "Provides a deliberate production requirement and load path.",
            "collection": collection,
        }

    def test_creation_requires_explicit_confirmation(self):
        result = blender_worker.create_project("Test", "", [], False, False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "confirmation_required")

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

    def test_six_instance_hub_array_binds_to_each_real_wheel(self):
        wheels = []
        for index, suffix in enumerate(("FL", "FR", "ML", "MR", "RL", "RR")):
            wheel = self.advanced_component(f"Wheel_{suffix}", "mesh", collection="Wheels")
            wheel["location"] = [index // 2, -0.4 if index % 2 == 0 else 0.4, 0.25]
            wheels.append(wheel)
        hub = self.advanced_component("Wheel_Hubs", "primitive", "cylinder", "Wheels")
        hub["array_count"] = 6
        axle = self.advanced_component("Wheel_Axles", "primitive", "cylinder", "Suspension")
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
