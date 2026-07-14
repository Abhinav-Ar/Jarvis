import unittest
from unittest.mock import patch

import mac_tools


class MacToolTests(unittest.TestCase):
    @patch("mac_tools._apple", return_value="frontmost")
    @patch("mac_tools.subprocess.run")
    def test_open_application_reports_foreground_state(self, run, apple):
        result = mac_tools.open_application("Safari")
        self.assertTrue(result["ok"])
        self.assertTrue(result["frontmost"])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], ["/usr/bin/open", "-a", "Safari"])
        apple.assert_called_once()

    @patch("mac_tools.time.sleep")
    @patch("mac_tools._apple", side_effect=["0", "false", "frontmost"])
    @patch("mac_tools.subprocess.run")
    def test_github_desktop_without_window_is_relaunched(self, run, apple, sleep):
        result = mac_tools.open_application("GitHub Desktop")
        self.assertTrue(result["frontmost"])
        self.assertEqual(run.call_count, 4)
        self.assertIn("quit()", run.call_args_list[2].args[0][4])
        self.assertEqual(run.call_args_list[3].args[0], ["/usr/bin/open", "-a", "GitHub Desktop"])

    @patch("mac_tools.open_application", return_value={"ok": True, "frontmost": True})
    @patch("mac_tools.subprocess.run")
    def test_open_url_adds_https_and_activates_browser(self, run, activate):
        result = mac_tools.open_url("www.google.com", "Safari")
        self.assertEqual(result["url"], "https://www.google.com")
        self.assertTrue(result["frontmost"])
        run.assert_called_once_with(
            ["/usr/bin/open", "-a", "Safari", "https://www.google.com"],
            check=True,
            timeout=20,
        )
        activate.assert_called_once_with("Safari")

    def test_open_url_rejects_non_web_schemes(self):
        result = mac_tools.open_url("file:///etc/passwd", "Safari")
        self.assertFalse(result["ok"])

    @patch("mac_tools._apple", return_value="closed")
    @patch("mac_tools._run", return_value="requested")
    def test_quit_application_requests_normal_quit_and_verifies_exit(self, run, apple):
        result = mac_tools.quit_application("Safari")
        self.assertTrue(result["ok"])
        self.assertTrue(result["closed"])
        self.assertIn("Application(argv[0]).quit()", run.call_args.args[0][4])
        apple.assert_called_once()

    @patch("mac_tools._apple", return_value="still_running")
    @patch("mac_tools._run", return_value="requested")
    def test_quit_application_does_not_claim_unsaved_app_closed(self, run, apple):
        result = mac_tools.quit_application("Pages")
        self.assertFalse(result["ok"])
        self.assertIn("unsaved-changes", result["error"])


if __name__ == "__main__":
    unittest.main()
