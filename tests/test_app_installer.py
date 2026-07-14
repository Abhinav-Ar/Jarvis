import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app_installer


class AppInstallerTests(unittest.TestCase):
    def test_rejects_shell_text(self):
        result = app_installer.install("blender; rm -rf /", confirmed=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "application_not_allowlisted")

    def test_requires_confirmation_before_install(self):
        with patch("app_installer._installed", return_value=False), patch("app_installer._brew", return_value="/brew"):
            result = app_installer.install("Blender", confirmed=False)
        self.assertFalse(result["ok"])
        self.assertTrue(result["confirmation_required"])

    def test_starts_observable_background_job(self):
        process = Mock(pid=1234)
        with tempfile.TemporaryDirectory() as runtime:
            jobs = Path(runtime) / "installations"
            with (
                patch.object(app_installer, "JOBS", jobs),
                patch("app_installer._installed", return_value=False),
                patch("app_installer._brew", return_value="/brew"),
                patch("app_installer._official_cask", return_value=(True, "Blender.app")),
                patch("app_installer.subprocess.Popen", return_value=process),
            ):
                result = app_installer.install("Blender", confirmed=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "running")
            record = json.loads((jobs / f"{result['job_id']}.json").read_text())
            self.assertEqual(record["pid"], 1234)
            self.assertEqual(record["status"], "running")


if __name__ == "__main__":
    unittest.main()
