"""Jarvis voice assistant command-line application."""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import activity
import fast_commands
import diagnostics
from agent_platform import initialize_platform


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


def is_satisfied_command(text: str) -> bool:
    normalized = " ".join(re.sub(r"[^a-z0-9' ]", " ", text.lower()).split())
    normalized = normalized.replace("that'll", "that will").replace("that's", "that is")
    return normalized in {"that will be all", "that is all"}


def strip_wake_word(text: str, hotword: str) -> str:
    lowered = text.lower()
    if hotword not in lowered:
        return text.strip()
    index = lowered.index(hotword)
    result = (text[:index] + text[index + len(hotword):]).strip(" ,.!?")
    result = re.sub(r"^(hey|okay|ok)\b[\s,]*", "", result, flags=re.IGNORECASE)
    return result.strip(" ,.!?")


def is_authorized_logoff(text: str, hotword: str) -> bool:
    return hotword.lower() in text.lower() and is_logoff_command(strip_wake_word(text, hotword.lower()))


def is_authorized_session_close(text: str, hotword: str) -> bool:
    return hotword.lower() in text.lower() and is_satisfied_command(strip_wake_word(text, hotword.lower()))


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
    initialize_platform()
    start_desktop_control()
    activity.reset_ui()
    from assist import JarvisAssistant
    assistant = JarvisAssistant()
    recorder = None
    if not args.text:
        from audio import PhraseRecorder
        recorder = PhraseRecorder()

    hotword = os.getenv("JARVIS_HOTWORD", "jarvis").lower()
    session_active = False
    pending_audio_path = None
    print("Jarvis is ready. Press Control-C to stop.")
    activity.update("listening", "Listening")
    diagnostics.event("service_started", mode="text" if args.text else "voice", hotword=os.getenv("JARVIS_HOTWORD", "jarvis"))

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
                    activity.update("session" if session_active else "listening", "Ready" if session_active else "Listening")
                    audio_path = recorder.listen(on_speech_start=lambda: diagnostics.event("speech_started"))
                try:
                    print("Transcribing…", flush=True)
                    transcription_started = time.perf_counter()
                    text = assistant.transcribe(audio_path)
                    transcription_seconds = time.perf_counter() - transcription_started
                    diagnostics.event(
                        "transcription_completed", duration_ms=round(transcription_seconds * 1000),
                        transcript=text if os.getenv("JARVIS_LOG_TRANSCRIPTS", "1") == "1" else "[disabled]",
                    )
                finally:
                    audio_path.unlink(missing_ok=True)
                if text:
                    print(f"Heard ({transcription_seconds:.1f}s transcription): {text}")

            if not text:
                continue
            termination = session_active and is_satisfied_command(text)
            if not request_is_active(
                text,
                text_mode=args.text,
                no_hotword=args.no_hotword,
                follow_up=session_active,
                hotword=hotword,
            ):
                diagnostics.event("wake_phrase_not_found", transcript=text[:300])
                activity.update("session" if session_active else "listening", "Say Jarvis to continue" if session_active else "Listening")
                continue

            wake_detected = hotword in text.lower()
            request_id = uuid.uuid4().hex[:12]
            if wake_detected:
                if not session_active:
                    assistant.reset_session()
                session_active = True
                activity.cue("heard")
                activity.update("transcribing", "Wake confirmed", "Jarvis heard the activation phrase")
                text = strip_wake_word(text, hotword)
                diagnostics.event("wake_phrase_confirmed", request_id=request_id, request=text[:500])
            if not text:
                activity.append_chat("assistant", "How can I help?")
                assistant.speak("How can I help?")
                activity.update("session", "Ready", "Listening for your request")
                continue

            if is_logoff_command(text) and wake_detected:
                activity.update("stopped", "Stopped")
                stop_desktop_control()
                print("Jarvis: Logging off.")
                assistant.speak("Logging off.")
                break

            if is_logoff_command(text) and not wake_detected:
                message = "For a complete shutdown, say: Hey Jarvis, log off."
                activity.append_chat("user", text)
                activity.append_chat("assistant", message)
                assistant.speak(message)
                activity.update("session", "Your turn", "Conversation active")
                continue

            if is_satisfied_command(text) and wake_detected:
                activity.append_chat("user", text)
                activity.append_chat("assistant", "I’m glad I could help.")
                assistant.speak("I’m glad I could help.")
                assistant.reset_session()
                session_active = False
                activity.update("listening", "Listening")
                activity.cue("complete")
                continue

            if is_satisfied_command(text) and not wake_detected:
                message = "To close this session, say: Hey Jarvis, that’ll be all."
                activity.append_chat("user", text)
                activity.append_chat("assistant", message)
                assistant.speak(message)
                activity.update("session", "Your turn", "Conversation active")
                continue

            activity.append_chat("user", text)

            prompt = f"Local time: {datetime.now().astimezone().isoformat(timespec='minutes')}\nUser: {text}"
            if not wake_detected:
                activity.cue("heard")
            if is_complex_request(text):
                activity.acknowledge()
            print("Thinking…", flush=True)
            activity.update("planning", "Planning…", text[:100])
            thinking_started = time.perf_counter()
            diagnostics.event("request_started", request_id=request_id, request=text[:500], complex=is_complex_request(text))
            try:
                fast_reply = fast_commands.execute(text)
            except Exception as fast_error:
                diagnostics.event(
                    "fast_command_fallback", level="warning", request_id=request_id,
                    error=str(fast_error), request=text[:300],
                )
                fast_reply = None
            reply = fast_reply or assistant.ask(prompt, request_id=request_id)
            thinking_seconds = time.perf_counter() - thinking_started
            diagnostics.event("request_answer_ready", request_id=request_id, duration_ms=round(thinking_seconds * 1000), response_chars=len(reply))
            print(f"Jarvis ({thinking_seconds:.1f}s thinking): {reply}")
            activity.append_chat("assistant", reply)
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
                    session_active = True
                    continue
            activity.update("session", "Your turn", "Conversation active — wake word not required")
            activity.cue("complete")
            diagnostics.event("request_completed", request_id=request_id)
            if args.once:
                break
        except KeyboardInterrupt:
            print("\nGoodbye.")
            break
        except Exception as exc:
            activity.update("error", "Problem", str(exc)[:120])
            activity.cue("error")
            print(f"Jarvis error: {exc}", file=sys.stderr)
            diagnostics.event("request_failed", level="error", error=str(exc), traceback=traceback.format_exc())
            fallback = "I ran into a problem before I could verify the task. I’ve stopped safely instead of pretending it finished."
            activity.append_chat("assistant", fallback)
            try:
                assistant.speak(fallback, allow_barge_in=not args.text)
            except Exception as speech_error:
                print(f"Jarvis speech error: {speech_error}", file=sys.stderr)
            if args.once:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
