import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jarvis import (
    has_wake_phrase, is_authorized_logoff, is_authorized_session_close, is_logoff_command,
    is_satisfied_command, request_is_active,
    start_desktop_control, stop_desktop_control, strip_wake_word,
)


class RequestActivationTests(unittest.TestCase):
    def test_log_off_is_local_lifecycle_command(self):
        self.assertTrue(is_logoff_command("log off"))
        self.assertTrue(is_logoff_command("Log out!"))
        self.assertTrue(is_logoff_command("Hey, log off"))
        self.assertFalse(is_logoff_command("log off Spotify"))
        self.assertTrue(is_authorized_logoff("Hey Jarvis, log off", "jarvis"))
        self.assertTrue(is_authorized_logoff("and hey Jarvis Logoff", "jarvis"))
        self.assertFalse(is_authorized_logoff("log off", "jarvis"))

    def test_baymax_style_satisfaction_ends_session(self):
        self.assertTrue(is_satisfied_command("That'll be all."))
        self.assertTrue(is_satisfied_command("That's all"))
        self.assertFalse(is_satisfied_command("I'm satisfied with my care."))
        self.assertTrue(is_authorized_session_close("Hey Jarvis, that'll be all", "jarvis"))
        self.assertFalse(is_authorized_session_close("that'll be all", "jarvis"))

    def test_wake_only_and_wake_with_prompt_are_cleaned(self):
        self.assertEqual(strip_wake_word("Hey Jarvis", "jarvis"), "")
        self.assertEqual(strip_wake_word("Hey Jarvis, open Safari", "jarvis"), "open Safari")
        self.assertEqual(
            strip_wake_word("Close everything related to the Jarvis workspace", "jarvis"),
            "Close everything related to the Jarvis workspace",
        )
        self.assertFalse(has_wake_phrase("close the Jarvis project", "jarvis"))
        self.assertTrue(has_wake_phrase("and hey Jarvis, log off", "jarvis"))

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

    def test_active_conversation_accepts_followups_without_wake_word(self):
        self.assertTrue(
            request_is_active(
                "continue with the next step",
                text_mode=False,
                no_hotword=False,
                follow_up=True,
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
