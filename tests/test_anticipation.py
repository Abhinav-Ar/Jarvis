import unittest
from unittest.mock import patch

import anticipation


class AnticipationTests(unittest.TestCase):
    def test_git_objective_expands_prerequisites_but_not_new_authority(self):
        result = anticipation.analyze("Commit my changes")
        self.assertEqual(result["category"], "git_delivery")
        self.assertTrue(result["action"])
        self.assertTrue(any("repository" in step for step in result["prerequisite_steps"]))
        self.assertIn("do not perform consequential", result["policy"])

    def test_informational_question_is_not_turned_into_an_action(self):
        result = anticipation.analyze("How do I install Blender?")
        self.assertEqual(result["category"], "software_installation")
        self.assertFalse(result["action"])
        self.assertEqual(result["prerequisite_steps"], [])

    def test_context_probe_is_local_and_bounded(self):
        with patch("mac_tools.frontmost_application", return_value="Blender"), patch(
            "mac_tools.workspace_applications", return_value=[
                {"name": "Blender", "capabilities": ["model"]},
                {"name": "DaVinci Resolve", "capabilities": ["edit"]},
            ]
        ), patch("agent_platform.AgentPlatform.active_project_session", return_value={"ok": True, "session": None}):
            context = anticipation.probe_context("Create a Blender product model")
        self.assertEqual(context["frontmost_application"], "Blender")
        self.assertEqual([item["name"] for item in context["design_applications"]], ["Blender"])


if __name__ == "__main__":
    unittest.main()
