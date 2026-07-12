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
                "get_weather", "open_search", "spotify_control", "open_application",
                "set_system_volume", "clipboard", "system_status", "show_notification",
                "create_reminder", "create_note", "create_calendar_event",
                "todoist_create_task", "home_assistant_control", "create_email_draft",
                "find_contact", "find_files",
            }
        self.assertEqual(function_names, handler_names)

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
