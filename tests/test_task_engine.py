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
            self.assertIn("Resolve the intended application", plan.steps[0])
            self.assertIn("Verify the application", plan.steps[-1])

    def test_informational_how_to_request_does_not_require_action(self):
        self.assertFalse(TaskEngine.action_requested("How do I install Blender?"))
        self.assertTrue(TaskEngine.action_requested("Install Blender on my laptop"))
        self.assertTrue(TaskEngine.action_requested("Yes, edit the current rover"))
        self.assertTrue(TaskEngine.action_requested("Okay, do this in my Blender project"))
        self.assertTrue(TaskEngine.action_requested("Sure, do all of that that you just told me"))
        self.assertTrue(TaskEngine.action_requested(
            "Inspect and improve my currently open Blender project as an existing engineering assembly. "
            "Develop a repair strategy, then enact it immediately in the existing project."
        ))
        self.assertTrue(TaskEngine.action_requested(
            "Can we address that and actually bind the objects together structurally?"
        ))
        self.assertTrue(TaskEngine.action_requested(
            "Load the rover file and make all the changes you described before."
        ))
        self.assertTrue(TaskEngine.action_requested(
            "I'm telling you to display the rover file, please."
        ))
        self.assertTrue(TaskEngine.action_requested(
            "I want you to design clamps for my LEGO model."
        ))
        self.assertFalse(TaskEngine.action_requested("Did you open the edited file?"))

    def test_compound_blender_edit_overrides_incorrect_read_only_cloud_plan(self):
        data = {
            "goal": "Inspect and improve the existing Blender assembly",
            "requires_tools": False,
            "success_criteria": ["The edited file is verified"],
            "steps": ["Inspect the file", "Improve the assembly", "Save and verify"],
            "risk": "read_only",
            "missing_information": [],
        }
        response = SimpleNamespace(output_text=json.dumps(data))
        client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response))
        with TemporaryDirectory() as runtime, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": runtime}):
            engine = TaskEngine()
            plan = engine.plan(
                client, "model", "low",
                "Inspect and improve my currently open Blender project as an existing engineering assembly.",
            )
        self.assertTrue(plan.requires_tools)
        self.assertEqual(plan.risk, "consequential")

    def test_planner_mutation_steps_override_surface_level_diagnostic_wording(self):
        data = {
            "goal": "Resolve the visible Blender state mismatch",
            "requires_tools": True,
            "success_criteria": ["The correct rover file is displayed"],
            "steps": ["Inspect the active scene", "Switch to the correct rover file", "Verify it is visible"],
            "risk": "read_only",
            "missing_information": [],
        }
        response = SimpleNamespace(output_text=json.dumps(data))
        client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response))
        with TemporaryDirectory() as runtime, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": runtime}):
            engine = TaskEngine()
            plan = engine.plan(client, "model", "low", "The Blender screen is not showing the rover file.")
        self.assertTrue(engine.mutation_requested)
        self.assertTrue(plan.requires_tools)
        self.assertEqual(plan.risk, "consequential")

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
            self.assertIn("intended repository", plan.steps[0])
            self.assertIn("Inspect repository", plan.steps)
            self.assertTrue((Path(runtime) / "active-task.json").exists())

    def test_local_anticipation_adds_domain_completion_contract_without_cloud(self):
        with TemporaryDirectory() as runtime, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": runtime}):
            engine = TaskEngine()
            client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: None))
            plan = engine.plan(client, "model", "low", "Install Blender")
            self.assertIn("Check whether the requested application is already installed", plan.steps)
            self.assertIn("Verify the installed application exists and can launch", plan.steps)
            self.assertTrue(any("merely downloaded" in item for item in plan.success_criteria))

    def test_tool_journal_records_only_bounded_evidence(self):
        with TemporaryDirectory() as runtime, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": runtime}):
            engine = TaskEngine()
            # Use a real plan record by falling back through an unavailable client.
            engine.plan(SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(Exception()))), "m", "low", "Do task")
            engine.record_tool("example", {"ok": False, "error": "failed", "secret": "do-not-store"})
            saved = (Path(runtime) / "active-task.json").read_text()
            self.assertIn("failed", saved)
            self.assertNotIn("do-not-store", saved)

    def test_detailed_existing_project_plan_is_not_duplicated_and_tracks_focus(self):
        data = {
            "goal": "Repair existing rover", "requires_tools": True,
            "success_criteria": ["Saved project passes review"],
            "steps": ["Load the saved project", "Inspect stored failures", "Patch failed components", "Render", "Verify", "Open project"],
            "risk": "consequential", "missing_information": [],
        }
        response = SimpleNamespace(output_text=json.dumps(data))
        client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response))
        with TemporaryDirectory() as runtime, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": runtime}):
            engine = TaskEngine()
            plan = engine.plan(client, "model", "low", "Fix the existing Blender rover")
            self.assertEqual(plan.steps, data["steps"])
            engine.record_tool("blender_revise_advanced_project", {"ok": False, "error": "needs axle"})
            saved = json.loads((Path(runtime) / "active-task.json").read_text())
            self.assertEqual(saved["current_step"], 2)

    def test_resumable_native_failure_persists_compact_recovery_state(self):
        with TemporaryDirectory() as runtime, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": runtime}):
            engine = TaskEngine()
            engine.plan(
                SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(Exception()))),
                "m", "low", "Build a Blender mount",
            )
            engine.record_tool("blender_create_advanced_project", {
                "ok": False, "resumable": True, "recovery_state": "preflight_repair",
                "application": "Blender", "project": "Mount", "draft_path": "/tmp/draft.json",
                "design_brief_id": "abc123", "specification_hash": "hash1",
                "validation_issue_records": [{"code": "scale", "message": "Correct the scale"}],
            })
            saved = json.loads((Path(runtime) / "active-task.json").read_text())
            self.assertEqual(saved["recovery"]["state"], "preflight_repair")
            self.assertEqual(saved["recovery"]["specification_hash"], "hash1")
            self.assertIn("Correct the scale", engine.recovery_summary())

    def test_read_only_blender_question_drops_inherited_build_steps(self):
        data = {
            "goal": "Explain the rover hierarchy", "requires_tools": True,
            "success_criteria": ["Hierarchy inspected", "The result is an editable native artifact rather than a blockout"],
            "steps": ["Inspect the Blender Outliner", "Explain the hierarchy", "Build the selected concept", "Render the project"],
            "risk": "read_only", "missing_information": [],
        }
        response = SimpleNamespace(output_text=json.dumps(data))
        client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response))
        with TemporaryDirectory() as runtime, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": runtime}):
            plan = TaskEngine().plan(client, "model", "low", "Why are the Blender rover collections separate?")
            self.assertTrue(plan.requires_tools)
            self.assertEqual(plan.risk, "read_only")
            self.assertEqual(plan.steps, ["Inspect the Blender Outliner", "Explain the hierarchy"])
            self.assertEqual(plan.success_criteria, ["Hierarchy inspected"])


if __name__ == "__main__":
    unittest.main()
