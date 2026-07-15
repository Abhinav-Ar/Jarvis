import os
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from assist import JarvisAssistant
from task_engine import TaskPlan
import execution_supervisor


class FakeResponses:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.responses)


class AssistantTests(unittest.TestCase):
    @staticmethod
    def bypass_planner(assistant, requires_tools=False):
        assistant.task_engine.lane = "complex" if requires_tools else "simple"
        assistant.task_engine.plan = lambda *args, **kwargs: TaskPlan(
            "test", requires_tools, ["done"], ["act", "verify"], "low", []
        )

    def test_speech_text_removes_markdown_links_and_urls(self):
        spoken = JarvisAssistant.speech_text(
            "Latest: [AP News](https://apnews.com/story) and https://example.com/details"
        )
        self.assertEqual(spoken, "Latest: AP News and")

    def test_repeated_decoder_hallucination_is_rejected(self):
        self.assertEqual(JarvisAssistant.sanitize_transcript("and " + "modification " * 100), "")
        self.assertEqual(
            JarvisAssistant.sanitize_transcript("Commit and push the Jarvis project"),
            "Commit and push the Jarvis project",
        )

    @patch.dict(os.environ, {"JARVIS_LOCAL_TRANSCRIPTION": "0"})
    def test_streaming_transcription_returns_completed_text(self):
        events = iter([
            SimpleNamespace(type="transcript.text.delta", delta="Hello "),
            SimpleNamespace(type="transcript.text.delta", delta="Jarvis"),
            SimpleNamespace(type="transcript.text.done", text="Hello Jarvis"),
        ])
        create = Mock(return_value=events)
        assistant = JarvisAssistant()
        assistant.client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
        path = Path(tempfile.gettempdir()) / "jarvis-test-audio.wav"
        path.write_bytes(b"test")
        try:
            self.assertEqual(assistant.transcribe(path), "Hello Jarvis")
            self.assertTrue(create.call_args.kwargs["stream"])
        finally:
            path.unlink(missing_ok=True)

    @patch.dict(os.environ, {"JARVIS_LOCAL_TRANSCRIPTION": "1"})
    def test_local_transcription_receives_pcm_samples_without_cloud(self):
        transcribe = Mock(return_value={"text": "Hello locally"})
        local_module = SimpleNamespace(transcribe=transcribe)
        assistant = JarvisAssistant()
        assistant.platform = Mock()
        path = Path(tempfile.gettempdir()) / "jarvis-test-local-audio.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 320)
        try:
            with patch.dict("sys.modules", {"mlx_whisper": local_module}):
                self.assertEqual(assistant.transcribe(path), "Hello locally")
            waveform = transcribe.call_args.args[0]
            self.assertEqual(waveform.dtype.name, "float32")
            self.assertEqual(len(waveform), 320)
            assistant.platform.cloud_allowed.assert_not_called()
        finally:
            path.unlink(missing_ok=True)

    @patch.dict(os.environ, {"OPENAI_MODEL": "gpt-5-mini"})
    def test_older_mini_model_uses_compatible_reasoning_effort(self):
        assistant = JarvisAssistant()
        self.assertEqual(assistant.reasoning_effort, "minimal")

    def test_plain_response_is_returned_and_remembered(self):
        answer = SimpleNamespace(id="r1", output=[], output_text="Hello, Sir.")
        assistant = JarvisAssistant()
        self.bypass_planner(assistant)
        fake = FakeResponses([answer])
        assistant.client = SimpleNamespace(responses=fake)

        self.assertEqual(assistant.ask("Hello"), "Hello, Sir.")
        self.assertEqual(assistant.previous_response_id, "r1")

    def test_stop_returns_during_cloud_wait_without_using_late_response(self):
        assistant = JarvisAssistant()
        assistant._cloud_response = lambda *args, **kwargs: (time.sleep(3), object())[1]
        with tempfile.TemporaryDirectory() as folder, (
            patch.object(execution_supervisor, "CANCEL_FILE", Path(folder) / "cancel-current-task")
        ):
            timer = threading.Timer(0.15, lambda: execution_supervisor.request_cancel("request", source="test"))
            timer.start()
            started = time.monotonic()
            try:
                result = assistant._cloud_response_cancellable("assistant", "request")
            finally:
                timer.cancel()
                execution_supervisor.clear_cancel()
        self.assertIsNone(result)
        self.assertLess(time.monotonic() - started, 1.5)

    def test_short_followup_reuses_active_tool_lane(self):
        answer = SimpleNamespace(id="r2", output=[], output_text="Continuing.")
        assistant = JarvisAssistant()
        self.bypass_planner(assistant)
        assistant.previous_response_id = "r1"
        assistant.last_selected_tools = [{"type": "function", "name": "spotify_control"}]
        fake = FakeResponses([answer])
        assistant.client = SimpleNamespace(responses=fake)

        self.assertEqual(assistant.ask("Local time: now\nUser: continue"), "Continuing.")
        self.assertEqual(fake.calls[0]["tools"], assistant.last_selected_tools)

    def test_punctuated_followup_reuses_local_tool_lane(self):
        answer = SimpleNamespace(id="r3", output=[], output_text="I checked it.")
        assistant = JarvisAssistant()
        self.bypass_planner(assistant)
        assistant.last_selected_tools = [{"type": "function", "name": "git_status"}]
        fake = FakeResponses([answer])
        assistant.client = SimpleNamespace(responses=fake)

        self.assertEqual(assistant.ask("Local time: now\nUser: Yeah, do it."), "I checked it.")
        self.assertEqual(fake.calls[0]["tools"], assistant.last_selected_tools)

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
        self.bypass_planner(assistant)
        fake = FakeResponses([first, second])
        assistant.client = SimpleNamespace(responses=fake)

        with patch("assist.tools.execute", return_value={"ok": True, "temperature": 72}):
            self.assertEqual(assistant.ask("Weather?"), "It is sunny.")

        output = fake.calls[1]["input"][0]
        self.assertEqual(output["type"], "function_call_output")
        self.assertEqual(output["call_id"], "call-1")
        self.assertIn('"ok": true', output["output"])
        self.assertEqual(assistant.previous_response_id, "r2")

    def test_simple_verified_action_skips_second_model_round_trip(self):
        tool_call = SimpleNamespace(
            type="function_call", name="open_application", arguments='{"name":"Safari"}', call_id="c1"
        )
        action = SimpleNamespace(id="r1", output=[tool_call], output_text="")
        assistant = JarvisAssistant()
        self.bypass_planner(assistant)
        fake = FakeResponses([action])
        assistant.client = SimpleNamespace(responses=fake)

        with patch("assist.tools.execute", return_value={"ok": True, "application": "Safari", "frontmost": True}):
            self.assertEqual(assistant.ask("Open Safari"), "Safari is open.")
        self.assertEqual(len(fake.calls), 1)

    def test_known_user_blocker_stops_without_another_model_call(self):
        tool_call = SimpleNamespace(
            type="function_call", name="git_push",
            arguments='{"repository":"Jarvis","confirmed":true}', call_id="c1",
        )
        action = SimpleNamespace(id="r1", output=[tool_call], output_text="")
        assistant = JarvisAssistant()
        self.bypass_planner(assistant, requires_tools=True)
        fake = FakeResponses([action])
        assistant.client = SimpleNamespace(responses=fake)
        failure = {
            "ok": False, "error_code": "remote_permission_denied",
            "requires_user": True, "committed": True, "error": "403",
        }
        with patch("assist.tools.execute", return_value=failure):
            answer = assistant.ask("Commit and push Jarvis")
        self.assertIn("rejected the push", answer)
        self.assertEqual(len(fake.calls), 1)

    def test_actionable_task_is_audited_before_completion(self):
        tool_call = SimpleNamespace(
            type="function_call", name="open_application", arguments='{"name":"Safari"}', call_id="c1"
        )
        action = SimpleNamespace(id="r1", output=[tool_call], output_text="")
        premature = SimpleNamespace(id="r2", output=[], output_text="Safari opened.")
        verified = SimpleNamespace(id="r3", output=[], output_text="Safari is open and foreground.")
        assistant = JarvisAssistant()
        self.bypass_planner(assistant, requires_tools=True)
        fake = FakeResponses([action, premature, verified])
        assistant.client = SimpleNamespace(responses=fake)

        with patch("assist.tools.execute", return_value={"ok": True, "frontmost": True}):
            answer = assistant.ask("Open Safari")

        self.assertEqual(answer, "Safari is open and foreground.")
        self.assertIn("Audit the active task", fake.calls[2]["input"])

    def test_unevidenced_action_promise_is_blocked(self):
        promise = SimpleNamespace(id="r1", output=[], output_text="I’ll open it now.")
        repeated = SimpleNamespace(id="r2", output=[], output_text="I’ll take care of that.")
        assistant = JarvisAssistant()
        self.bypass_planner(assistant, requires_tools=True)
        fake = FakeResponses([promise, repeated])
        assistant.client = SimpleNamespace(responses=fake)

        answer = assistant.ask("Open Safari")

        self.assertIn("no action ran", answer)
        self.assertIn("didn’t make any changes", answer)

    def test_missing_capability_blocks_without_calling_model(self):
        assistant = JarvisAssistant()
        self.bypass_planner(assistant, requires_tools=True)
        first = SimpleNamespace(id="r1", output=[], output_text="I’ll find and delete those files.")
        second = SimpleNamespace(id="r2", output=[], output_text="I’ll take care of it.")
        fake = FakeResponses([first, second])
        assistant.client = SimpleNamespace(responses=fake)

        answer = assistant.ask("Delete every file on the Mac")

        self.assertIn("no action ran", answer)
        self.assertEqual(len(fake.calls), 2)


if __name__ == "__main__":
    unittest.main()
