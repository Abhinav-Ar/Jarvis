import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import capability_families


class CapabilityFamilyTests(unittest.TestCase):
    def test_versioned_application_bundle_is_detected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "OpenSCAD-2021.01.app").mkdir()
            original_path = capability_families.Path

            def routed_path(value):
                if value == "/Applications":
                    return root
                return original_path(value)

            with patch.object(capability_families, "Path", side_effect=routed_path):
                self.assertTrue(capability_families._app("OpenSCAD"))

    def test_nested_application_bundle_is_detected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "DaVinci Resolve" / "DaVinci Resolve.app").mkdir(parents=True)
            original_path = capability_families.Path

            def routed_path(value):
                return root if value == "/Applications" else original_path(value)

            with patch.object(capability_families, "Path", side_effect=routed_path):
                self.assertTrue(capability_families._app("DaVinci Resolve"))

    def test_registry_contains_all_broad_families(self):
        names = set(capability_families.families())
        self.assertEqual(names, {
            "google_workspace", "microsoft_365", "development", "creative",
            "engineering", "business", "research", "macos",
        })

    @patch.dict("os.environ", {}, clear=True)
    def test_business_objective_automatically_adds_artifact_family(self):
        plan = capability_families.compile_objective("Create a spreadsheet for my finances and budget")
        names = {item["name"] for item in plan["team"]}
        self.assertIn("Business", names)
        self.assertTrue(names.intersection({"Google Workspace", "Microsoft 365"}))

    def test_development_objective_selects_codex_family(self):
        plan = capability_families.compile_objective("Use Codex to implement this feature")
        self.assertIn("Development", {item["name"] for item in plan["team"]})


if __name__ == "__main__":
    unittest.main()
