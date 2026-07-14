import unittest
from unittest.mock import patch

import capability_families


class CapabilityFamilyTests(unittest.TestCase):
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
