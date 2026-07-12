import unittest
from unittest.mock import patch

import tools


class ToolTests(unittest.TestCase):
    def test_unknown_tool_is_rejected(self):
        result = tools.execute("erase_computer", {})
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
