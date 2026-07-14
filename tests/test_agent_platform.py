import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_platform import AgentPlatform


class AgentPlatformTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.agent = AgentPlatform(Path(self.directory.name) / "agent.db")

    def tearDown(self):
        self.directory.cleanup()

    def test_memory_is_durable_searchable_and_deletable(self):
        self.assertTrue(self.agent.remember("music preference", "prefers recent alternative music")["ok"])
        self.assertEqual(self.agent.search_memory("alternative")["matches"][0]["key"], "music preference")
        self.assertTrue(self.agent.forget("music preference")["deleted"])

    def test_indexing_requires_explicit_roots(self):
        root = Path(self.directory.name) / "authorized"
        root.mkdir()
        (root / "project.md").write_text("Jarvis persistent native agent", encoding="utf-8")
        result = self.agent.index_paths([root])
        self.assertEqual(result["indexed"], 1)
        self.assertEqual(self.agent.search_documents("persistent")["matches"][0]["title"], "project.md")

    @patch.dict("os.environ", {"JARVIS_MAX_CLOUD_CALLS_PER_DAY": "0"})
    def test_cloud_budget_can_hard_stop_calls(self):
        allowed, reason = self.agent.cloud_allowed()
        self.assertFalse(allowed)
        self.assertIn("limit", reason.lower())

    def test_workflows_and_jobs_persist(self):
        self.assertTrue(self.agent.save_workflow("morning", [{"tool": "agent_status"}])["ok"])
        self.assertEqual(self.agent.queue_job("morning", {})["status"], "queued")
        self.assertEqual(self.agent.summary()["queued_jobs"], 1)

    def test_project_session_lifecycle_is_durable(self):
        started = self.agent.start_project_session(
            "Jarvis", "/tmp/Jarvis", "main", "abc123", {"changed_files": []}
        )
        self.assertEqual(self.agent.active_project_session()["session"]["repository"], "Jarvis")
        closed = self.agent.close_project_session(
            started["session_id"], "def456", {"changed_files": ["M app.py"]}, "Implemented feature"
        )
        self.assertTrue(closed["ok"])
        self.assertIsNone(self.agent.active_project_session()["session"])

    def test_task_failures_remain_searchable_after_later_tasks(self):
        self.agent.begin_task("first", "push Jarvis", "Push Jarvis", "git")
        self.agent.record_task_event(
            "first", 1, "push", "failed", "GitHub denied access",
            {"error_code": "remote_permission_denied"},
        )
        self.agent.finish_task("first", "needs_input", "GitHub rejected the push", "remote_permission_denied")
        self.agent.begin_task("second", "open Safari", "Open Safari", "direct")
        self.agent.finish_task("second", "completed", "Safari opened")
        history = self.agent.recent_tasks(limit=5)["tasks"]
        self.assertEqual([task["id"] for task in history[:2]], ["second", "first"])
        failed = next(task for task in history if task["id"] == "first")
        self.assertEqual(failed["error_code"], "remote_permission_denied")
        self.assertEqual(failed["events"][0]["action"], "push")


if __name__ == "__main__":
    unittest.main()
