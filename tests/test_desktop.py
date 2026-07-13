import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import desktop


class DesktopSafetyTests(unittest.TestCase):
    @patch("desktop.CONTROL_FLAG")
    def test_actions_are_blocked_when_menu_toggle_is_off(self, control_flag):
        control_flag.exists.return_value = False
        result = desktop.perform_action("click", 10, 10, "", "escape", 0, False)
        self.assertFalse(result["ok"])

    @patch("desktop.HELPER")
    @patch("desktop.CONTROL_FLAG")
    def test_typing_requires_confirmation(self, control_flag, helper):
        control_flag.exists.return_value = True
        helper.exists.return_value = True
        result = desktop.perform_action("type", 0, 0, "hello", "escape", 0, False)
        self.assertTrue(result["confirmation_required"])

    def test_click_outside_locked_application_display_is_rejected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            control = root / "enabled"
            helper = root / "helper"
            target = root / "target.json"
            control.touch(); helper.touch()
            target.write_text(json.dumps({
                "application": "GitHub Desktop",
                "display": {"global_x": 0, "global_y": 0, "global_width": 1440, "global_height": 900},
            }))
            with patch.object(desktop, "CONTROL_FLAG", control), patch.object(
                desktop, "HELPER", helper
            ), patch.object(desktop, "TARGET_FILE", target):
                result = desktop.perform_action("click", -3278, 18, "", "escape", 0, False)
            self.assertFalse(result["ok"])
            self.assertIn("outside", result["error"])


if __name__ == "__main__":
    unittest.main()
