import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import activity


class ActivityTests(unittest.TestCase):
    def test_chat_is_bounded_and_reset_with_ui(self):
        with TemporaryDirectory() as folder:
            runtime = Path(folder)
            with patch.object(activity, "RUNTIME", runtime), patch.object(
                activity, "CHAT_FILE", runtime / "chat.json"
            ), patch.object(activity, "STATE_FILE", runtime / "activity.json"), patch.object(
                activity, "ACTION_FILE", runtime / "actions.json"
            ), patch.object(activity, "PLAN_FILE", runtime / "ui-plan.json"
            ), patch.object(activity, "BACKGROUND_TASK_FILE", runtime / "background-task.json"), patch.object(
                activity, "SESSION_UI_FILE", runtime / "session-ui-active"
            ), patch.object(
                activity, "TEXT_COMMAND_DIR", runtime / "text-commands"
            ):
                for index in range(15):
                    activity.append_chat("user", f"message {index}")
                messages = json.loads((runtime / "chat.json").read_text())
                self.assertEqual(len(messages), 12)
                activity.reset_ui()
                self.assertEqual(json.loads((runtime / "chat.json").read_text()), [])

    def test_typed_command_queue_is_ordered_and_consumed_atomically(self):
        with TemporaryDirectory() as folder:
            queue = Path(folder) / "text-commands"
            queue.mkdir()
            with patch.object(activity, "TEXT_COMMAND_DIR", queue):
                (queue / "a.json").write_text(json.dumps({"text": "first command"}))
                (queue / "b.json").write_text(json.dumps({"text": "second command"}))
                self.assertTrue(activity.text_command_pending())
                self.assertEqual(activity.take_text_command(), "first command")
                self.assertEqual(activity.take_text_command(), "second command")
                self.assertFalse(activity.text_command_pending())

    def test_clearing_session_discards_unprocessed_typed_commands(self):
        with TemporaryDirectory() as folder:
            queue = Path(folder) / "text-commands"
            queue.mkdir()
            (queue / "pending.json").write_text(json.dumps({"text": "later"}))
            with patch.object(activity, "TEXT_COMMAND_DIR", queue):
                activity.clear_text_commands()
                self.assertFalse(activity.text_command_pending())

    def test_session_hud_has_an_explicit_lifecycle(self):
        with TemporaryDirectory() as folder:
            runtime = Path(folder)
            flag = runtime / "session-ui-active"
            with patch.object(activity, "RUNTIME", runtime), patch.object(activity, "SESSION_UI_FILE", flag):
                activity.begin_session_ui()
                self.assertTrue(flag.exists())
                activity.end_session_ui()
                self.assertFalse(flag.exists())

    def test_background_task_preserves_elapsed_start_and_advances_stage(self):
        with TemporaryDirectory() as folder:
            runtime = Path(folder)
            background = runtime / "background-task.json"
            with patch.object(activity, "RUNTIME", runtime), patch.object(activity, "BACKGROUND_TASK_FILE", background):
                activity.update_background_task("job-1", "INSTALLING BLENDER", "Preparing", step=1)
                first = json.loads(background.read_text())
                activity.update_background_task("job-1", "INSTALLING BLENDER", "Installing", step=3)
                second = json.loads(background.read_text())
            self.assertEqual(first["started"], second["started"])
            self.assertEqual(second["step"], 3)
            self.assertEqual(second["phase"], "Installing")

    def test_action_description_does_not_expose_typed_text(self):
        label, target = activity.describe_tool(
            "desktop_action", {"action": "type", "text": "private contents", "x": 0, "y": 0}
        )
        self.assertEqual(label, "CONTROL DESKTOP")
        self.assertEqual(target, "type")
        self.assertNotIn("private", target)


if __name__ == "__main__":
    unittest.main()
