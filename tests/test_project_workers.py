import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import blender_worker
import blender_advanced_worker
import openscad_worker
import project_workspace


class NativeProjectWorkerTests(unittest.TestCase):
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
                output.write_bytes(b"solid orion\nendsolid orion\n")
                return Mock(returncode=0, stdout="Geometry cache size: 1")

            with (
                patch.object(project_workspace, "ROOT", root),
                patch.object(openscad_worker, "BINARY", Path(__file__)),
                patch("openscad_worker.subprocess.run", side_effect=compile_model),
                patch("project_workspace.activity.update_background_task"),
                patch("project_workspace.diagnostics.event"),
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
