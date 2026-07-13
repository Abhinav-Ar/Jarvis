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
            ), patch.object(activity, "STATE_FILE", runtime / "activity.json"):
                for index in range(15):
                    activity.append_chat("user", f"message {index}")
                messages = json.loads((runtime / "chat.json").read_text())
                self.assertEqual(len(messages), 12)
                activity.reset_ui()
                self.assertEqual(json.loads((runtime / "chat.json").read_text()), [])


if __name__ == "__main__":
    unittest.main()
