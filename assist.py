"""OpenAI Responses API conversation and speech services."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI

import tools


SYSTEM_PROMPT = """You are Jarvis, a concise, warm, capable voice assistant.
Address the user naturally. Keep spoken answers short unless detail is requested.
Use tools when the user asks for weather, web/image search, or Spotify control.
Never claim a tool succeeded unless its result says it did. The current local time
is provided with each request when relevant. Do not expose internal tool syntax.
"""


class JarvisAssistant:
    def __init__(self) -> None:
        self.client = OpenAI()
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
        self.voice = os.getenv("OPENAI_VOICE", "echo")
        self.tts_model = os.getenv("OPENAI_TTS_MODEL", "tts-1")
        self.previous_response_id: str | None = None

    def ask(self, question: str) -> str:
        response = self.client.responses.create(
            model=self.model,
            instructions=SYSTEM_PROMPT,
            input=question,
            tools=tools.TOOL_DEFINITIONS,
            previous_response_id=self.previous_response_id,
        )

        # A response may request several tool rounds before producing speech.
        for _ in range(6):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                self.previous_response_id = response.id
                return response.output_text.strip() or "I don't have a response for that."

            outputs = []
            for call in calls:
                try:
                    arguments = json.loads(call.arguments or "{}")
                    result = tools.execute(call.name, arguments)
                except Exception as exc:  # Tool failures should not stop conversation.
                    result = {"ok": False, "error": str(exc)}
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(result),
                    }
                )

            response = self.client.responses.create(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=outputs,
                tools=tools.TOOL_DEFINITIONS,
                previous_response_id=response.id,
            )

        raise RuntimeError("Jarvis exceeded the tool-call limit.")

    def transcribe(self, audio_path: Path) -> str:
        with audio_path.open("rb") as audio:
            result = self.client.audio.transcriptions.create(
                model=os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
                file=audio,
                language=os.getenv("JARVIS_LANGUAGE", "en"),
            )
        return result.text.strip()

    def speak(self, text: str) -> None:
        if not text or os.getenv("JARVIS_MUTE", "0") == "1":
            return
        path = Path(tempfile.gettempdir()) / "jarvis-response.mp3"
        with self.client.audio.speech.with_streaming_response.create(
            model=self.tts_model,
            voice=self.voice,
            input=text,
        ) as response:
            response.stream_to_file(path)
        try:
            subprocess.run(["/usr/bin/afplay", str(path)], check=True)
        finally:
            path.unlink(missing_ok=True)


_default: JarvisAssistant | None = None


def _assistant() -> JarvisAssistant:
    global _default
    if _default is None:
        _default = JarvisAssistant()
    return _default


def ask_question_memory(question: str) -> str:
    """Compatibility wrapper for older callers."""
    return _assistant().ask(question)


def TTS(text: str) -> str:
    """Compatibility wrapper for older callers."""
    _assistant().speak(text)
    return "done"
