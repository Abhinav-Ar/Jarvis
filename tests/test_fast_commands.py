import unittest
from unittest.mock import patch

import fast_commands


class FastCommandTests(unittest.TestCase):
    @patch("fast_commands.mac_tools.open_application", return_value={"ok": True})
    def test_open_known_app_bypasses_model(self, opened):
        self.assertEqual(fast_commands.execute("Hey, open Safari"), "Safari is open.")
        opened.assert_called_once_with("Safari")

    def test_multistep_request_does_not_take_fast_lane(self):
        self.assertIsNone(fast_commands.execute("Open Safari and then go to Google"))

    @patch("fast_commands.mac_tools.set_system_volume")
    def test_volume_is_bounded(self, volume):
        self.assertEqual(fast_commands.execute("Set volume to 150"), "Volume set to 100 percent.")
        volume.assert_called_once_with(100)


if __name__ == "__main__":
    unittest.main()
