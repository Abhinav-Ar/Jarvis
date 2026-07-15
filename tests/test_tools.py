import unittest
from unittest.mock import patch

import tools
import integrations


class ToolTests(unittest.TestCase):
    def test_unknown_tool_is_rejected(self):
        result = tools.execute("erase_computer", {})
        self.assertFalse(result["ok"])

    def test_all_function_tools_have_handlers(self):
        function_names = {
            definition["name"]
            for definition in tools.TOOL_DEFINITIONS
            if definition["type"] == "function"
        }
        with patch.multiple(
            tools,
            get_weather=lambda **kwargs: {},
            open_search=lambda **kwargs: {},
            spotify_control=lambda **kwargs: {},
        ):
            handler_names = {
                "get_weather", "open_search", "spotify_control", "open_application", "browser_navigate",
                "quit_application",
                "set_system_volume", "clipboard", "system_status", "show_notification",
                "create_reminder", "create_note", "create_calendar_event",
                "todoist_create_task", "home_assistant_control", "create_email_draft",
                "find_contact", "find_files", "apple_shortcuts",
                "spotify_play_playlist", "spotify_create_discovery_playlist",
                "desktop_inspect", "desktop_action",
                "desktop_accessibility_inspect", "desktop_accessibility_set", "desktop_accessibility_press",
                "desktop_local_ocr",
                "desktop_window_arrange", "desktop_window_restore",
                "git_repositories", "git_status", "git_commit_and_push",
                "git_commit", "git_push",
                "agent_status", "task_history_search", "memory_store", "memory_search", "memory_forget",
                "local_knowledge_search",
                "project_session_start", "project_session_resume", "project_session_status",
                "project_session_close",
                "orion_goal_status", "orion_world_state", "orion_workflows", "orion_teach_workflow",
                "codex_generate", "generation_status", "generation_cancel",
                "capability_families_status", "objective_compile", "google_drive_search",
                "google_create_spreadsheet", "google_create_document", "google_create_presentation",
                "design_project_plan",
                "blender_create_project", "blender_refine_project", "blender_create_advanced_project", "freecad_create_project",
                "openscad_create_project", "resolve_create_project", "native_project_open",
                "install_application", "installation_status",
            }
        self.assertEqual(function_names, handler_names)

    def test_tool_selection_keeps_only_relevant_integrations(self):
        names = {definition["name"] for definition in tools.select_definitions("Play my UG Spotify playlist")}
        self.assertIn("spotify_play_playlist", names)
        self.assertNotIn("desktop_action", names)
        self.assertNotIn("git_commit", names)

    def test_general_conversation_sends_no_tools(self):
        self.assertEqual(tools.select_definitions("Tell me a short joke"), [])

    def test_native_project_request_selects_dedicated_worker(self):
        names = {definition.get("name", definition["type"]) for definition in tools.select_definitions("Create a parametric enclosure in FreeCAD")}
        self.assertIn("freecad_create_project", names)
        self.assertIn("openscad_create_project", names)

    def test_open_native_project_selects_exact_project_loader(self):
        names = {definition.get("name", definition["type"]) for definition in tools.select_definitions("Open my Neon Desk Blender project")}
        self.assertIn("native_project_open", names)

    def test_blender_followup_context_selects_refinement_worker(self):
        names = {definition.get("name", definition["type"]) for definition in tools.select_definitions(
            "Add a cyan strip around that desk. Active native project: Blender NeonDust32"
        )}
        self.assertIn("blender_refine_project", names)

    def test_complex_blender_scene_exposes_advanced_modeler(self):
        names = {definition.get("name", definition["type"]) for definition in tools.select_definitions(
            "Create a detailed Blender lunar outpost with a rover and satellite dishes"
        )}
        self.assertIn("blender_create_advanced_project", names)

    def test_inferred_objective_family_exposes_required_worker(self):
        names = {definition.get("name", definition["type"]) for definition in tools.select_definitions(
            "Build a printable enclosure for my sensor"
        )}
        self.assertIn("freecad_create_project", names)
        self.assertIn("design_project_plan", names)

    def test_install_request_selects_native_installer(self):
        names = {definition.get("name", definition["type"]) for definition in tools.select_definitions("Install Blender on my laptop")}
        self.assertIn("install_application", names)
        self.assertIn("installation_status", names)

    def test_read_only_tool_is_not_action_evidence(self):
        self.assertFalse(tools.is_action_evidence("find_files", {}, {"ok": True, "files": ["x"]}))
        self.assertTrue(tools.is_action_evidence("install_application", {}, {"ok": True, "status": "running"}))

    @patch("tools.app_installer.install", return_value={"ok": True, "status": "running"})
    def test_installer_receives_request_and_task_correlation(self, install):
        with patch("execution_supervisor.platform") as platform, patch("execution_supervisor.snapshot", return_value={}):
            platform.return_value.risk_for.return_value = "consequential"
            platform.return_value.verified_execution.return_value = None
            platform.return_value.tool_failure_window.return_value = {"failures": 0}
            tools.execute(
                "install_application", {"application": "Blender", "confirmed": True},
                context={"request_id": "request-1", "task_id": "task-1"},
            )
        install.assert_called_once_with(
            application="Blender", confirmed=True, _request_id="request-1", _task_id="task-1",
        )

    @patch.dict("os.environ", {}, clear=True)
    def test_optional_integrations_fail_cleanly_without_secrets(self):
        self.assertFalse(integrations.todoist_create_task("test")["ok"])
        self.assertFalse(integrations.home_assistant_control("light", "turn_on", "light.test")["ok"])

    @patch.dict("os.environ", {"HOME_ASSISTANT_URL": "http://example", "HOME_ASSISTANT_TOKEN": "x"})
    def test_home_assistant_rejects_unapproved_services(self):
        result = integrations.home_assistant_control("lock", "unlock", "lock.front_door")
        self.assertFalse(result["ok"])

    @patch("tools.webbrowser.open", return_value=True)
    def test_image_search_opens_encoded_url(self, browser_open):
        result = tools.open_search("red panda", "images")
        self.assertTrue(result["ok"])
        url = browser_open.call_args.args[0]
        self.assertIn("red+panda", url)
        self.assertIn("tbm=isch", url)


if __name__ == "__main__":
    unittest.main()
