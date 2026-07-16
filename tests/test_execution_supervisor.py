import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import execution_supervisor
from agent_platform import AgentPlatform


class ExecutionSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.runtime_patches = [
            patch.object(execution_supervisor, "RUNTIME", root),
            patch.object(execution_supervisor, "CANCEL_FILE", root / "cancel-current-task"),
            patch.object(execution_supervisor, "LATEST_FILE", root / "execution-state.json"),
        ]
        for item in self.runtime_patches:
            item.start()
            self.addCleanup(item.stop)
        self.platform = Mock()
        self.platform.risk_for.return_value = "read_only"
        self.platform.begin_execution_checkpoint.return_value = {"ok": True}
        self.platform.finish_execution_checkpoint.return_value = {"ok": True}
        self.platform.verified_execution.return_value = None
        self.platform.tool_failure_window.return_value = {"failures": 0}

    def test_success_is_checkpointed_and_verified(self):
        with (
            patch("execution_supervisor.platform", return_value=self.platform),
            patch("execution_supervisor.snapshot", return_value={"frontmost_application": "Safari", "target_running": True}),
        ):
            result = execution_supervisor.execute(
                "open_application", {"name": "Safari"},
                lambda: {"ok": True, "frontmost": True}, task_id="task", request_id="request",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["_supervision"]["verified"])
        self.platform.begin_execution_checkpoint.assert_called_once()
        self.platform.finish_execution_checkpoint.assert_called_once()

    def test_safe_tool_retries_when_observable_contract_is_not_met(self):
        handler = Mock(side_effect=[
            {"ok": True, "frontmost": False},
            {"ok": True, "frontmost": True},
        ])
        with (
            patch("execution_supervisor.platform", return_value=self.platform),
            patch("execution_supervisor.snapshot", return_value={"target_running": True}),
            patch("execution_supervisor.time.sleep"),
        ):
            result = execution_supervisor.execute("open_application", {"name": "Safari"}, handler)
        self.assertTrue(result["ok"])
        self.assertEqual(result["_supervision"]["attempts"], 2)

    def test_consequential_tool_is_never_automatically_repeated(self):
        self.platform.risk_for.return_value = "consequential"
        handler = Mock(return_value={"ok": False, "retryable": True, "error": "failed"})
        with (
            patch("execution_supervisor.platform", return_value=self.platform),
            patch("execution_supervisor.snapshot", return_value={}),
        ):
            result = execution_supervisor.execute("git_commit", {"repository": "Jarvis"}, handler)
        self.assertFalse(result["ok"])
        handler.assert_called_once()

    def test_cancellation_stops_before_action(self):
        execution_supervisor.request_cancel(source="test")
        handler = Mock(return_value={"ok": True})
        result = execution_supervisor.execute("open_application", {"name": "Safari"}, handler)
        self.assertTrue(result["cancelled"])
        handler.assert_not_called()

    def test_partial_window_layout_failure_restores_checkpointed_frames(self):
        with (
            patch("execution_supervisor.platform", return_value=self.platform),
            patch("execution_supervisor.snapshot", return_value={}),
            patch("desktop.restore_windows", return_value={"ok": True, "restored": ["Safari"]}) as restore,
        ):
            result = execution_supervisor.execute(
                "desktop_window_arrange", {"applications": ["Safari"], "confirmed": True},
                lambda: {"ok": False, "error": "placement failed"},
            )
        self.assertTrue(result["_rollback"]["ok"])
        restore.assert_called_once_with(applications=["Safari"], confirmed=True)

    def test_checkpoint_journal_round_trip(self):
        database = Path(self.temp.name) / "agent.db"
        store = AgentPlatform(database)
        store.begin_execution_checkpoint("c1", "t1", "r1", "open_application", "read_only", {"name": "Safari"}, {"frontmost": "Finder"})
        store.finish_execution_checkpoint("c1", "verified", {"frontmost": "Safari"}, 1)
        records = store.recent_execution_checkpoints("t1")["checkpoints"]
        self.assertEqual(records[0]["status"], "verified")
        self.assertEqual(records[0]["attempts"], 1)

    def test_large_blender_checkpoint_keeps_valid_compact_json(self):
        database = Path(self.temp.name) / "large-agent.db"
        store = AgentPlatform(database)
        components = [
            {"name": f"Part {index}", "operation": "mesh", "primitive": "none", "collection": "Assembly",
             "location": [0, 0, 0], "rotation": [0, 0, 0], "array_count": 1,
             "vertices": [[0, 0, 0]] * 200, "faces": [[0, 0, 0]] * 200}
            for index in range(80)
        ]
        store.begin_execution_checkpoint(
            "large", "task", "request", "blender_create_advanced_project", "consequential",
            {"project_name": "Rover", "components": components, "booleans": []}, {},
        )
        record = store.recent_execution_checkpoints("task")["checkpoints"][0]
        arguments = __import__("json").loads(record["arguments"])
        self.assertTrue(arguments["_full_arguments_omitted"])
        self.assertEqual(arguments["component_count"], 80)
        self.assertLessEqual(len(arguments["component_summary"]), 40)

    def test_running_process_is_terminated_when_stop_is_requested(self):
        timer = threading.Timer(0.15, lambda: execution_supervisor.request_cancel("worker", source="test"))
        timer.start()
        started = time.monotonic()
        try:
            result = execution_supervisor.run_cancellable_process(
                ["/bin/sleep", "5"], request_id="worker", timeout=10,
            )
        finally:
            timer.cancel()
            execution_supervisor.clear_cancel()
        self.assertTrue(result["cancelled"])
        self.assertLess(time.monotonic() - started, 2)

    def test_running_process_relays_progress_while_alive(self):
        callback = Mock()
        result = execution_supervisor.run_cancellable_process(
            ["/bin/sleep", "0.35"], timeout=2, progress_callback=callback,
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(callback.call_count, 1)

    def test_verified_consequential_action_is_not_repeated_in_same_request(self):
        self.platform.risk_for.return_value = "consequential"
        self.platform.verified_execution.return_value = {"id": "prior"}
        handler = Mock(return_value={"ok": True})
        with patch("execution_supervisor.platform", return_value=self.platform):
            result = execution_supervisor.execute(
                "git_push", {"repository": "Jarvis", "confirmed": True}, handler,
                request_id="request",
            )
        self.assertTrue(result["duplicate_prevented"])
        handler.assert_not_called()

    def test_repeated_tool_failure_opens_local_circuit(self):
        self.platform.tool_failure_window.return_value = {
            "failures": 3, "latest_error_code": "timeout", "cooldown_seconds": 120,
        }
        handler = Mock(return_value={"ok": True})
        with patch("execution_supervisor.platform", return_value=self.platform):
            result = execution_supervisor.execute("open_search", {"query": "news"}, handler)
        self.assertEqual(result["error_code"], "tool_circuit_open")
        self.assertTrue(result["alternative_route_required"])
        handler.assert_not_called()

    def test_quality_feedback_does_not_open_adapter_circuit(self):
        self.platform.tool_failure_window.return_value = {
            "failures": 3, "latest_error_code": "design_quality_gate_failed", "cooldown_seconds": 120,
        }
        handler = Mock(return_value={
            "ok": False, "resumable": True, "error_code": "design_quality_gate_failed",
            "error": "Correct the saved specification",
        })
        with (
            patch("execution_supervisor.platform", return_value=self.platform),
            patch("execution_supervisor.snapshot", return_value={}),
        ):
            result = execution_supervisor.execute("blender_revise_advanced_project", {}, handler)
        self.assertEqual(result["error_code"], "design_quality_gate_failed")
        handler.assert_called_once()


if __name__ == "__main__":
    unittest.main()
