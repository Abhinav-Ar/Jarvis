import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jarvis import is_logoff_command, request_is_active, start_desktop_control, stop_desktop_control


class RequestActivationTests(unittest.TestCase):
    def test_log_off_is_local_lifecycle_command(self):
        self.assertTrue(is_logoff_command("log off"))
        self.assertTrue(is_logoff_command("Log out!"))
        self.assertTrue(is_logoff_command("Hey, log off"))
        self.assertFalse(is_logoff_command("log off Spotify"))

    def test_text_mode_does_not_require_hotword(self):
        self.assertTrue(
            request_is_active(
                "What can you do?",
                text_mode=True,
                no_hotword=False,
                follow_up=False,
                hotword="jarvis",
            )
        )

    def test_voice_mode_still_requires_hotword(self):
        self.assertFalse(
            request_is_active(
                "What can you do?",
                text_mode=False,
                no_hotword=False,
                follow_up=False,
                hotword="jarvis",
            )
        )

    def test_logoff_clears_desktop_control(self):
        with TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)):
            flag = Path(home) / "Library/Application Support/Jarvis/.runtime/desktop-control-enabled"
            flag.parent.mkdir(parents=True)
            flag.touch()
            stop_desktop_control()
            self.assertFalse(flag.exists())

    def test_desktop_control_defaults_on_unless_disabled(self):
        with TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)):
            runtime = Path(home) / "Library/Application Support/Jarvis/.runtime"
            start_desktop_control()
            self.assertTrue((runtime / "desktop-control-enabled").exists())
            (runtime / "desktop-control-enabled").unlink()
            (runtime / "desktop-control-disabled").touch()
            start_desktop_control()
            self.assertTrue((runtime / "desktop-control-enabled").exists())
            self.assertFalse((runtime / "desktop-control-disabled").exists())


if __name__ == "__main__":
    unittest.main()
