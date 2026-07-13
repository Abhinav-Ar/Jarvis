import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import diagnostics


class DiagnosticTests(unittest.TestCase):
    def test_events_are_structured_and_secrets_are_redacted(self):
        with TemporaryDirectory() as folder:
            runtime = Path(folder)
            event_file = runtime / "events.jsonl"
            with patch.object(diagnostics, "RUNTIME", runtime), patch.object(
                diagnostics, "EVENT_FILE", event_file
            ):
                diagnostics.event("test_event", request_id="abc", api_key="sk-secret-value-123456", ok=True)
            record = json.loads(event_file.read_text().splitlines()[0])
            self.assertEqual(record["event"], "test_event")
            self.assertEqual(record["request_id"], "abc")
            self.assertEqual(record["api_key"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
