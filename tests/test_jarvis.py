import unittest

from jarvis import request_is_active


class RequestActivationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
