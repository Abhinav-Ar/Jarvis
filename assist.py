"""OpenAI Responses API conversation and speech services."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from openai import OpenAI
import sounddevice as sd

import tools


SYSTEM_PROMPT = """You are Jarvis, a concise, warm, capable voice assistant.
Address the user naturally. Because answers are spoken aloud, default to at most
45 words and three compact points unless detail is explicitly requested. Do not
include raw URLs in prose; citations may remain attached to displayed text.
Use tools when the user asks for current research, weather, searches, Mac actions,
Apple apps, Spotify, Todoist, or Home Assistant. Only perform actions that the
user explicitly requested; never infer a side effect from casual conversation.
Spotify existing-playlist playback and new-playlist creation are distinct: never
create a playlist unless the requested action verb is explicitly create, make,
build, or generate. The words "new", "discovery", and "recommendation" describe
a playlist but do not authorize creation when the requested verb is play, open,
start, resume, or listen. A request to play "one of my playlists" must only
play an existing playlist owned by the user or marked collaborative; followed
playlists owned by other people do not count as "my playlists."
Email tooling creates visible drafts only and never sends them.
Desktop inspection is read-only. Before desktop actions, inspect the screen, then
use only bounded actions explicitly requested by the user. Desktop control must
be enabled in the visible menu bar. Never inspect or type passwords, private keys,
authentication codes, or payment data. Always ask for confirmation immediately
before sending messages, submitting forms, purchases, deletions, or account changes.
Never claim a tool succeeded unless its result says it did. The current local time
is provided with each request when relevant. Do not expose internal tool syntax.
"""


class JarvisAssistant:
    def __init__(self) -> None:
        self.client = OpenAI()
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
        self.reasoning_effort = os.getenv(
            "OPENAI_REASONING_EFFORT",
            "none" if self.model.startswith("gpt-5.4") else "minimal",
        )
        self.voice = os.getenv("OPENAI_VOICE", "echo")
        self.tts_model = os.getenv("OPENAI_TTS_MODEL", "tts-1")
        self.previous_response_id: str | None = None

    def ask(self, question: str) -> str:
        response = self.client.responses.create(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
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
                reasoning={"effort": self.reasoning_effort},
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

    @staticmethod
    def speech_text(text: str) -> str:
        """Turn display-oriented Markdown into concise, speakable text."""
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"[*_`#]", "", text)
        text = re.sub(r"\n\s*[-•]\s*", ". ", text)
        text = re.sub(r"\s+", " ", text).strip()
        limit = int(os.getenv("JARVIS_MAX_SPOKEN_CHARS", "500"))
        if len(text) > limit:
            boundary = text.rfind(". ", 0, limit)
            text = text[: boundary + 1 if boundary > limit // 2 else limit].rstrip()
            text += " I’ve shown the remaining details on screen."
        return text

    def speak(self, text: str, allow_barge_in: bool = False) -> tuple[float, bool, Path | None]:
        if not text or os.getenv("JARVIS_MUTE", "0") == "1":
            return 0.0, False, None
        text = self.speech_text(text)
        request_started = time.perf_counter()
        first_audio_delay = 0.0
        interrupted = False
        interruption_audio = None
        monitor_context = None
        if allow_barge_in:
            from audio import BargeInMonitor

            monitor_context = BargeInMonitor()
            monitor = monitor_context.__enter__()
        else:
            monitor = None
        try:
            with self.client.audio.speech.with_streaming_response.create(
                model=self.tts_model,
                voice=self.voice,
                input=text,
                response_format="pcm",
            ) as response:
                pending = b""
                with sd.RawOutputStream(samplerate=24000, channels=1, dtype="int16") as output:
                    for chunk in response.iter_bytes(chunk_size=4096):
                        if monitor is not None and monitor.triggered.is_set():
                            interrupted = True
                            break
                        if not first_audio_delay:
                            first_audio_delay = time.perf_counter() - request_started
                        pending += chunk
                        complete = len(pending) - (len(pending) % 2)
                        if complete:
                            output.write(pending[:complete])
                            pending = pending[complete:]
            if interrupted and monitor is not None:
                interruption_audio = monitor.capture_phrase()
        finally:
            if monitor_context is not None:
                monitor_context.__exit__(None, None, None)
        return first_audio_delay, interrupted, interruption_audio


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
