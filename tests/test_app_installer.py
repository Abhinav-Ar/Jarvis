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
                patch("app_installer._official_cask", return_value=(True, "Blender.app", "https://example.com/blender.dmg", "https://example.com")),
                patch("app_installer.subprocess.Popen", return_value=process),
                patch("app_installer._publish_task") as publish,
            ):
                result = app_installer.install("Blender", confirmed=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "running")
            record = json.loads((jobs / f"{result['job_id']}.json").read_text())
            self.assertEqual(record["pid"], 1234)
            self.assertEqual(record["status"], "running")
            publish.assert_called_once()

    def test_failed_package_download_recovers_inside_same_job(self):
        with tempfile.TemporaryDirectory() as runtime:
            jobs = Path(runtime) / "installations"
            jobs.mkdir()
            job_id = "abc123abc123"
            log_path = jobs / f"{job_id}.log"
            log_path.write_text("Download failed with 403")
            (jobs / f"{job_id}.json").write_text(json.dumps({
                "job_id": job_id, "application": "Blender", "cask": "blender",
                "bundle": "Blender.app", "status": "running", "log": str(log_path),
                "request_id": "request-1", "task_id": "task-1",
                "download_url": "https://example.com/blender.dmg", "homepage": "https://example.com",
                "route": "homebrew",
            }))
            completed = Mock(returncode=1)
            with (
                patch.object(app_installer, "JOBS", jobs),
                patch("app_installer._brew", return_value="/brew"),
                patch("app_installer._installed", return_value=False),
                patch("app_installer.subprocess.run", return_value=completed),
                patch("app_installer._browser_install", return_value=(True, "")) as fallback,
                patch("app_installer._finish_supervised_task") as finish,
                patch("app_installer._publish_task") as publish,
            ):
                self.assertEqual(app_installer._worker(job_id), 0)
            record = json.loads((jobs / f"{job_id}.json").read_text())
            self.assertEqual(record["status"], "completed")
            self.assertTrue(record["verified"])
            fallback.assert_called_once()
            finish.assert_called_once()
            self.assertEqual(publish.call_args_list[-1].kwargs["status"], "completed")

    def test_terminal_jobs_are_observed_only_once(self):
        with tempfile.TemporaryDirectory() as runtime:
            jobs = Path(runtime) / "installations"
            jobs.mkdir()
            path = jobs / "abc123abc123.json"
            path.write_text(json.dumps({
                "job_id": "abc123abc123", "application": "Blender", "status": "failed",
                "verified": False, "error": "403", "request_id": "r1", "task_id": "t1",
            }))
            with patch.object(app_installer, "JOBS", jobs):
                self.assertEqual(len(app_installer.poll_jobs()), 1)
                self.assertEqual(app_installer.poll_jobs(), [])


if __name__ == "__main__":
    unittest.main()
