# ORION for macOS

ORION — **One Really Intelligent Operating Network** — is a persistent, local-first
Mac operating assistant. It records a spoken phrase,
transcribes it locally on Apple silicon by default, reasons through the Responses API, executes bounded
tools when requested, and speaks the result through the Mac's audio output.

Say **“Hey ORION”** once to open a session. Follow-up requests and interruptions do
not need the wake phrase. Say **“Hey ORION, that’ll be all”** to close the current
conversation, or **“Hey ORION, log off”** to stop the background assistant.

The macOS service and permission bundle retain their original `com.jarvis.*` identifiers
and `~/Library/Application Support/Jarvis` storage path. This is intentional migration
compatibility: the product is ORION, while preserving those internal identifiers prevents
macOS from discarding the Screen Recording and Accessibility grants you already approved.

## Persistent operating architecture

ORION now runs six durable local subsystems around the existing action engine:

- **World model:** observations carry a source, confidence, timestamp, and expiry so
  stale screen or system state is not treated as current truth.
- **Goal supervisor:** every request becomes a persistent objective with ordered steps,
  success criteria, risk, evidence, and a lifecycle that follow-ups can resume.
- **Four-layer memory:** working memory for the live session, episodic task history,
  semantic preferences and facts, and procedural user-taught workflows.
- **Event monitor:** low battery, low disk, and scheduled-work watchers operate locally
  in the background and use cooldowns instead of repeatedly firing.
- **Adapter registry and intelligence router:** native and deterministic routes are
  preferred; Accessibility and local OCR precede vision; cloud reasoning is used only
  when the request actually needs it and remains subject to a daily cap.
- **Sanitized replay:** request, route, goal, response, and outcome records make failures
  reproducible without rerunning actions or storing secrets in the replay corpus.

Teach a procedure with a phrase such as: “Teach ORION a workflow named Focus Mode:
when I say start focus mode, open Notes, then mute notifications.” Ask “ORION status,”
“What are you working on?”, or “What workflows do you know?” for zero-cloud summaries.

### Generation workers

ORION can supervise long-running artifact workers rather than trying to perform
every task inside one voice response. The first worker is the Codex CLI bundled
with ChatGPT. An explicit request such as “Use Codex to implement the settings
screen in the Jarvis repository” starts an asynchronous workspace-write job,
returns a job identifier immediately, and leaves ORION responsive. ORION monitors
the process, records its final result, and sends a macOS notification when it
finishes. Generation never commits or pushes unless those actions are requested
separately. “What is Codex working on?” reports the latest job locally.

The same worker contract is intended for future CAD, 3D, document, media, data,
and simulation adapters: a bounded workspace, an explicit objective, progress,
an inspectable artifact, and separate approval for consequential publication.

### Verified action execution

Imperative requests are evidence-gated. ORION cannot satisfy an action request
with future-tense prose: the matching state-changing tool must run successfully,
while searches and inspections count only as supporting observations. If no
executable capability exists, ORION says that nothing changed and records a
capability gap instead of pretending to continue.

Explicit application-install requests use Homebrew's cask catalog through an
argument-safe background worker. ORION validates cask metadata, starts an
observable job, keeps its output under the private runtime folder, verifies the
installed cask/application, and posts a macOS notification when it finishes.
If the publisher rejects Homebrew's download, the same persistent job opens the
official HTTPS download in Safari, monitors the completed disk image, mounts it,
installs the application, and performs final verification. The originating task
remains linked to every phase and is completed only after that verification.
Ask “Is Blender installed yet?” to inspect the latest job without another install.

The menu-bar **Cloud Limit** item is a direct toggle. When on, the configured
rolling daily ceiling applies; when off, ORION allows cloud calls without its
local ceiling, although provider billing and account limits still apply.

### Capability families and objective composition

Users describe an outcome once; they do not create or select workers. ORION
compiles the objective against eight broad families and assembles a temporary
team from the smallest useful combination:

- Google Workspace — Drive, Sheets, Docs, and Slides
- Microsoft 365 — OneDrive, Excel, Word, PowerPoint, and Outlook
- Development — Codex, Git, GitHub, Xcode, and VS Code
- Creative — image, design, audio, video, and 3D production adapters
- Engineering and CAD — parametric models, drawings, simulation, and validation
- Business — budgets, invoices, forecasts, reports, and dashboards
- Research — current web and authorized local-document synthesis
- macOS — applications, windows, files, Apple apps, Shortcuts, and system state

Families are capability manifests, not fake integrations. The menu shows how
many are currently available. Families requiring a provider account, OAuth
grant, or installed application report that exact prerequisite. Once a family
adapter is authorized, every objective using it becomes available without
teaching a separate workflow.

The Google Workspace family includes an end-to-end budget generator. “Create a
Google Drive spreadsheet for my finances and set it up as a monthly budget”
creates Dashboard, Transactions, Budget, and Categories sheets; formulas,
currency formatting, category and transaction-type validation, frozen headers,
automatic sizing, and a Budget-vs-Actual chart; then returns the Drive URL.

Authorize it in `.env` with either a short-lived `GOOGLE_ACCESS_TOKEN` or a
refresh-token configuration:

```dotenv
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=
```

The OAuth grant needs Drive-file, Sheets, Docs, and Slides scopes. ORION never
stores those credentials in its memory, replay, diagnostics, or model context.

### Native creative and engineering workers

ORION can generate durable, editable projects through installed application APIs:

- Blender: structured scenes, procedural component detail, physical accent-light placement, neutral cinematic lighting, cameras, safe in-place refinements with backups, `.blend`, and rendered previews.
- FreeCAD: structured parametric solids, editable `.FCStd`, and STEP/STL exports.
- OpenSCAD: self-contained `.scad` source with verified STL compilation.
- DaVinci Resolve: project settings, media import, media pools, timelines, and saved Resolve projects.

Generated files and manifests are stored under `~/Documents/ORION Projects`. Each
worker requires an explicit creation request, publishes compact background progress,
and verifies its native artifacts before ORION reports completion.

## Capabilities

### Conversation and live information

- Spoken or typed conversations with session memory
- Current web research through OpenAI web search
- Weather for any named location through Open-Meteo
- Open web or image searches in the default browser
- Inspect local Git changes, form a meaningful commit message, commit, and push
  when the user explicitly requests the complete operation
- Plan multi-step goals, insert safe prerequisites, journal tool evidence, recover
  from failed steps, and audit success criteria before reporting completion
- Show live hearing, planning, working, checking, speaking, needs-input, and error
  states through the menu bar and a compact translucent full-display HUD
- Present the active voice session as a bounded live chat showing both user and
  Jarvis messages, reset cleanly whenever Jarvis starts
- Keep the HUD visible during screen inspection while excluding only Jarvis's
  overlay windows from the visual capture
- Require a confirmed “Jarvis” wake phrase to open a conversation; follow-up turns
  and interruptions remain active until dismissal, while full logoff requires the
  wake phrase again
- Write rotated structured diagnostic events with request IDs, timings, plans,
  tool results, display mappings, speech playback, and redacted failures
- Speak selected high-value milestones during longer tasks while keeping routine
  clicks and inspections in the visual telemetry feed
- Route common local commands instantly and skip full planning and auditing for
  straightforward single-step requests
- Spoken responses through the built-in macOS voice by default, with optional OpenAI text-to-speech

### Mac control

- Open installed applications
- Detect and exit native fullscreen when necessary, then move and resize one or
  two app/browser windows into a verified display-aware work stage and restore
  their original frames and fullscreen state when the session ends
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

## Local-first persistent agent platform

Jarvis now maintains a local SQLite agent database in `.runtime/agent.db` with:

- user-authorized durable memories with explicit remember and forget operations;
- text indexing limited to folders explicitly listed in `JARVIS_INDEX_ROOTS`;
- reusable workflow definitions and a persistent background-job queue;
- integration and capability health state;
- read-only, reversible, and consequential safety classifications;
- actual cloud-call/token accounting and a daily hard call limit;
- durable task, step, result, and structured-failure history that later requests can search;
- deterministic prerequisite and recovery policies for known workflows;
- a small bounded retrieval packet instead of uploading the entire local database.

The menu-bar command center displays memory, indexed-file, workflow, and recent
cloud-call counts, along with the active project session. Routine speech uses the free macOS voice by default. Set
`JARVIS_LOCAL_SPEECH=0` only when intentionally choosing paid cloud TTS.

Microphone transcription uses `mlx-whisper` and the Apple-silicon GPU by default.
The first use downloads and caches the selected model. If the local model cannot
run, Jarvis may fall back to OpenAI transcription when
`JARVIS_ALLOW_TRANSCRIPTION_FALLBACK=1`. Set that value to `0` for a strict
no-cloud transcription policy.

Cloud escalation can be disabled entirely with `JARVIS_CLOUD_ENABLED=0`, or capped
with `JARVIS_MAX_CLOUD_CALLS_PER_DAY`. The same cap covers reasoning, planning,
screen vision, fallback transcription, and optional cloud speech. Known fast
commands and local transcription/speech never consume the cap.
Jarvis indexes no personal folder by default. To authorize folders, use a
colon-separated list on macOS, for example:

```dotenv
JARVIS_INDEX_ROOTS=/Users/you/Documents/Projects:/Users/you/Documents/Notes
JARVIS_INDEX_MAX_FILES=500
```

## Local execution and recovery

Known workflows are executed as local state machines rather than repeatedly
asking the language model what to do next. Every step records its action, result,
error code, and bounded evidence in SQLite. A later question such as “what failed
last time?” reads that record instead of guessing from the current screen.

The Git workflow now identifies the active repository, inspects its changes,
generates a non-empty commit summary locally, commits, pushes, and verifies the
working tree and remote synchronization. If command-line Git is rejected but the
request names GitHub Desktop, Jarvis makes one bounded attempt through GitHub
Desktop's signed-in session and verifies the repository afterward. It never
recommits while retrying a push.

For graphical applications, Jarvis can inspect, fill, and press controls by their
Accessibility labels. This costs no vision tokens and avoids coordinate drift.
When Electron hides its renderer Accessibility tree, Jarvis uses Apple's on-device
Vision OCR to read visible labels and identify context such as GitHub Desktop's
current repository. Paid screenshot vision is the final fallback only when local
labels and OCR are insufficient. Passwords, security codes, tokens, payment fields, and
unconfirmed submissions remain prohibited.

The HUD is a click-through translucent overlay: conversation stays in the upper
corner, action telemetry and the dependency path stay near the lower corners, and
the center remains available for the working application. Futuristic grid, scan,
and command-core animation provide state visibility without an opaque sidebar.
Hovering over conversation or telemetry temporarily enables scrolling; every
other region remains click-through. When Jarvis opens apps for visible work, it
normalizes native fullscreen, identifies processes by bundle and process aliases,
sets frames through Accessibility, and verifies the resulting coordinates. Two
named apps can be tiled on the same display. Original window frames and fullscreen
state are restored after “Hey Jarvis, that’ll be all,” logoff, or an explicit restore.

Structured recovery also covers foreground activation, unsaved-work dialogs,
Spotify playback-device activation, missing project targets, network failures,
and required permissions. Known blockers return a direct local explanation;
unfamiliar failures alone escalate to cloud reasoning.

## Project sessions

Project sessions are the first complete persistent workflow. They give Jarvis a
durable concept of what you are working on instead of treating every command as
an isolated chat. Say any of these:

- “Jarvis, start project Jarvis” to record the branch and Git state, locally index
  the repository, and open GitHub Desktop and Visual Studio Code when installed.
- “Project status” during the active conversation to hear the current branch and
  changed-file count without a model call.
- “Resume project Jarvis” to begin from the most recently stored session notes.
- “End project session” to save the ending state and a handoff note. Jarvis warns
  about uncommitted work and never commits merely because a session ended.

The active project survives app restarts and appears in the menu-bar command
center. Project files stay local except for the small, relevant excerpts that are
retrieved for a request which actually needs cloud reasoning.

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
- **Screen & System Audio Recording** for on-demand visual screen inspection
- **Accessibility** for permission-gated clicking, typing, keys, scrolling, and
  reversible application-window positioning

Review these under System Settings → Privacy & Security. Denying one permission
only disables that related action.

The Jarvis menu provides direct shortcuts to the Screen Recording and
Accessibility panes. Add `~/Applications/Jarvis Menu.app` or enable
**Jarvis Menu** in both lists, then restart it
from the login service if macOS requests a restart. Desktop control defaults on
whenever Jarvis starts. Choosing **Disable Desktop Control** is an emergency stop
for the current session; the next Jarvis start defaults it back on. Desktop control does not
change the menu color; colors reflect live activity, while red means stopped or
errored.

## Run

Recommended first test:

```sh
./start.sh --text
```

Voice mode:

```sh
./start.sh
```

## Always-on background service (macOS)

The first implementation of the final local architecture is included as a user
LaunchAgent. It runs in your signed-in graphical session, starts at login, keeps
Jarvis alive after crashes, writes local logs, and stays stopped after the clean
“Jarvis, log off” command.

The installer deploys a private runtime copy to
`~/Library/Application Support/Jarvis`. This is necessary because macOS blocks
background agents from reliably reading executables under the protected
`Documents` directory. Re-run the installer after changing source or `.env` to
update the deployed copy.

Installation also builds an ad-hoc-signed native Swift menu-bar controller at
`~/Applications/Jarvis Menu.app`. A
cyan `● Jarvis` means it is listening; red means it is stopped. Its menu offers
Start, Stop, Restart, current status, recent logs, and the runtime folder. Stop
unloads the voice service until Start is selected; it does not auto-restart. The
controller itself intentionally has no Quit option and is automatically restored
if it crashes. It has no Dock icon and starts at login with the voice service.

Install it only after normal voice mode works and macOS microphone permission has
already been granted:

```sh
./install-background.sh
```

Manage it with:

```sh
./jarvisctl status
./jarvisctl logs           # print recent entries and return
./jarvisctl logs --follow  # continuous live stream; Control-C exits the view
./jarvisctl stop
./jarvisctl start
./jarvisctl restart
```

Remove the login service without deleting Jarvis or its logs:

```sh
./uninstall-background.sh
```

This is a local background assistant with a native menu controller. macOS must be
awake and the user logged in for microphone and desktop access. Web addresses are
opened through direct browser navigation; screen inspection and coordinate-based
actions are reserved as fallbacks for apps without a structured integration.

Say “Jarvis” followed by a request. Press Control-C to stop.
Say “Jarvis, log off” to end the assistant cleanly without using Control-C.

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
items, weights recent plays and four-week affinity first, and retries rate limits
and temporary failures. Existing-playlist playback is a separate action and can
never create a playlist. “Unheard” means absent
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
