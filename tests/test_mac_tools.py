import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import mac_tools


class MacToolTests(unittest.TestCase):
    def test_creative_and_cad_aliases_are_canonical(self):
        self.assertEqual(mac_tools.canonical_application_name("free cad"), "FreeCAD")
        self.assertEqual(mac_tools.canonical_application_name("open scad"), "OpenSCAD")
        self.assertEqual(mac_tools.canonical_application_name("da vinci"), "DaVinci Resolve")

    @patch("mac_tools.application_bundle_path", return_value=Path("/Applications/DaVinci Resolve/DaVinci Resolve.app"))
    @patch("mac_tools._apple", return_value="frontmost")
    @patch("mac_tools.subprocess.run")
    def test_registered_workspace_app_opens_by_explicit_bundle(self, run, apple, bundle):
        result = mac_tools.open_application("da vinci")
        self.assertTrue(result["frontmost"])
        self.assertEqual(run.call_args_list[0].args[0], ["/usr/bin/open", "/Applications/DaVinci Resolve/DaVinci Resolve.app"])
    @patch("mac_tools._apple", return_value="frontmost")
    @patch("mac_tools.subprocess.run")
    def test_open_application_reports_foreground_state(self, run, apple):
        result = mac_tools.open_application("Safari")
        self.assertTrue(result["ok"])
        self.assertTrue(result["frontmost"])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], ["/usr/bin/open", "-a", "Safari"])
        apple.assert_called_once()

    @patch("mac_tools.open_application", return_value={"ok": True, "frontmost": True})
    @patch("mac_tools.application_bundle_path", return_value=Path("/Applications/Blender.app"))
    @patch("mac_tools._apple", return_value="Neon Desk.blend - Blender")
    @patch("mac_tools.subprocess.run")
    def test_open_file_verifies_exact_document_window(self, run, apple, bundle, activate):
        with tempfile.TemporaryDirectory() as folder:
            scene = Path(folder) / "Neon Desk.blend"
            scene.write_bytes(b"BLENDER")
            result = mac_tools.open_file_in_application(scene, "Blender")
        self.assertTrue(result["ok"])
        self.assertTrue(result["loaded"])
        self.assertEqual(result["document"], "Neon Desk.blend")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/open", "-a", "/Applications/Blender.app", str(scene.resolve())])
        activate.assert_called_once_with("Blender")

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
