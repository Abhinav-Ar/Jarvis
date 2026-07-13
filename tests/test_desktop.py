import unittest
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


if __name__ == "__main__":
    unittest.main()
