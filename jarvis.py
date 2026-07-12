"""Jarvis voice assistant command-line application."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from dotenv import load_dotenv


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A conversational voice assistant for macOS")
    parser.add_argument("--text", action="store_true", help="type instead of using the microphone")
    parser.add_argument("--no-hotword", action="store_true", help="accept every captured phrase")
    parser.add_argument("--once", action="store_true", help="process one request and exit")
    parser.add_argument("--list-devices", action="store_true", help="list microphone devices and exit")
    return parser.parse_args()


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

    from assist import JarvisAssistant
    assistant = JarvisAssistant()
    recorder = None
    if not args.text:
        from audio import PhraseRecorder
        recorder = PhraseRecorder()

    hotword = os.getenv("JARVIS_HOTWORD", "jarvis").lower()
    follow_up = False
    print("Jarvis is ready. Press Control-C to stop.")

    while True:
        try:
            if args.text:
                text = input("You: ").strip()
                if text.lower() in {"exit", "quit"}:
                    break
            else:
                print(f"Listening for ‘{hotword}’…")
                audio_path = recorder.listen()
                try:
                    text = assistant.transcribe(audio_path)
                finally:
                    audio_path.unlink(missing_ok=True)
                if text:
                    print(f"Heard: {text}")

            if not text:
                continue
            if not (args.no_hotword or follow_up or hotword in text.lower()):
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

            prompt = f"Local time: {datetime.now().astimezone().isoformat(timespec='minutes')}\nUser: {text}"
            reply = assistant.ask(prompt)
            print(f"Jarvis: {reply}")
            assistant.speak(reply)
            follow_up = reply.rstrip().endswith("?")
            if args.once:
                break
        except KeyboardInterrupt:
            print("\nGoodbye.")
            break
        except Exception as exc:
            print(f"Jarvis error: {exc}", file=sys.stderr)
            if args.once:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
