import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from assist import JarvisAssistant


class FakeResponses:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.responses)


class AssistantTests(unittest.TestCase):
    def test_speech_text_removes_markdown_links_and_urls(self):
        spoken = JarvisAssistant.speech_text(
            "Latest: [AP News](https://apnews.com/story) and https://example.com/details"
        )
        self.assertEqual(spoken, "Latest: AP News and")

    @patch.dict(os.environ, {"OPENAI_MODEL": "gpt-5-mini"})
    def test_older_mini_model_uses_compatible_reasoning_effort(self):
        assistant = JarvisAssistant()
        self.assertEqual(assistant.reasoning_effort, "minimal")

    def test_plain_response_is_returned_and_remembered(self):
        answer = SimpleNamespace(id="r1", output=[], output_text="Hello, Sir.")
        assistant = JarvisAssistant()
        fake = FakeResponses([answer])
        assistant.client = SimpleNamespace(responses=fake)

        self.assertEqual(assistant.ask("Hello"), "Hello, Sir.")
        self.assertEqual(assistant.previous_response_id, "r1")

    def test_function_call_result_is_sent_back(self):
        tool_call = SimpleNamespace(
            type="function_call",
            name="get_weather",
            arguments='{"location":"Cupertino"}',
            call_id="call-1",
        )
        first = SimpleNamespace(id="r1", output=[tool_call], output_text="")
        second = SimpleNamespace(id="r2", output=[], output_text="It is sunny.")
        assistant = JarvisAssistant()
        fake = FakeResponses([first, second])
        assistant.client = SimpleNamespace(responses=fake)

        with patch("assist.tools.execute", return_value={"ok": True, "temperature": 72}):
            self.assertEqual(assistant.ask("Weather?"), "It is sunny.")

        output = fake.calls[1]["input"][0]
        self.assertEqual(output["type"], "function_call_output")
        self.assertEqual(output["call_id"], "call-1")
        self.assertIn('"ok": true', output["output"])
        self.assertEqual(assistant.previous_response_id, "r2")


if __name__ == "__main__":
    unittest.main()
