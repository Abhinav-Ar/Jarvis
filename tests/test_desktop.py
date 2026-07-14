import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import desktop


class DesktopSafetyTests(unittest.TestCase):
    @patch("desktop._helper_json", return_value={
        "ok": True, "display_id": 1,
        "original": {"x": 0, "y": 0, "width": 1000, "height": 700},
    })
    @patch("desktop.mac_tools.open_application", return_value={"ok": True})
    def test_two_app_workspace_is_tiled_on_one_display(self, opened, helper):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            control = root / "enabled"; control.touch()
            with patch.object(desktop, "CONTROL_FLAG", control), patch.object(
                desktop, "WINDOW_STATE_FILE", root / "windows.json"
            ):
                result = desktop.arrange_windows(["Safari", "Notes"], confirmed=True)
        self.assertTrue(result["ok"])
        layouts = [call.args[0] for call in helper.call_args_list if call.args[0][0] == "window-layout"]
        self.assertEqual(layouts[0][2], "tile-left")
        self.assertEqual(layouts[1][2], "tile-right")
        self.assertEqual(layouts[1][-1], "1")

    def test_window_arrangement_requires_confirmation(self):
        with TemporaryDirectory() as folder:
            control = Path(folder) / "enabled"; control.touch()
            with patch.object(desktop, "CONTROL_FLAG", control):
                result = desktop.arrange_windows(["Safari"], confirmed=False)
        self.assertTrue(result["confirmation_required"])

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

    @patch("desktop.CONTROL_FLAG")
    def test_accessibility_fill_rejects_sensitive_fields(self, control_flag):
        control_flag.exists.return_value = True
        result = desktop.accessibility_set("Safari", "Password", "not-allowed", confirmed=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "sensitive_field")

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
