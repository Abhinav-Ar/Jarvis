import unittest
from unittest.mock import patch

import google_workspace


class GoogleWorkspaceTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_missing_authorization_is_actionable(self):
        result = google_workspace.create_document("Test", "Body", confirmed=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "google_authorization_required")

    @patch("google_workspace._request")
    def test_budget_spreadsheet_is_complete_in_one_operation(self, request):
        request.side_effect = [
            {"ok": True, "data": {
                "spreadsheetId": "sheet123", "spreadsheetUrl": "https://example/sheet123",
                "sheets": [{"properties": {"title": name, "sheetId": index}} for index, name in enumerate(("Dashboard", "Transactions", "Budget", "Categories"), start=1)],
            }},
            {"ok": True, "data": {}},
            {"ok": True, "data": {}},
        ]
        result = google_workspace.create_spreadsheet("Personal Finance", "budget", "USD", confirmed=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["sheets"], ["Dashboard", "Transactions", "Budget", "Categories"])
        values = request.call_args_list[1].kwargs["payload"]["data"]
        self.assertTrue(any(item["range"].startswith("Budget!") for item in values))
        formatting = request.call_args_list[2].kwargs["payload"]["requests"]
        self.assertTrue(any("addChart" in item for item in formatting))

    def test_creation_requires_explicit_request(self):
        result = google_workspace.create_spreadsheet("Budget", "budget", "USD", confirmed=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "confirmation_required")


if __name__ == "__main__":
    unittest.main()
