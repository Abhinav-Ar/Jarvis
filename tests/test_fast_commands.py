import unittest
from unittest.mock import patch

import fast_commands


class FastCommandTests(unittest.TestCase):
    @patch("app_installer.status_summary", return_value="Blender is installed and verified.")
    def test_installation_status_never_starts_another_install(self, status):
        self.assertEqual(fast_commands.execute("Is a Blender installed yet?"), "Blender is installed and verified.")
        status.assert_called_once_with("blender")

    @patch("activity.record_step")
    @patch("activity.update")
    @patch("activity.set_execution_path")
    @patch("desktop.arrange_windows", return_value={"ok": True})
    @patch("fast_commands.mac_tools.application_exists", return_value=True)
    def test_two_app_workspace_bypasses_model(self, exists, arrange, plan, update, record):
        answer = fast_commands.execute(
            "Open GitHub Desktop and Visual Studio Code, then arrange them so I can work in both"
        )
        self.assertEqual(answer, "GitHub Desktop and Visual Studio Code are arranged in a balanced side-by-side workspace.")
        arrange.assert_called_once_with(["GitHub Desktop", "Visual Studio Code"], confirmed=True)

    @patch("activity.record_step")
    @patch("activity.update")
    @patch("activity.set_execution_path")
    @patch("desktop.arrange_windows", return_value={"ok": True})
    @patch("fast_commands.mac_tools.application_exists", return_value=True)
    def test_balanced_workspace_wording_is_one_paired_operation(self, exists, arrange, plan, update, record):
        answer = fast_commands.execute(
            "Open GitHub Desktop and Visual Studio Code and create a balanced workspace"
        )
        self.assertIn("balanced", answer)
        arrange.assert_called_once_with(["GitHub Desktop", "Visual Studio Code"], confirmed=True)

    @patch("fast_commands._stage")
    @patch("fast_commands.mac_tools.application_exists", return_value=True)
    @patch("fast_commands.mac_tools.open_application", return_value={"ok": True})
    def test_open_known_app_bypasses_model(self, opened, exists, stage):
        self.assertEqual(fast_commands.execute("Hey, open Safari"), "Safari is open.")
        opened.assert_called_once_with("Safari")
        stage.assert_called_once_with("Safari")

    @patch("fast_commands.mac_tools.quit_application", return_value={"ok": True})
    def test_close_app_bypasses_model(self, closed):
        self.assertEqual(fast_commands.execute("Close Safari"), "Safari is closed.")
        closed.assert_called_once_with("Safari")

    @patch("fast_commands._stage")
    @patch("fast_commands.mac_tools.application_exists", return_value=True)
    @patch("fast_commands.mac_tools.open_application", return_value={"ok": True})
    def test_app_aliases_are_canonical(self, opened, exists, stage):
        self.assertEqual(fast_commands.execute("Open Chrome"), "Google Chrome is open.")
        opened.assert_called_once_with("Google Chrome")

    def test_multistep_request_does_not_take_fast_lane(self):
        self.assertIsNone(fast_commands.execute("Open Safari and then go to Google"))

    @patch("fast_commands._stage")
    @patch("fast_commands.mac_tools.open_url", return_value={"ok": True, "url": "https://google.com"})
    def test_direct_website_navigation_bypasses_model(self, opened, stage):
        self.assertEqual(fast_commands.execute("Go to google.com"), "google.com is open in Safari.")
        opened.assert_called_once_with("google.com", "Safari")
        stage.assert_called_once_with("Safari")

    @patch("spot.play_playlist", return_value={"ok": True, "name": "UG"})
    def test_named_playlist_bypasses_model(self, played):
        self.assertEqual(fast_commands.execute("Play my playlist named UG on Spotify"), "Playing UG.")
        played.assert_called_once_with("ug")

    @patch("fast_commands.mac_tools.set_system_volume")
    def test_volume_is_bounded(self, volume):
        self.assertEqual(fast_commands.execute("Set volume to 150"), "Volume set to 100 percent.")
        volume.assert_called_once_with(100)

    @patch("project_workflow.start", return_value={"ok": True, "repository": "Jarvis", "branch": "main"})
    def test_start_project_session_bypasses_model(self, start):
        self.assertEqual(
            fast_commands.execute("Start project Jarvis"),
            "Started the Jarvis project session on main.",
        )
        start.assert_called_once_with("jarvis")

    @patch("project_workflow.close", return_value={"ok": True, "repository": "Jarvis", "warning": "Uncommitted work remains."})
    def test_close_project_session_bypasses_model(self, close):
        self.assertEqual(
            fast_commands.execute("End project session"),
            "Closed the Jarvis project session. Uncommitted work remains.",
        )

    @patch("project_workflow.close_workspace", return_value={
        "ok": True,
        "repository": "Jarvis",
        "closed_applications": ["GitHub Desktop", "Visual Studio Code"],
        "warning": "Uncommitted work remains.",
    })
    def test_close_named_project_workspace_preserves_project_name(self, close_workspace):
        self.assertEqual(
            fast_commands.execute("Close everything on my laptop related to the Jarvis project"),
            "Closed GitHub Desktop, Visual Studio Code for the Jarvis project. Uncommitted work remains.",
        )
        close_workspace.assert_called_once_with("jarvis")


if __name__ == "__main__":
    unittest.main()
