import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from task_engine import TaskEngine


class TaskEngineTests(unittest.TestCase):
    def test_imperative_simple_action_requires_tool_evidence(self):
        with TemporaryDirectory() as runtime, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": runtime}):
            engine = TaskEngine()
            client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: None))
            plan = engine.plan(client, "model", "low", "Open Safari")
            self.assertTrue(plan.requires_tools)
            self.assertEqual(plan.steps[-1], "Verify the outcome")

    def test_informational_how_to_request_does_not_require_action(self):
        self.assertFalse(TaskEngine.action_requested("How do I install Blender?"))
        self.assertTrue(TaskEngine.action_requested("Install Blender on my laptop"))

    def test_planner_creates_prerequisite_plan_and_persists_state(self):
        data = {
            "goal": "Commit and push changes",
            "requires_tools": True,
            "success_criteria": ["Remote contains the commit"],
            "steps": ["Inspect repository", "Create commit message", "Commit", "Push", "Verify"],
            "risk": "consequential",
            "missing_information": [],
        }
        response = SimpleNamespace(output_text=json.dumps(data))
        client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response))
        with TemporaryDirectory() as runtime, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": runtime}):
            engine = TaskEngine()
            plan = engine.plan(client, "model", "low", "Commit and push")
            self.assertEqual(plan.steps[0], "Inspect repository")
            self.assertTrue((Path(runtime) / "active-task.json").exists())

    def test_tool_journal_records_only_bounded_evidence(self):
        with TemporaryDirectory() as runtime, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": runtime}):
            engine = TaskEngine()
            # Use a real plan record by falling back through an unavailable client.
            engine.plan(SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(Exception()))), "m", "low", "Do task")
            engine.record_tool("example", {"ok": False, "error": "failed", "secret": "do-not-store"})
            saved = (Path(runtime) / "active-task.json").read_text()
            self.assertIn("failed", saved)
            self.assertNotIn("do-not-store", saved)


if __name__ == "__main__":
    unittest.main()
