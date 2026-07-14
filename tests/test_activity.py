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
            ):
                for index in range(15):
                    activity.append_chat("user", f"message {index}")
                messages = json.loads((runtime / "chat.json").read_text())
                self.assertEqual(len(messages), 12)
                activity.reset_ui()
                self.assertEqual(json.loads((runtime / "chat.json").read_text()), [])

    def test_action_description_does_not_expose_typed_text(self):
        label, target = activity.describe_tool(
            "desktop_action", {"action": "type", "text": "private contents", "x": 0, "y": 0}
        )
        self.assertEqual(label, "CONTROL DESKTOP")
        self.assertEqual(target, "type")
        self.assertNotIn("private", target)


if __name__ == "__main__":
    unittest.main()
