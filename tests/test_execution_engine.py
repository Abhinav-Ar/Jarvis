import unittest
from unittest.mock import Mock, patch

import execution_engine


class ExecutionEngineTests(unittest.TestCase):
    def setUp(self):
        self.platform = Mock()
        self.platform.active_project_session.return_value = {"session": None}
        self.platform.recent_tasks.return_value = {"tasks": []}
        for target in ("execution_engine.activity.record_step", "execution_engine.activity.set_execution_path"):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    @patch("execution_engine.activity.update")
    @patch("execution_engine.activity.announce")
    @patch("execution_engine.desktop.arrange_windows", return_value={"ok": True})
    @patch("execution_engine.mac_tools.open_application", return_value={"ok": True, "frontmost": True})
    @patch("execution_engine.git_tools.sync_status", return_value={"ok": True, "ahead": 0, "working_tree_clean": True})
    @patch("execution_engine.git_tools.commit_and_push", return_value={"ok": True, "repository": "Jarvis", "pushed": True})
    @patch("execution_engine.git_tools.generate_commit_message", return_value="Update assistant logic and tests")
    @patch("execution_engine.git_tools.status", return_value={"ok": True, "has_changes": True, "changed_files": [" M assist.py"]})
    @patch("execution_engine._infer_repository", return_value={"ok": True, "repository": "Jarvis", "source": "request"})
    def test_known_commit_push_runs_complete_local_workflow(
        self, infer, status, message, commit_push, sync, opened, arranged, announce, update,
    ):
        with patch("execution_engine.platform", return_value=self.platform):
            result = execution_engine.run_git_workflow(
                "Go to GitHub Desktop and commit and push my Jarvis changes"
            )
        self.assertTrue(result["ok"])
        self.assertIn("verified", result["summary"])
        commit_push.assert_called_once_with("Jarvis", "Update assistant logic and tests", True)
        self.platform.finish_task.assert_called_once()

    @patch("execution_engine.activity.update")
    @patch("execution_engine.activity.announce")
    @patch("execution_engine.desktop.arrange_windows", return_value={"ok": True})
    @patch("execution_engine._github_desktop_push", return_value={"ok": True, "pushed": True, "verified_up_to_date": True})
    @patch("execution_engine.mac_tools.open_application", return_value={"ok": True, "frontmost": True})
    @patch("execution_engine.git_tools.sync_status", return_value={"ok": True, "ahead": 0, "working_tree_clean": True})
    @patch("execution_engine.git_tools.commit_and_push", return_value={
        "ok": False, "error_code": "remote_permission_denied", "requires_user": True,
        "committed": True, "error": "403",
    })
    @patch("execution_engine.git_tools.generate_commit_message", return_value="Update tests")
    @patch("execution_engine.git_tools.status", return_value={"ok": True, "has_changes": True, "changed_files": [" M test.py"]})
    @patch("execution_engine._infer_repository", return_value={"ok": True, "repository": "Jarvis", "source": "request"})
    def test_permission_failure_tries_desktop_authenticated_push_once(
        self, infer, status, message, commit_push, sync, opened, desktop_push, arranged, announce, update,
    ):
        with patch("execution_engine.platform", return_value=self.platform):
            result = execution_engine.run_git_workflow(
                "Use GitHub Desktop to commit and push Jarvis"
            )
        self.assertTrue(result["ok"])
        desktop_push.assert_called_once()

    def test_meta_question_does_not_trigger_git_action(self):
        self.assertIsNone(execution_engine.run_git_workflow("Describe the problem you found trying to commit"))

    @patch("execution_engine.desktop.arrange_windows", return_value={"ok": True})
    @patch("execution_engine.mac_tools.open_application", return_value={"ok": True, "frontmost": True})
    @patch("execution_engine.desktop.accessibility_snapshot", return_value={
        "ok": True, "elements": [{"value": "Abhinav", "enabled": True}],
    })
    @patch("execution_engine.desktop.accessibility_set", return_value={"ok": True})
    def test_labelled_form_fill_is_local_and_verified(self, set_field, inspect, opened, arranged):
        with patch("execution_engine.platform", return_value=self.platform):
            result = execution_engine.run_form_workflow(
                "Type Abhinav into the Name field in Safari"
            )
        self.assertTrue(result["ok"])
        set_field.assert_called_once_with("Safari", "Name", "Abhinav", confirmed=True)

    def test_prior_failure_is_reported_from_history(self):
        self.platform.recent_tasks.return_value = {"tasks": [{
            "status": "needs_input", "result_summary": "GitHub rejected the push",
            "error_code": "remote_permission_denied",
        }]}
        with patch("execution_engine.platform", return_value=self.platform):
            answer = execution_engine.recent_failure_summary("What problem did you run into?")
        self.assertIn("GitHub rejected the push", answer)


if __name__ == "__main__":
    unittest.main()
