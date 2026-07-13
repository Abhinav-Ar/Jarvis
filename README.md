# Jarvis for macOS

Jarvis is a voice-driven Mac and personal assistant. It records a spoken phrase,
transcribes it with OpenAI, reasons through the Responses API, executes bounded
tools when requested, and speaks the result through the Mac's audio output.

## Capabilities

### Conversation and live information

- Spoken or typed conversations with session memory
- Current web research through OpenAI web search
- Weather for any named location through Open-Meteo
- Open web or image searches in the default browser
- Spoken responses through OpenAI text-to-speech

### Mac control

- Open installed applications
- Set output volume
- Read or replace the clipboard when explicitly requested
- Report battery, power, CPU, memory, disk, and macOS status
- Show local notifications
- Search the Spotlight file index and return matching paths
- List or run Apple Shortcuts, including shortcuts for Home devices and scenes

### Apple apps

- Create Apple Reminders
- Create Apple Notes
- Create Apple Calendar events
- Look up explicitly named Apple Contacts
- Compose visible Apple Mail drafts; Jarvis never sends them

### Optional services

- Spotify playback, navigation, current-track information, and private discovery playlists built locally from your taste
- Todoist task creation with natural-language due dates
- Home Assistant lights, switches, scenes, scripts, media players, and climate power

Jarvis deliberately has no unrestricted terminal tool, file deletion tool,
purchase tool, password access, or silent email/message sending.

## Install

```sh
./setup.sh
```

The installer creates a private `.venv`, installs dependencies, and creates `.env`
from `.env.example`. Secrets in `.env` are ignored by Git.

## Credential checklist

Only the OpenAI key is required. Every other integration is optional and is
loaded only when used.

| Capability | Values in `.env` | Where to obtain them |
|---|---|---|
| Core voice and AI | `OPENAI_API_KEY` | OpenAI Platform → API keys |
| Spotify | `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI` | Spotify Developer Dashboard |
| Todoist | `TODOIST_API_TOKEN` | Todoist Settings → Integrations → Developer |
| Home Assistant | `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_TOKEN` | Home Assistant profile → Long-lived access tokens |

You do **not** need an OpenAI assistant ID, thread ID, organization ID, project
ID, weather key, Google key, Apple developer ID, or macOS application password.

### OpenAI

Create an API key at <https://platform.openai.com/api-keys>, ensure the API
project has billing/model access, and place it in `.env`:

```dotenv
OPENAI_API_KEY=your_key_here
```

API usage is billed separately from a ChatGPT subscription.

### Spotify

Create an app at <https://developer.spotify.com/dashboard>. Add this exact URI
to its redirect allowlist:

```text
http://127.0.0.1:8888/callback
```

Copy the client ID and secret into `.env`. The first Spotify request opens its
OAuth approval page. Playback control generally needs Spotify Premium and an
active Spotify device.

### Todoist

Generate a personal API token from Todoist's developer integrations settings and
set `TODOIST_API_TOKEN`. No client ID is needed for this single-user setup.

### Home Assistant

Set the URL of your server and create a long-lived access token from your Home
Assistant profile. Jarvis allowlists a limited collection of service calls; it
does not accept arbitrary Home Assistant services.

## macOS permissions

No API keys are needed for Apple apps, but macOS asks you to approve access when
each feature is first used:

- **Microphone** for voice input
- **Automation** for Calendar, Reminders, Notes, Mail, and Contacts
- **Contacts** when looking someone up
- **Notifications** for local alerts
- Possibly **Files and Folders** or **Full Disk Access** if you want Spotlight
  results from protected locations

Review these under System Settings → Privacy & Security. Denying one permission
only disables that related action.

## Run

Recommended first test:

```sh
./start.sh --text
```

Voice mode:

```sh
./start.sh
```

Say “Jarvis” followed by a request. Press Control-C to stop.

```sh
./start.sh --no-hotword   # respond to every detected phrase
./start.sh --once         # handle one request and exit
./start.sh --list-devices # list microphone device numbers
```

Set `JARVIS_INPUT_DEVICE` in `.env` if the default microphone is wrong. Raise
`JARVIS_ENERGY_THRESHOLD` if noise activates recording; lower it if your voice
is not detected.

While speaking, Jarvis measures speaker echo and uses an adaptive barge-in
threshold. If interruption remains difficult, lower `JARVIS_BARGE_IN_THRESHOLD`.
If Jarvis interrupts itself, raise `JARVIS_BARGE_IN_THRESHOLD_RATIO`. When an
interruption is detected, the terminal prints the measured voice level and active
threshold to make calibration concrete.

## Example requests

- “Jarvis, research today's biggest AI announcement.”
- “Jarvis, open Visual Studio Code and set the volume to 35 percent.”
- “Jarvis, how are my battery and memory doing?”
- “Jarvis, remind me to renew my passport.”
- “Jarvis, add a calendar event tomorrow at 2 PM for one hour.”
- “Jarvis, draft an email to me@example.com about Friday's meeting.”
- “Jarvis, find my tax return PDF.”
- “Jarvis, play Spotify and tell me what song is on.”
- “Jarvis, make a private Spotify discovery playlist based on my taste.”
- “Jarvis, add submit expenses to Todoist, due Friday.”
- “Jarvis, turn off light.living_room through Home Assistant.”
- “Jarvis, run my Good Night shortcut.”

## Privacy

Audio and generated speech use temporary files that are deleted after each turn.
OpenAI processes transcripts and responses. Weather queries go to Open-Meteo;
configured optional actions go to their respective services. Clipboard, Contacts,
file search, and Apple app data are accessed only when the corresponding tool is
explicitly requested. Conversation memory lasts until Jarvis exits.

Spotify discovery processes listening metadata locally and sends only a success
summary to the language model. It paginates large libraries, inspects playlist
items Spotify permits, handles sparse history, excludes duplicates and non-track
items, and retries rate limits and temporary failures. “Unheard” means absent
from the history and accessible playlists Spotify exposes; Spotify does not
provide a complete lifetime listening ledger.

## Project layout

- `jarvis.py` — command-line loop and hotword behavior
- `audio.py` — microphone phrase capture and silence detection
- `assist.py` — OpenAI conversation, transcription, TTS, and tool orchestration
- `tools.py` — tool schemas, weather, search, and dispatch
- `mac_tools.py` — bounded native macOS and Apple-app actions
- `integrations.py` — Todoist and Home Assistant
- `spot.py` — lazy Spotify OAuth and playback control
