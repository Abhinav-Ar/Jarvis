"""ORION voice assistant command-line application."""

from __future__ import annotations

import argparse
import json
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
import execution_supervisor
from agent_platform import initialize_platform
from orion_kernel import initialize_kernel


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A conversational voice assistant for macOS")
    parser.add_argument("--text", action="store_true", help="type instead of using the microphone")
    parser.add_argument("--no-hotword", action="store_true", help="accept every captured phrase")
    parser.add_argument("--once", action="store_true", help="process one request and exit")
    parser.add_argument("--list-devices", action="store_true", help="list microphone devices and exit")
    return parser.parse_args()


def request_is_active(text: str, *, text_mode: bool, no_hotword: bool, follow_up: bool, hotword: str) -> bool:
    """Text is always active; voice requires its wake word unless in a follow-up."""
    return text_mode or no_hotword or follow_up or has_wake_phrase(text, hotword)


def _wake_prefix(hotword: str) -> re.Pattern[str]:
    """Match activation language only at the start of an utterance.

    Barge-in transcription sometimes retains a leading conjunction from the
    sentence ORION was speaking, so a single "and" is accepted before the
    activation phrase. Mentions such as "the ORION project" are not wakeups.
    """
    escaped = re.escape(hotword.strip())
    return re.compile(
        rf"^\s*(?:(?:and|but)\s+)?(?:(?:hey|okay|ok)\s+)?{escaped}\b[\s,.:;!?-]*",
        flags=re.IGNORECASE,
    )


def has_wake_phrase(text: str, hotword: str) -> bool:
    return bool(_wake_prefix(hotword).match(text))


def is_logoff_command(text: str) -> bool:
    normalized = " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())
    for prefix in ("hey ", "okay ", "ok ", "please "):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    return normalized in {
        "log off", "logoff", "log out", "logout", "go offline",
        "shut down orion", "shut down jarvis",
    }


def is_satisfied_command(text: str) -> bool:
    normalized = " ".join(re.sub(r"[^a-z0-9' ]", " ", text.lower()).split())
    normalized = normalized.replace("that'll", "that will").replace("that's", "that is").replace("we're", "we are")
    for prefix in ("okay ", "ok ", "please ", "thanks ", "thank you "):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    return normalized in {
        "that will be all", "that is all", "that is everything",
        "we are done", "we are all set", "done for now", "all set for now",
        "end this session", "close this session",
    }


def strip_wake_word(text: str, hotword: str) -> str:
    match = _wake_prefix(hotword).match(text)
    return (text[match.end():] if match else text).strip(" ,.!?")


def is_authorized_logoff(text: str, hotword: str) -> bool:
    return has_wake_phrase(text, hotword) and is_logoff_command(strip_wake_word(text, hotword))


def is_authorized_session_close(text: str, hotword: str) -> bool:
    return has_wake_phrase(text, hotword) and is_satisfied_command(strip_wake_word(text, hotword))


def stop_desktop_control() -> None:
    """Remove the active-session control grant while ORION is stopped."""
    flag = Path.home() / "Library/Application Support/Jarvis/.runtime/desktop-control-enabled"
    flag.unlink(missing_ok=True)


def start_desktop_control() -> None:
    """Every new ORION session defaults to desktop control on."""
    runtime = Path.home() / "Library/Application Support/Jarvis/.runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "desktop-control-disabled").unlink(missing_ok=True)
    (runtime / "desktop-control-enabled").touch()


def is_complex_request(text: str) -> bool:
    lowered = text.lower()
    markers = (
        " and then ", " then ", "commit", "push", "fill out", "organize",
        "all of", "after that", "arrange", "tile", "side by side", "both apps",
        "balanced workspace", "create a workspace", "set up a workspace",
    )
    return any(marker in lowered for marker in markers)


def restore_workspace() -> None:
    try:
        from desktop import restore_windows
        restore_windows(confirmed=True)
    except Exception as exc:
        diagnostics.event("workspace_restore_failed", level="warning", error=str(exc))


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

    print("Starting ORION…", flush=True)
    agent_platform = initialize_platform()
    operating_kernel = initialize_kernel()
    agent_platform.write_status()
    session_id = uuid.uuid4().hex
    start_desktop_control()
    activity.reset_ui()
    from assist import OrionAssistant
    assistant = OrionAssistant()
    recorder = None
    if not args.text:
        from audio import PhraseRecorder, TypedCommandReady, push_to_talk_enabled
        recorder = PhraseRecorder()

    hotword = os.getenv("ORION_HOTWORD", "orion").lower()
    session_active = False
    pending_audio_path = None
    print("ORION is ready. Press Control-C to stop.")
    activity.update("listening", "Listening")
    diagnostics.event("service_started", identity="ORION", session_id=session_id, mode="text" if args.text else "voice", hotword=hotword)

    while True:
        try:
            typed_input = False
            if args.text:
                text = input("You: ").strip()
                if text.lower() in {"exit", "quit"}:
                    break
            else:
                listen_started = time.perf_counter()
                text = activity.take_text_command()
                if text:
                    typed_input = True
                    print(f"Typed: {text}", flush=True)
                elif pending_audio_path is not None:
                    print("Processing your interruption…")
                    audio_path = pending_audio_path
                    pending_audio_path = None
                else:
                    ptt_mode = push_to_talk_enabled()
                    print("Hold Right Option to speak…" if ptt_mode else f"Listening for ‘{hotword}’…")
                    activity.update("session" if session_active else "listening", "Hold Right Option" if ptt_mode else ("Ready" if session_active else "Listening"))
                    try:
                        audio_path = recorder.listen(on_speech_start=lambda: diagnostics.event("speech_started"))
                    except TypedCommandReady:
                        text = activity.take_text_command()
                        typed_input = bool(text)
                        if not typed_input:
                            continue
                if not typed_input:
                    try:
                        print("Transcribing…", flush=True)
                        transcription_started = time.perf_counter()
                        text = assistant.transcribe(audio_path)
                        transcription_seconds = time.perf_counter() - transcription_started
                        diagnostics.event(
                            "transcription_completed", duration_ms=round(transcription_seconds * 1000),
                            transcript=text if os.getenv("ORION_LOG_TRANSCRIPTS", os.getenv("JARVIS_LOG_TRANSCRIPTS", "1")) == "1" else "[disabled]",
                        )
                    finally:
                        audio_path.unlink(missing_ok=True)
                    if text:
                        print(f"Heard ({transcription_seconds:.1f}s transcription): {text}")

            if not text:
                continue
            ptt_activation = not args.text and not typed_input and push_to_talk_enabled()
            if not request_is_active(
                text,
                text_mode=args.text or typed_input,
                no_hotword=args.no_hotword or ptt_activation,
                follow_up=session_active,
                hotword=hotword,
            ):
                diagnostics.event("wake_phrase_not_found", transcript=text[:300])
                activity.update("session" if session_active else "listening", "Say ORION to continue" if session_active else "Listening")
                continue

            wake_detected = has_wake_phrase(text, hotword)
            request_id = uuid.uuid4().hex[:12]
            execution_supervisor.begin_request(request_id)
            if wake_detected:
                text = strip_wake_word(text, hotword)
            lifecycle_authorized = args.text or typed_input or args.no_hotword or ptt_activation or wake_detected

            if is_logoff_command(text) and lifecycle_authorized:
                activity.clear_text_commands()
                activity.end_session_ui()
                restore_workspace()
                activity.update("stopped", "Stopped")
                stop_desktop_control()
                operating_kernel.stop_monitor()
                print("ORION: Logging off.")
                assistant.speak("Logging off.")
                break

            if is_satisfied_command(text) and lifecycle_authorized and session_active:
                activity.clear_text_commands()
                activity.append_chat("user", text)
                activity.append_chat("assistant", "I’m glad I could help.")
                activity.end_session_ui()
                assistant.speak("I’m glad I could help.")
                restore_workspace()
                assistant.reset_session()
                session_active = False
                activity.update("listening", "Hold Right Option" if ptt_activation else "Listening")
                activity.cue("complete")
                continue

            if (is_logoff_command(text) or is_satisfied_command(text)) and not lifecycle_authorized:
                diagnostics.event("lifecycle_command_rejected", request_id=request_id, request=text[:120])
                continue

            if not text:
                continue

            if ptt_activation or typed_input or wake_detected or args.text or args.no_hotword:
                if not session_active:
                    assistant.reset_session()
                session_active = True
                activity.cue("heard")
                diagnostics.event(
                    "request_activation_confirmed", request_id=request_id,
                    method="typed" if typed_input else ("push_to_talk" if ptt_activation else "wake_phrase"),
                )

            activity.begin_session_ui()
            activity.append_chat("user", text)

            kernel_turn = operating_kernel.before_request(text, request_id, session_id)
            kernel_context = json.dumps(kernel_turn["context"], default=str)[:5000]
            prompt = (
                f"Local time: {datetime.now().astimezone().isoformat(timespec='minutes')}\n"
                f"ORION operating context (local, bounded): {kernel_context}\nUser: {text}"
            )
            if not wake_detected:
                activity.cue("heard")
            if is_complex_request(text):
                activity.acknowledge()
            print("Thinking…", flush=True)
            activity.update("planning", "Planning…", text[:100])
            thinking_started = time.perf_counter()
            diagnostics.event(
                "request_started", request_id=request_id, request=text[:500],
                complex=is_complex_request(text), input_source="typed" if typed_input else ("terminal" if args.text else "voice"),
            )
            try:
                fast_reply = fast_commands.execute(text, request_id=request_id)
            except Exception as fast_error:
                diagnostics.event(
                    "fast_command_fallback", level="warning", request_id=request_id,
                    error=str(fast_error), request=text[:300],
                )
                fast_reply = None
            reply = fast_reply or assistant.ask(prompt, request_id=request_id)
            assistant.record_turn(text, reply, local=fast_reply is not None)
            operating_kernel.after_response(
                text, reply, request_id, session_id, kernel_turn["goal_id"], kernel_turn["route"]
            )
            thinking_seconds = time.perf_counter() - thinking_started
            diagnostics.event("request_answer_ready", request_id=request_id, duration_ms=round(thinking_seconds * 1000), response_chars=len(reply))
            print(f"ORION ({thinking_seconds:.1f}s thinking): {reply}")
            activity.append_chat("assistant", reply)
            speaking_started = time.perf_counter()
            interrupted = False
            interruption_audio = None
            if typed_input:
                voice_start_seconds = 0.0
            else:
                activity.update("speaking", "Responding…")
                voice_start_seconds, interrupted, interruption_audio = assistant.speak(
                    reply, allow_barge_in=not args.text
                )
            if not args.text and not typed_input:
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
            activity.update("session", "Your turn", "Type below or hold Right Option to continue")
            activity.cue("complete")
            diagnostics.event("request_completed", request_id=request_id)
            if args.once:
                break
        except KeyboardInterrupt:
            restore_workspace()
            print("\nGoodbye.")
            break
        except Exception as exc:
            activity.update("error", "Problem", str(exc)[:120])
            activity.cue("error")
            print(f"ORION error: {exc}", file=sys.stderr)
            diagnostics.event("request_failed", level="error", error=str(exc), traceback=traceback.format_exc())
            if "cloud-call limit" in str(exc).lower():
                fallback = (
                    "Cloud reasoning is paused because today’s call budget has been reached. "
                    "My local Mac controls and saved workflows still work, and cloud access will return as the rolling 24-hour window clears."
                )
            else:
                fallback = "I ran into a problem before I could verify the task. I’ve stopped safely instead of pretending it finished."
            activity.append_chat("assistant", fallback)
            try:
                assistant.speak(fallback, allow_barge_in=not args.text)
            except Exception as speech_error:
                print(f"ORION speech error: {speech_error}", file=sys.stderr)
            if args.once:
                return 1
    operating_kernel.stop_monitor()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
