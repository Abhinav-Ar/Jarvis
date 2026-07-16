# Personal intelligence

ORION is an everyday personal intelligence layer first. Engineering, creative,
coding, and automation workers are specialists invoked only when the objective
requires them.

## Product priorities

1. Reduce cognitive load by remembering where information came from.
2. Connect authorized messages, contacts, calendar, mail, files, and services.
3. Answer ordinary questions through one conversational interface.
4. Prefer local retrieval and deterministic actions before paid cloud reasoning.
5. Preserve source, timestamp, confidence, and privacy boundaries.
6. Take initiative on safe prerequisites while leaving consequential decisions to
   the user.

## Personal timeline

`src/orion/personal_intelligence.py` normalizes communication records into local
SQLite events containing their source, external identifier, time, sender,
participants, channel, direction, content, and source metadata. Relationships are
represented separately from service-specific phone numbers, email addresses, and
aliases.

Common questions such as “When did Alex say he would pick me up?” use the local
fast lane. ORION resolves Alex through authorized Contacts data, searches the local
timeline, and answers with the smallest matching excerpt and its timestamp. This
path does not need a paid model call.

## Connector policy

- **Apple Messages:** local, read-only access to `~/Library/Messages/chat.db`.
  macOS Full Disk Access is required for the installed ORION menu application.
- **Apple Contacts:** resolves names and aliases to message identities through the
  native Contacts permission boundary.
- **Discord:** supports an explicitly authorized data-export folder. A future live
  connector must use Discord's supported bot/OAuth model; ORION does not scrape a
  user's account token.
- **Calendar and Mail:** native adapters remain available. Mail creates drafts and
  never sends without confirmation.

Personal source content is indexed locally. Broad thread dumps are prohibited;
retrieval returns only the excerpts needed for the active question.

## Permission setup

Open the ORION menu and choose **Full Disk Access for Messages…**. Add or enable
`Jarvis Menu.app` and the Python 3.13 executable used by the background service
(`/opt/homebrew/opt/python@3.13/bin/python3.13`), then restart ORION. The menu's
Personal context line reports indexed events, known people, and ready sources.

To authorize a Discord export, set `ORION_DISCORD_EXPORT_DIR` in `.env` to the
folder containing the export. Restart ORION afterward.

## Next connector families

The same event contract can accept WhatsApp exports, Slack, Gmail, Google Calendar,
Notion, and other authorized sources without changing the conversational interface.
Each connector remains responsible for permissions, incremental synchronization,
source attribution, and deletion/revocation.
