"""Jarvis voice assistant command-line application."""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import activity
import fast_commands


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A conversational voice assistant for macOS")
    parser.add_argument("--text", action="store_true", help="type instead of using the microphone")
    parser.add_argument("--no-hotword", action="store_true", help="accept every captured phrase")
    parser.add_argument("--once", action="store_true", help="process one request and exit")
    parser.add_argument("--list-devices", action="store_true", help="list microphone devices and exit")
    return parser.parse_args()


def request_is_active(text: str, *, text_mode: bool, no_hotword: bool, follow_up: bool, hotword: str) -> bool:
    """Text is always active; voice requires its wake word unless in a follow-up."""
    return text_mode or no_hotword or follow_up or hotword in text.lower()


def is_logoff_command(text: str) -> bool:
    normalized = " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())
    for prefix in ("hey ", "okay ", "ok ", "please "):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    return normalized in {"log off", "log out", "logout", "go offline", "shut down jarvis"}


def stop_desktop_control() -> None:
    """Remove the active-session control grant while Jarvis is stopped."""
    flag = Path.home() / "Library/Application Support/Jarvis/.runtime/desktop-control-enabled"
    flag.unlink(missing_ok=True)


def start_desktop_control() -> None:
    """Every new Jarvis session defaults to desktop control on."""
    runtime = Path.home() / "Library/Application Support/Jarvis/.runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "desktop-control-disabled").unlink(missing_ok=True)
    (runtime / "desktop-control-enabled").touch()


def is_complex_request(text: str) -> bool:
    lowered = text.lower()
    markers = (" and then ", "commit", "push", "fill out", "organize", "all of", "after that")
    return any(marker in lowered for marker in markers)


def main() -> int:
    load_dotenv()
    args = arguments()
    if args.list_devices:
        from audio import PhraseRecorder
        print(PhraseRecorder.devices())
        return 0

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is missing. Copy .env.example to .env and add your key.", file=sys.stderr)
        return 2

    print("Starting Jarvis…", flush=True)
    start_desktop_control()
    from assist import JarvisAssistant
    assistant = JarvisAssistant()
    recorder = None
    if not args.text:
        from audio import PhraseRecorder
        recorder = PhraseRecorder()

    hotword = os.getenv("JARVIS_HOTWORD", "jarvis").lower()
    follow_up = False
    pending_audio_path = None
    print("Jarvis is ready. Press Control-C to stop.")
    activity.update("listening", "Listening")

    while True:
        try:
            if args.text:
                text = input("You: ").strip()
                if text.lower() in {"exit", "quit"}:
                    break
            else:
                listen_started = time.perf_counter()
                if pending_audio_path is not None:
                    print("Processing your interruption…")
                    audio_path = pending_audio_path
                    pending_audio_path = None
                else:
                    print(f"Listening for ‘{hotword}’…")
                    activity.update("listening", "Listening")
                    audio_path = recorder.listen()
                try:
                    print("Transcribing…", flush=True)
                    activity.update("transcribing", "Hearing…")
                    transcription_started = time.perf_counter()
                    text = assistant.transcribe(audio_path)
                    transcription_seconds = time.perf_counter() - transcription_started
                finally:
                    audio_path.unlink(missing_ok=True)
                if text:
                    print(f"Heard ({transcription_seconds:.1f}s transcription): {text}")

            if not text:
                continue
            if not request_is_active(
                text,
                text_mode=args.text,
                no_hotword=args.no_hotword,
                follow_up=follow_up,
                hotword=hotword,
            ):
                continue

            # Remove only the first hotword so the model receives a natural request.
            lowered = text.lower()
            if hotword in lowered:
                index = lowered.index(hotword)
                text = (text[:index] + text[index + len(hotword):]).strip(" ,.!?")
            if not text:
                assistant.speak("Yes?")
                follow_up = True
                continue

            if is_logoff_command(text):
                activity.update("stopped", "Stopped")
                stop_desktop_control()
                print("Jarvis: Logging off.")
                assistant.speak("Logging off.")
                break

            prompt = f"Local time: {datetime.now().astimezone().isoformat(timespec='minutes')}\nUser: {text}"
            activity.cue("heard")
            if is_complex_request(text):
                activity.acknowledge()
            print("Thinking…", flush=True)
            activity.update("planning", "Planning…", text[:100])
            thinking_started = time.perf_counter()
            reply = fast_commands.execute(text) or assistant.ask(prompt)
            thinking_seconds = time.perf_counter() - thinking_started
            print(f"Jarvis ({thinking_seconds:.1f}s thinking): {reply}")
            speaking_started = time.perf_counter()
            activity.update("speaking", "Responding…")
            voice_start_seconds, interrupted, interruption_audio = assistant.speak(
                reply, allow_barge_in=not args.text
            )
            if not args.text:
                total_seconds = time.perf_counter() - listen_started
                speech_seconds = time.perf_counter() - speaking_started
                print(
                    f"Voice started in {voice_start_seconds:.1f}s; completed in {total_seconds:.1f}s "
                    f"({speech_seconds:.1f}s including playback)."
                )
                if interrupted:
                    print("Interrupted — listening for your next instruction.")
                    pending_audio_path = interruption_audio
                    follow_up = True
                    continue
            follow_up = reply.rstrip().endswith("?")
            activity.update("needs_input" if follow_up else "listening", "Needs you" if follow_up else "Listening")
            if not follow_up:
                activity.cue("complete")
            if args.once:
                break
        except KeyboardInterrupt:
            print("\nGoodbye.")
            break
        except Exception as exc:
            activity.update("error", "Problem", str(exc)[:120])
            activity.cue("error")
            print(f"Jarvis error: {exc}", file=sys.stderr)
            if args.once:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
