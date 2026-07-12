# Jarvis for macOS

Jarvis is an always-ready conversational voice assistant. It records a spoken
phrase locally, transcribes it with OpenAI, answers through the Responses API,
and speaks the answer through the Mac's audio output. It can also check weather,
open searches, and optionally control Spotify.

## What you need

- An Apple Silicon Mac with Python 3.10 or newer
- A microphone and macOS microphone permission for Terminal or Codex
- An OpenAI API key with billing enabled
- Internet access
- Optional: a Spotify developer application and Spotify Premium

API usage is billed by OpenAI. Voice mode sends each detected phrase for
transcription. Text mode is useful for setup and does not access the microphone.

## Install

```sh
./setup.sh
```

Open `.env` and set:

```dotenv
OPENAI_API_KEY=your_key_here
```

The first voice launch should trigger a macOS microphone permission prompt.
Allow access for the application from which Jarvis is running. If needed, check
System Settings → Privacy & Security → Microphone.

## Run

Voice mode:

```sh
./start.sh
```

Say “Jarvis” followed by a request. Press Control-C to stop.

Text mode, recommended for the first test:

```sh
./start.sh --text
```

Other useful options:

```sh
./start.sh --no-hotword   # respond to every spoken phrase
./start.sh --once         # handle one request and exit
./start.sh --list-devices # show microphone device numbers
```

Set `JARVIS_INPUT_DEVICE` in `.env` if the default microphone is wrong. Raise
`JARVIS_ENERGY_THRESHOLD` if background noise activates recording; lower it if
Jarvis does not detect your voice.

## Spotify (optional)

Create an application in the Spotify developer dashboard. Register
`http://127.0.0.1:8888/callback` as its redirect URI, then fill in the three
`SPOTIPY_...` values in `.env`. The first Spotify command opens a browser for
authorization. Spotify is loaded only when requested, so it cannot prevent the
rest of Jarvis from starting.

## Architecture

- `jarvis.py`: command-line loop, hotword and follow-up behavior
- `audio.py`: microphone capture and silence detection
- `assist.py`: OpenAI Responses, transcription, TTS, and conversation memory
- `tools.py`: structured weather, search, and Spotify tools
- `spot.py`: lazy Spotify OAuth and playback control

Conversation memory lasts for the current process. Restarting Jarvis starts a
fresh conversation. No assistant ID or thread ID is required.

## Privacy and safety

Audio is temporarily written to the system temporary directory, uploaded for
transcription, and deleted immediately afterward. Generated speech is treated
the same way. Secrets belong only in `.env`, which Git ignores.
