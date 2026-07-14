import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
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

    @patch("execution_engine.run_git_workflow")
    def test_repository_answer_resumes_pending_git_intent(self, run_workflow):
        run_workflow.return_value = {"ok": True, "summary": "Jarvis was committed and pushed."}
        with TemporaryDirectory() as folder, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": folder}):
            execution_engine._save_pending_git(
                "Commit and push my changes", ["FitnessGooner", "Jarvis"]
            )
            answer = execution_engine._resume_pending_git("for the Jarvis project")
            self.assertEqual(answer, "Jarvis was committed and pushed.")
            self.assertFalse((Path(folder) / "pending-intent.json").exists())
        run_workflow.assert_called_once_with(
            "Commit and push my changes for the Jarvis repository"
        )

    @patch("execution_engine.run_git_workflow")
    def test_repository_restatement_resumes_pending_git_intent(self, run_workflow):
        run_workflow.return_value = {"ok": True, "summary": "Jarvis was committed and pushed."}
        with TemporaryDirectory() as folder, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": folder}):
            execution_engine._save_pending_git(
                "Commit my changes and push on getup desktop", ["FitnessGooner", "Jarvis"]
            )
            answer = execution_engine._resume_pending_git("You should commit and push the Jarvis app")
        self.assertEqual(answer, "Jarvis was committed and pushed.")
        run_workflow.assert_called_once_with(
            "Commit my changes and push on getup desktop for the Jarvis repository"
        )

    @patch("execution_engine.run_git_workflow")
    def test_app_directly_resumes_last_git_operation_with_ui(self, run_workflow):
        run_workflow.return_value = {"ok": True, "summary": "Pushed through GitHub Desktop."}
        with TemporaryDirectory() as folder, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": folder}):
            execution_engine._save_last_git_context("Jarvis", "Commit and push my changes", True, True)
            answer = execution_engine._resume_recent_git_in_app("Can you do it from the app directly?")
        self.assertEqual(answer, "Pushed through GitHub Desktop.")
        self.assertIn("using GitHub Desktop UI directly", run_workflow.call_args.args[0])

    def test_push_my_changes_implies_commit_and_push(self):
        self.assertEqual(
            execution_engine._git_intent("Push my changes on GitHub Desktop"),
            (True, True),
        )

    @patch("execution_engine.git_tools.sync_status", return_value={
        "ok": True, "ahead": 0, "working_tree_clean": False,
    })
    @patch("execution_engine.git_tools.status", return_value={
        "ok": True, "changed_files": [" M one.py", " M two.py"], "has_changes": True,
    })
    def test_correction_verifies_recent_git_state_instead_of_promising(self, status, sync):
        with TemporaryDirectory() as folder, patch.dict("os.environ", {"JARVIS_RUNTIME_DIR": folder}):
            execution_engine._save_last_git_context("Jarvis", "Push my changes", True, True)
            answer = execution_engine._verify_recent_git_correction("No, it wasn't. I can see changes pending.")
        self.assertEqual(answer, "I checked Jarvis: 2 files are still uncommitted. Existing commits are synchronized.")


if __name__ == "__main__":
    unittest.main()
