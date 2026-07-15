"""Safe, structured tools available to ORION."""

from __future__ import annotations

import os
import webbrowser
from urllib.parse import quote_plus

import requests

import diagnostics
import activity
import integrations
import mac_tools
import desktop
import git_tools
import project_workflow
import anticipation
import recovery
import execution_supervisor
import app_installer
from agent_platform import platform


ADVANCED_BLENDER_COMPONENT = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "operation": {"type": "string", "enum": ["primitive", "mesh", "extrude_profile", "lathe_profile", "curve_tube", "terrain"]},
        "primitive": {"type": "string", "enum": ["none", "cube", "cylinder", "sphere", "cone", "torus"]},
        "profile": {"type": "array", "maxItems": 64, "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}},
        "path": {"type": "array", "maxItems": 64, "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}},
        "vertices": {"type": "array", "maxItems": 256, "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}},
        "faces": {"type": "array", "maxItems": 256, "items": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 8}},
        "dimensions": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "location": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "rotation": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "depth": {"type": "number"}, "radius": {"type": "number"}, "segments": {"type": "integer"},
        "color": {"type": "string"}, "metallic": {"type": "number"}, "roughness": {"type": "number"}, "emission": {"type": "number"},
        "bevel": {"type": "number"}, "subdivision": {"type": "integer"},
        "solidify": {"type": "number"}, "mirror_axis": {"type": "string", "enum": ["none", "x", "y", "z"]},
        "array_count": {"type": "integer"},
        "array_offset": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "smooth": {"type": "boolean"}, "role": {"type": "string", "enum": ["object", "cutter"]},
        "design_intent": {"type": "string", "description": "The requirement or design principle this component exists to satisfy."},
    },
    "required": ["name", "operation", "primitive", "profile", "path", "vertices", "faces", "dimensions", "location", "rotation", "depth", "radius", "segments", "color", "metallic", "roughness", "emission", "bevel", "subdivision", "solidify", "mirror_axis", "array_count", "array_offset", "smooth", "role", "design_intent"],
    "additionalProperties": False,
}


TOOL_DEFINITIONS = [
    {"type": "web_search"},
    {
        "type": "function",
        "name": "get_weather",
        "description": "Get current weather and today's forecast for a named place.",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "open_search",
        "description": "Open a web or image search in the user's default browser.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kind": {"type": "string", "enum": ["web", "images"]},
            },
            "required": ["query", "kind"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "spotify_control",
        "description": "Control Spotify, play a requested song, or report the current track. For play, query is the song or empty to resume; otherwise query is empty. Never use this tool for playlist creation or playlist-name playback.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "next", "previous", "current"],
                },
                "query": {"type": "string"},
            },
            "required": ["action", "query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "spotify_play_playlist",
        "description": "Play one of the user's owned or collaborative Spotify playlists. Followed playlists owned by others are excluded from 'my playlists'. Set name to the requested playlist name, or empty only for any/random. This never creates a playlist.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "spotify_create_discovery_playlist",
        "description": "Create a new private Spotify discovery playlist using recent listening taste. Call ONLY when the requested action verb is create, make, build, or generate. Never call when the request verb is play, open, start, resume, or listen—even if the existing playlist is named Discovery Playlist.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "open_application",
        "description": "Open an installed macOS application and bring it to the foreground.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "quit_application",
        "description": "Quit a named macOS application normally and verify it actually exited. Use only when the user explicitly asks to close or quit the application. It does not force-quit or discard unsaved work.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "browser_navigate",
        "description": "Open a website directly in a Mac browser and bring the browser forward. Prefer this over desktop clicking or typing for URLs.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "browser": {"type": "string"},
            },
            "required": ["url", "browser"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "install_application",
        "description": "Install a trusted macOS application through Homebrew, track it as a background job, and verify the app bundle. Use for explicit install or download-and-install requests. The explicit request itself counts as confirmation; never use browser navigation as a substitute.",
        "parameters": {
            "type": "object",
            "properties": {"application": {"type": "string"}, "confirmed": {"type": "boolean"}},
            "required": ["application", "confirmed"], "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "installation_status",
        "description": "Check an installation job or verify whether a trusted application is installed.",
        "parameters": {
            "type": "object",
            "properties": {"application": {"type": "string"}, "job_id": {"type": "string"}},
            "required": ["application", "job_id"], "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "set_system_volume",
        "description": "Set the Mac output volume from 0 to 100.",
        "parameters": {
            "type": "object",
            "properties": {"level": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["level"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "clipboard",
        "description": "Read the clipboard or replace it with explicitly requested text.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["read", "write"]},
                "text": {"type": "string"},
            },
            "required": ["action", "text"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "system_status",
        "description": "Report Mac battery, CPU, memory, disk, and operating-system status.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "show_notification",
        "description": "Show a local macOS notification.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "message": {"type": "string"}},
            "required": ["title", "message"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "create_reminder",
        "description": "Create an item in Apple Reminders. Use list_name Reminders unless requested otherwise.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "list_name": {"type": "string"}},
            "required": ["title", "list_name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "create_note",
        "description": "Create an Apple Note. Use folder Notes unless requested otherwise.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "folder": {"type": "string"},
            },
            "required": ["title", "body", "folder"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "create_calendar_event",
        "description": "Create an Apple Calendar event. Start must be a local ISO date/time. Use calendar Calendar unless specified.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string"},
                "duration_minutes": {"type": "integer", "minimum": 1},
                "calendar": {"type": "string"},
            },
            "required": ["title", "start", "duration_minutes", "calendar"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "todoist_create_task",
        "description": "Create a Todoist task. due_string may be empty or natural language such as tomorrow at 3pm.",
        "parameters": {
            "type": "object",
            "properties": {"content": {"type": "string"}, "due_string": {"type": "string"}},
            "required": ["content", "due_string"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "home_assistant_control",
        "description": "Control an allowlisted Home Assistant entity and service.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "enum": ["light", "switch", "scene", "script", "media_player", "climate"]},
                "service": {"type": "string"},
                "entity_id": {"type": "string"},
            },
            "required": ["domain", "service", "entity_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "create_email_draft",
        "description": "Create and visibly open an Apple Mail draft. This never sends the email.",
        "parameters": {
            "type": "object",
            "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            "required": ["to", "subject", "body"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "find_contact",
        "description": "Look up an explicitly named person in Apple Contacts.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "find_files",
        "description": "Search this Mac's Spotlight index for files matching a user query; returns up to 20 paths.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "apple_shortcuts",
        "description": "List or run a named Apple Shortcut, including shortcuts that control Apple Home devices and scenes. Only run a shortcut explicitly requested by the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "run"]},
                "name": {"type": "string"},
            },
            "required": ["action", "name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "desktop_inspect",
        "description": "Capture and visually inspect the Mac for an explicit request. When interacting with a named app, application MUST be its exact name; ORION brings it forward, captures only that app's display, and locks clicks to that display. Use an empty application only for read-only inspection across all displays.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}, "application": {"type": "string"}},
            "required": ["question", "application"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "git_repositories",
        "description": "List local Git repositories and how many changed files each has. Use this to identify the intended repository instead of guessing from a GUI.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "git_status",
        "description": "Inspect a repository's branch, changed files, and diff summary before forming a commit message.",
        "parameters": {
            "type": "object",
            "properties": {"repository": {"type": "string"}},
            "required": ["repository"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "git_commit_and_push",
        "description": "Stage all changes, create a commit with a meaningful non-empty message, and push it. Set confirmed true only when the user explicitly requested both commit and push. Inspect Git status first.",
        "parameters": {
            "type": "object",
            "properties": {
                "repository": {"type": "string"},
                "message": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["repository", "message", "confirmed"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "git_commit",
        "description": "Stage all changes and create a local commit without pushing. Use when the user requests commit but does not request push. Inspect status first and infer a useful message. Set confirmed true only for an explicit commit request.",
        "parameters": {
            "type": "object",
            "properties": {
                "repository": {"type": "string"},
                "message": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["repository", "message", "confirmed"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "git_push",
        "description": "Push the current branch without creating another commit. Use to retry a previously failed push. Set confirmed true only when the user explicitly requested a push.",
        "parameters": {
            "type": "object",
            "properties": {"repository": {"type": "string"}, "confirmed": {"type": "boolean"}},
            "required": ["repository", "confirmed"], "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function", "name": "desktop_accessibility_inspect",
        "description": "Inspect labelled controls in a named Mac application locally without a screenshot or vision-model call. Sensitive field values are redacted.",
        "parameters": {"type": "object", "properties": {"application": {"type": "string"}, "selector": {"type": "string"}}, "required": ["application", "selector"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "desktop_local_ocr",
        "description": "Read visible text in a named application locally with Apple Vision. Use before paid screenshot analysis when labelled Accessibility controls are unavailable.",
        "parameters": {"type": "object", "properties": {"application": {"type": "string"}}, "required": ["application"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "desktop_accessibility_set",
        "description": "Set a non-sensitive labelled text field in a named application. The user must have explicitly requested the typing action.",
        "parameters": {"type": "object", "properties": {"application": {"type": "string"}, "selector": {"type": "string"}, "text": {"type": "string"}, "confirmed": {"type": "boolean"}}, "required": ["application", "selector", "text", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "desktop_accessibility_press",
        "description": "Press a labelled non-sensitive control in a named application. Requires explicit authorization for the requested action.",
        "parameters": {"type": "object", "properties": {"application": {"type": "string"}, "selector": {"type": "string"}, "confirmed": {"type": "boolean"}}, "required": ["application", "selector", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "desktop_window_arrange",
        "description": "Normalize fullscreen state, then create a verified, reversible workspace for one or two named applications behind the click-through ORION HUD. For two apps, prefer the largest connected display and balanced usable space; if app minimum sizes prevent a balanced horizontal split, use an even vertical stage rather than a cramped lopsided layout.",
        "parameters": {
            "type": "object",
            "properties": {
                "applications": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2},
                "confirmed": {"type": "boolean"},
            },
            "required": ["applications", "confirmed"], "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function", "name": "desktop_window_restore",
        "description": "Restore application windows previously staged by ORION to their original frames.",
        "parameters": {
            "type": "object",
            "properties": {
                "applications": {"type": "array", "items": {"type": "string"}},
                "confirmed": {"type": "boolean"},
            },
            "required": ["applications", "confirmed"], "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "desktop_action",
        "description": "Perform one bounded Mac input action after screen inspection. Desktop control must be visibly enabled in the menu. Never interact with passwords, authentication codes, payment data, purchases, deletions, messages, or final form submission without explicit confirmation. Coordinates use screenshot pixels.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["click", "type", "key", "scroll"]},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "text": {"type": "string"},
                "key": {"type": "string", "enum": ["return", "enter", "tab", "escape", "space", "delete"]},
                "amount": {"type": "integer"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["action", "x", "y", "text", "key", "amount", "confirmed"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function", "name": "agent_status",
        "description": "Report ORION's complete local platform status, including goals, world state, layered memory, adapters, workflows, jobs, capabilities, replay, and cloud policy.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "task_history_search",
        "description": "Search ORION's durable local task and failure history. Use when the user asks what happened, what failed, or what problem ORION encountered previously.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query", "limit"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "memory_store",
        "description": "Store a durable personal preference or fact only when the user explicitly asks ORION to remember it.",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}, "required": ["key", "value"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "memory_search",
        "description": "Search user-authorized durable ORION memory for relevant preferences or facts.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "memory_forget",
        "description": "Delete one named durable memory only when the user explicitly asks ORION to forget it.",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "local_knowledge_search",
        "description": "Search only files the user explicitly authorized ORION to index locally.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "project_session_start",
        "description": "Start a persistent local project session for a named Git repository, open available project apps, index its local context, and record starting state.",
        "parameters": {"type": "object", "properties": {"repository": {"type": "string"}}, "required": ["repository"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "project_session_resume",
        "description": "Resume a named project using its prior local session journal and current Git state.",
        "parameters": {"type": "object", "properties": {"repository": {"type": "string"}}, "required": ["repository"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "project_session_status",
        "description": "Report the active project session and current Git changes.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "project_session_close",
        "description": "Close the active project session, persist a local journal, and warn about uncommitted work without committing automatically.",
        "parameters": {"type": "object", "properties": {"notes": {"type": "string"}}, "required": ["notes"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "orion_goal_status",
        "description": "Report ORION's current persistent objective and its known steps.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "orion_world_state",
        "description": "Read ORION's fresh local world model, including system state and observed context.",
        "parameters": {"type": "object", "properties": {"prefix": {"type": "string"}}, "required": ["prefix"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "orion_workflows",
        "description": "List workflows ORION knows, including user-taught procedures.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "orion_teach_workflow",
        "description": "Teach ORION a reusable procedure only when the user explicitly asks. Store its name, spoken trigger, and ordered steps.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "trigger": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}}}, "required": ["name", "trigger", "steps"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "codex_generate",
        "description": "Start an asynchronous Codex worker to generate or modify code in a named Git repository. Use only when the user explicitly asks ORION to build, implement, generate, refactor, or fix code. This may edit files but never commits or pushes them.",
        "parameters": {"type": "object", "properties": {"repository": {"type": "string"}, "instruction": {"type": "string"}, "confirmed": {"type": "boolean"}}, "required": ["repository", "instruction", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "generation_status",
        "description": "Report the latest or named background artifact-generation job and its result.",
        "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "generation_cancel",
        "description": "Cancel a running generation job only when the user explicitly requests cancellation.",
        "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}, "confirmed": {"type": "boolean"}}, "required": ["job_id", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "capability_families_status",
        "description": "Report ORION's broad capability families, available adapters, and exact missing prerequisites.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "objective_compile",
        "description": "Compile one user objective into a temporary cross-family worker team. Use to determine capabilities and prerequisites without asking the user to name workers.",
        "parameters": {"type": "object", "properties": {"objective": {"type": "string"}}, "required": ["objective"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "google_drive_search",
        "description": "Search the user's authorized Google Drive by filename.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query", "limit"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "google_create_spreadsheet",
        "description": "Create and verify a polished Google spreadsheet in Drive. For finance requests choose the budget template, which builds Dashboard, Transactions, Budget, and Categories sheets with formulas, validation, formatting, and a chart. One explicit user request confirms creation.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "template": {"type": "string", "enum": ["blank", "budget", "expense_tracker"]}, "currency": {"type": "string"}, "confirmed": {"type": "boolean"}}, "required": ["title", "template", "currency", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "google_create_document",
        "description": "Create a Google Doc in Drive with generated content when the user explicitly requests the document.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}, "confirmed": {"type": "boolean"}}, "required": ["title", "content", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "google_create_presentation",
        "description": "Create a Google Slides presentation in Drive when the user explicitly requests it.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "confirmed": {"type": "boolean"}}, "required": ["title", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "design_project_plan",
        "description": "Create and persist the mandatory engineering design brief for a detailed 3D, product, CAD, assembly, or 3D-print project. Use web research first, then compare three concepts and call this before any advanced modeling worker. This is a prerequisite, not a completed model.",
        "parameters": {"type": "object", "properties": {
            "project_name": {"type": "string"}, "intent": {"type": "string"},
            "artifact_type": {"type": "string", "enum": ["visual_model", "product_concept", "functional_part", "3d_print", "assembly"]},
            "intended_use": {"type": "string"},
            "target_dimensions": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            "units": {"type": "string", "enum": ["mm", "cm", "m"]}, "material": {"type": "string"},
            "manufacturing_process": {"type": "string", "enum": ["visual_only", "fdm_3d_print", "resin_3d_print", "cnc", "fabrication", "general"]},
            "requirements": {"type": "array", "minItems": 5, "maxItems": 20, "items": {"type": "string"}},
            "constraints": {"type": "array", "minItems": 3, "maxItems": 15, "items": {"type": "string"}},
            "precedents": {"type": "array", "minItems": 2, "maxItems": 8, "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "source_url": {"type": "string"},
                "learned_principle": {"type": "string"}, "avoid_copying": {"type": "string"}
            }, "required": ["name", "source_url", "learned_principle", "avoid_copying"], "additionalProperties": False}},
            "concepts": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "strategy": {"type": "string"}, "strengths": {"type": "string"}, "risks": {"type": "string"},
                "function": {"type": "number", "minimum": 1, "maximum": 10},
                "manufacturability": {"type": "number", "minimum": 1, "maximum": 10},
                "usability": {"type": "number", "minimum": 1, "maximum": 10},
                "visual_coherence": {"type": "number", "minimum": 1, "maximum": 10},
                "originality": {"type": "number", "minimum": 1, "maximum": 10}
            }, "required": ["name", "strategy", "strengths", "risks", "function", "manufacturability", "usability", "visual_coherence", "originality"], "additionalProperties": False}},
            "selected_concept": {"type": "string"}, "selection_rationale": {"type": "string"},
            "design_principles": {"type": "array", "minItems": 4, "maxItems": 12, "items": {"type": "string"}},
            "print_settings": {"type": "object", "properties": {
                "nozzle_mm": {"type": "number"}, "layer_height_mm": {"type": "number"},
                "min_wall_mm": {"type": "number"}, "clearance_mm": {"type": "number"},
                "max_overhang_deg": {"type": "number"}, "load_case": {"type": "string"}
            }, "required": ["nozzle_mm", "layer_height_mm", "min_wall_mm", "clearance_mm", "max_overhang_deg", "load_case"], "additionalProperties": False},
            "confirmed": {"type": "boolean"}
        }, "required": ["project_name", "intent", "artifact_type", "intended_use", "target_dimensions", "units", "material", "manufacturing_process", "requirements", "constraints", "precedents", "concepts", "selected_concept", "selection_rationale", "design_principles", "print_settings", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "blender_create_project",
        "description": "Create and verify an editable Blender project from structured geometry, materials, camera, lighting, and an optional rendered preview. Use only for an explicit project-creation request.",
        "parameters": {"type": "object", "properties": {
            "project_name": {"type": "string"}, "description": {"type": "string"},
            "objects": {"type": "array", "maxItems": 50, "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "type": {"type": "string", "enum": ["cube", "sphere", "cylinder", "cone", "torus", "text"]},
                "dimensions": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "location": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "rotation": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "color": {"type": "string"}, "metallic": {"type": "number"}, "roughness": {"type": "number"}, "text": {"type": "string"}
            }, "required": ["name", "type", "dimensions", "location", "rotation", "color", "metallic", "roughness", "text"], "additionalProperties": False}},
            "render": {"type": "boolean"},
            "lighting_color": {"type": "string", "description": "Hex color for general scene illumination. Keep this neutral white unless the user explicitly requests the entire environment be color-washed."},
            "lighting_strength": {"type": "number", "minimum": 0.1, "maximum": 1.6},
            "accent_style": {"type": "string", "enum": ["none", "desk_perimeter", "under_desk", "monitor_backlight"], "description": "Physical placement for requested neon/RGB/accent illumination; never fake a light with a sphere object."},
            "accent_color": {"type": "string", "description": "Hex color of physical accent strips."},
            "accent_strength": {"type": "number", "minimum": 0.1, "maximum": 3.0},
            "confirmed": {"type": "boolean"}
        }, "required": ["project_name", "description", "objects", "render", "lighting_color", "lighting_strength", "accent_style", "accent_color", "accent_strength", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "blender_refine_project",
        "description": "Refine the active verified ORION Blender project in place while preserving its authored geometry. Use for follow-ups such as add, change, retry, replace, or adjust lighting. It can add procedural desk/keyboard detail, replace generated accent lights, rerender, save, and reopen the exact project.",
        "parameters": {"type": "object", "properties": {
            "project_name": {"type": "string"}, "description": {"type": "string"},
            "accent_style": {"type": "string", "enum": ["none", "desk_perimeter", "under_desk", "monitor_backlight"]},
            "accent_color": {"type": "string"}, "accent_strength": {"type": "number", "minimum": 0.1, "maximum": 3.0},
            "render": {"type": "boolean"}, "confirmed": {"type": "boolean"}
        }, "required": ["project_name", "description", "accent_style", "accent_color", "accent_strength", "render", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "blender_create_advanced_project",
        "description": "Create a detailed editable Blender project from an approved engineering design brief using safe procedural modeling: explicit vertex/face topology, profiles, revolved surfaces, curves, booleans, arrays, and modifier stacks. Use for product concepts and visual models; route dimensional printable parts to FreeCAD or OpenSCAD.",
        "parameters": {"type": "object", "properties": {
            "project_name": {"type": "string"}, "description": {"type": "string"}, "design_brief_id": {"type": "string"},
            "components": {"type": "array", "minItems": 1, "maxItems": 120, "items": ADVANCED_BLENDER_COMPONENT},
            "booleans": {"type": "array", "maxItems": 50, "items": {"type": "object", "properties": {
                "target": {"type": "string"}, "cutter": {"type": "string"},
                "operation": {"type": "string", "enum": ["DIFFERENCE", "UNION", "INTERSECT"]}
            }, "required": ["target", "cutter", "operation"], "additionalProperties": False}},
            "world_color": {"type": "string"}, "accent_color": {"type": "string"},
            "render": {"type": "boolean"}, "confirmed": {"type": "boolean"}
        }, "required": ["project_name", "description", "design_brief_id", "components", "booleans", "world_color", "accent_color", "render", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "native_project_open",
        "description": "Open and visibly load the exact editable file for a verified ORION native project. Use this instead of open_application when the user asks to open, show, or load a Blender, FreeCAD, or OpenSCAD project.",
        "parameters": {"type": "object", "properties": {
            "application": {"type": "string", "enum": ["Blender", "FreeCAD", "OpenSCAD"]},
            "project_name": {"type": "string", "description": "Exact project name, or empty to open the newest verified project for that application."}
        }, "required": ["application", "project_name"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "freecad_create_project",
        "description": "Create and verify an editable FreeCAD document containing structured parametric solids and export it as STEP or STL. Use only for an explicit CAD creation request.",
        "parameters": {"type": "object", "properties": {
            "project_name": {"type": "string"}, "description": {"type": "string"}, "design_brief_id": {"type": "string"},
            "parts": {"type": "array", "maxItems": 100, "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "type": {"type": "string", "enum": ["box", "cylinder", "sphere", "cone", "profile_extrusion", "revolved_profile"]},
                "dimensions": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "position": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "rotation": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "profile": {"type": "array", "maxItems": 64, "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}},
                "operation": {"type": "string", "enum": ["body", "add", "cut", "intersect"]},
                "target": {"type": "string"}, "fillet": {"type": "number"},
                "design_intent": {"type": "string"}
            }, "required": ["name", "type", "dimensions", "position", "rotation", "profile", "operation", "target", "fillet", "design_intent"], "additionalProperties": False}},
            "export_format": {"type": "string", "enum": ["step", "stl"]}, "confirmed": {"type": "boolean"}
        }, "required": ["project_name", "description", "design_brief_id", "parts", "export_format", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "openscad_create_project",
        "description": "Create a self-contained editable OpenSCAD source project and compile it into a verified STL. Use for explicit code-driven parametric CAD generation.",
        "parameters": {"type": "object", "properties": {
            "project_name": {"type": "string"}, "description": {"type": "string"}, "design_brief_id": {"type": "string"},
            "source": {"type": "string"}, "confirmed": {"type": "boolean"}
        }, "required": ["project_name", "description", "design_brief_id", "source", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "resolve_create_project",
        "description": "Create and verify a DaVinci Resolve project, project settings, media pool, and editable timeline through Blackmagic's official local scripting API. Use only when explicitly requested.",
        "parameters": {"type": "object", "properties": {
            "project_name": {"type": "string"}, "timeline_name": {"type": "string"},
            "media_paths": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
            "width": {"type": "integer"}, "height": {"type": "integer"}, "fps": {"type": "integer"},
            "confirmed": {"type": "boolean"}
        }, "required": ["project_name", "timeline_name", "media_paths", "width", "height", "fps", "confirmed"], "additionalProperties": False},
        "strict": True,
    },
]


TOOL_GROUPS = {
    "web": {"__web_search__", "get_weather", "open_search", "browser_navigate"},
    "spotify": {"spotify_control", "spotify_play_playlist", "spotify_create_discovery_playlist"},
    "mac": {"open_application", "native_project_open", "quit_application", "set_system_volume", "clipboard", "system_status", "show_notification"},
    "productivity": {
        "create_reminder", "create_note", "create_calendar_event", "todoist_create_task",
        "create_email_draft", "find_contact", "find_files", "apple_shortcuts",
    },
    "home": {"home_assistant_control"},
    "desktop": {"open_application", "desktop_inspect", "desktop_action", "desktop_accessibility_inspect", "desktop_local_ocr", "desktop_accessibility_set", "desktop_accessibility_press", "desktop_window_arrange", "desktop_window_restore"},
    "git": {"open_application", "git_repositories", "git_status", "git_commit", "git_commit_and_push", "git_push", "desktop_accessibility_inspect", "desktop_local_ocr", "desktop_accessibility_set", "desktop_accessibility_press", "desktop_window_arrange", "desktop_window_restore"},
    "agent": {"agent_status", "task_history_search", "memory_store", "memory_search", "memory_forget", "local_knowledge_search", "orion_goal_status", "orion_world_state", "orion_workflows", "orion_teach_workflow"},
    "project": {"project_session_start", "project_session_resume", "project_session_status", "project_session_close", "git_status"},
    "generation": {"codex_generate", "generation_status", "generation_cancel", "git_repositories", "git_status"},
    "capabilities": {"capability_families_status", "objective_compile"},
    "google_workspace": {"objective_compile", "google_drive_search", "google_create_spreadsheet", "google_create_document", "google_create_presentation", "browser_navigate"},
    "software": {"install_application", "installation_status"},
    "native_projects": {"__web_search__", "design_project_plan", "blender_create_project", "blender_refine_project", "blender_create_advanced_project", "freecad_create_project", "openscad_create_project", "resolve_create_project", "native_project_open", "desktop_inspect", "find_files", "open_application", "desktop_window_arrange"},
}

MUTATING_TOOLS = {
    "open_search", "open_application", "quit_application", "browser_navigate",
    "install_application", "set_system_volume", "show_notification",
    "spotify_play_playlist", "spotify_create_discovery_playlist",
    "create_reminder", "create_note", "create_calendar_event", "todoist_create_task",
    "home_assistant_control", "create_email_draft", "apple_shortcuts",
    "desktop_action", "desktop_accessibility_set", "desktop_accessibility_press",
    "desktop_window_arrange", "desktop_window_restore",
    "git_commit_and_push", "git_commit", "git_push",
    "memory_store", "memory_forget", "orion_teach_workflow",
    "codex_generate", "generation_cancel",
    "google_create_spreadsheet", "google_create_document", "google_create_presentation",
    "design_project_plan", "blender_create_project", "blender_refine_project", "blender_create_advanced_project", "freecad_create_project", "openscad_create_project", "resolve_create_project", "native_project_open",
    "project_session_start", "project_session_resume", "project_session_close",
}


def is_action_evidence(name: str, arguments: dict, result: dict) -> bool:
    """Only a successful state-changing capability can prove an action occurred."""
    if not result.get("ok"):
        return False
    if name == "clipboard":
        return arguments.get("action") == "write"
    if name == "spotify_control":
        return arguments.get("action") in {"play", "pause", "next", "previous"}
    return name in MUTATING_TOOLS


def select_definitions(request: str) -> list[dict]:
    """Send only tools relevant to this turn, keeping prompts small and choices clear."""
    text = request.lower()
    selected: set[str] = set()
    routes = (
        (("spotify", "playlist", "song", "music", "track", "album", "artist"), "spotify"),
        (("github", "git ", "repository", "repo", "commit", "push", "branch"), "git"),
        (("screen", "desktop", "click", "type into", "what do you see", "fill out"), "desktop"),
        (("blender", "freecad", "free cad", "openscad", "open scad", "davinci", "da vinci", "resolve"), "desktop"),
        (("weather", "news", "search", "website", "url", ".com", "safari", "browser"), "web"),
        (("reminder", "note", "calendar", "todoist", "email", "contact", "file", "shortcut"), "productivity"),
        (("light", "thermostat", "home assistant", "switch"), "home"),
        (("open ", "launch ", "close ", "quit ", "exit ", "volume", "clipboard", "battery", "system status", "notification"), "mac"),
        (("remember", "forget", "memory", "what do you know", "orion status", "jarvis status", "agent status", "indexed", "knowledge", "workflow", "working on", "world state"), "agent"),
        (("what happened", "what failed", "last task", "previous task", "problem did you", "your logs", "task history"), "agent"),
        (("project session", "start project", "resume project", "end project", "close project", "project status"), "project"),
        (("codex", "generate code", "write code", "implement", "refactor", "build a feature", "generation job"), "generation"),
        (("what can you do", "capability", "worker families", "available workers", "adapter"), "capabilities"),
        (("google drive", "google sheet", "spreadsheet", "google doc", "google slides", "budget", "finances", "expense tracker"), "google_workspace"),
        (("install ", "download ", "is installed", "installation", "installed yet"), "software"),
        (("blender", "freecad", "free cad", "openscad", "open scad", "davinci", "da vinci", "resolve", "3d model", "cad model", "3d print", "printable", "product design", "industrial design", "video project", "timeline"), "native_projects"),
    )
    for markers, group in routes:
        if any(marker in text for marker in markers):
            selected.update(TOOL_GROUPS[group])
    objective = anticipation.analyze(request)
    if objective.get("action"):
        family_routes = {
            "git_delivery": "git", "engineering_design": "native_projects",
            "workspace_layout": "desktop", "software_installation": "software",
            "artifact_creation": "google_workspace", "media_playback": "spotify",
            "application_control": "mac", "task_management": "productivity",
        }
        family = family_routes.get(str(objective.get("category", "")))
        if family:
            selected.update(TOOL_GROUPS[family])
    # Questions with no actionable signal need no tool schema at all. Current-data
    # questions keep a narrow web lane.
    if not selected and any(marker in text for marker in ("today", "current", "latest", "right now")):
        selected.update(TOOL_GROUPS["web"])
    return [
        definition for definition in TOOL_DEFINITIONS
        if definition.get("name") in selected
        or (definition.get("type") == "web_search" and "__web_search__" in selected)
    ]


def get_weather(location: str) -> dict:
    headers = {"User-Agent": "ORION personal operating assistant"}
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1, "language": "en", "format": "json"},
        headers=headers,
        timeout=10,
    )
    geo.raise_for_status()
    results = geo.json().get("results", [])
    if not results:
        return {"ok": False, "error": f"Location not found: {location}"}
    place = results[0]
    units = os.getenv("ORION_UNITS", os.getenv("JARVIS_UNITS", "fahrenheit"))
    forecast = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "temperature_unit": units,
            "wind_speed_unit": "mph" if units == "fahrenheit" else "kmh",
            "timezone": "auto",
            "forecast_days": 1,
        },
        headers=headers,
        timeout=10,
    )
    forecast.raise_for_status()
    return {
        "ok": True,
        "place": ", ".join(filter(None, [place.get("name"), place.get("admin1"), place.get("country")])),
        "weather": forecast.json(),
    }


def open_search(query: str, kind: str) -> dict:
    suffix = "&tbm=isch" if kind == "images" else ""
    opened = webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}{suffix}")
    return {"ok": opened, "query": query, "kind": kind}


def spotify_control(action: str, query: str = "") -> dict:
    # Import lazily so Spotify credentials are optional for every other feature.
    import spot

    return spot.control(action, query)


def spotify_play_playlist(name: str = "") -> dict:
    import spot

    return spot.play_playlist(name)


def spotify_create_discovery_playlist(name: str = "") -> dict:
    import spot

    return spot.create_discovery_playlist(name or "ORION Discoveries")


def orion_status() -> dict:
    from orion_kernel import kernel
    return {**platform().summary(), "kernel": kernel().status()}


def orion_goal_status() -> dict:
    from orion_kernel import kernel
    return kernel().active_goal()


def orion_world_state(prefix: str = "") -> dict:
    from orion_kernel import kernel
    kernel().refresh_world()
    return kernel().world_snapshot(prefix=prefix)


def orion_workflows() -> dict:
    from orion_kernel import kernel
    return kernel().workflows()


def orion_teach_workflow(name: str, trigger: str, steps: list[str]) -> dict:
    from orion_kernel import kernel
    return kernel().teach_workflow(name, trigger, steps)


def codex_generate(repository: str, instruction: str, confirmed: bool) -> dict:
    import generation
    return generation.start_codex_job(repository, instruction, confirmed)


def generation_status(job_id: str = "") -> dict:
    import generation
    return generation.job_status(job_id)


def generation_cancel(job_id: str, confirmed: bool) -> dict:
    import generation
    return generation.cancel_job(job_id, confirmed)


def capability_families_status() -> dict:
    import capability_families
    return capability_families.status()


def objective_compile(objective: str) -> dict:
    import capability_families
    return capability_families.compile_objective(objective)


def google_drive_search(query: str, limit: int = 20) -> dict:
    import google_workspace
    return google_workspace.search_drive(query, limit)


def google_create_spreadsheet(title: str, template: str, currency: str, confirmed: bool) -> dict:
    import google_workspace
    return google_workspace.create_spreadsheet(title, template, currency, confirmed)


def google_create_document(title: str, content: str, confirmed: bool) -> dict:
    import google_workspace
    return google_workspace.create_document(title, content, confirmed)


def google_create_presentation(title: str, confirmed: bool) -> dict:
    import google_workspace
    return google_workspace.create_presentation(title, confirmed)


def design_project_plan(**arguments) -> dict:
    import design_intelligence
    return design_intelligence.create_brief(**arguments)


def blender_create_project(**arguments) -> dict:
    import blender_worker
    return blender_worker.create_project(**arguments)


def blender_refine_project(**arguments) -> dict:
    import blender_worker
    return blender_worker.refine_project(**arguments)


def blender_create_advanced_project(**arguments) -> dict:
    import blender_advanced_worker
    return blender_advanced_worker.create_project(**arguments)


def freecad_create_project(**arguments) -> dict:
    import freecad_worker
    return freecad_worker.create_project(**arguments)


def openscad_create_project(**arguments) -> dict:
    import openscad_worker
    return openscad_worker.create_project(**arguments)


def resolve_create_project(**arguments) -> dict:
    import resolve_worker
    return resolve_worker.create_project(**arguments)


def native_project_open(application: str, project_name: str = "") -> dict:
    import project_workspace
    return project_workspace.open_project(application, project_name)


def execute(name: str, arguments: dict, context: dict | None = None) -> dict:
    diagnostics.event("safety_classified", tool=name, risk=platform().risk_for(name))
    handlers = {
        "get_weather": get_weather,
        "open_search": open_search,
        "spotify_control": spotify_control,
        "spotify_play_playlist": spotify_play_playlist,
        "spotify_create_discovery_playlist": spotify_create_discovery_playlist,
        "open_application": mac_tools.open_application,
        "quit_application": mac_tools.quit_application,
        "browser_navigate": mac_tools.open_url,
        "set_system_volume": mac_tools.set_system_volume,
        "clipboard": mac_tools.clipboard,
        "system_status": mac_tools.system_status,
        "show_notification": mac_tools.notify,
        "create_reminder": mac_tools.create_reminder,
        "create_note": mac_tools.create_note,
        "create_calendar_event": mac_tools.create_calendar_event,
        "todoist_create_task": integrations.todoist_create_task,
        "home_assistant_control": integrations.home_assistant_control,
        "create_email_draft": mac_tools.create_email_draft,
        "find_contact": mac_tools.find_contact,
        "find_files": mac_tools.find_files,
        "apple_shortcuts": mac_tools.shortcuts,
        "desktop_inspect": desktop.inspect_screen,
        "desktop_action": desktop.perform_action,
        "desktop_accessibility_inspect": desktop.accessibility_snapshot,
        "desktop_local_ocr": desktop.local_ocr,
        "desktop_accessibility_set": desktop.accessibility_set,
        "desktop_accessibility_press": desktop.accessibility_press,
        "desktop_window_arrange": desktop.arrange_windows,
        "desktop_window_restore": desktop.restore_windows,
        "git_repositories": git_tools.repositories,
        "git_status": git_tools.status,
        "git_commit_and_push": git_tools.commit_and_push,
        "git_commit": git_tools.commit,
        "git_push": git_tools.push,
        "agent_status": orion_status,
        "task_history_search": platform().recent_tasks,
        "memory_store": platform().remember,
        "memory_search": platform().search_memory,
        "memory_forget": platform().forget,
        "local_knowledge_search": platform().search_documents,
        "orion_goal_status": orion_goal_status,
        "orion_world_state": orion_world_state,
        "orion_workflows": orion_workflows,
        "orion_teach_workflow": orion_teach_workflow,
        "codex_generate": codex_generate,
        "generation_status": generation_status,
        "generation_cancel": generation_cancel,
        "capability_families_status": capability_families_status,
        "objective_compile": objective_compile,
        "google_drive_search": google_drive_search,
        "google_create_spreadsheet": google_create_spreadsheet,
        "google_create_document": google_create_document,
        "google_create_presentation": google_create_presentation,
        "design_project_plan": design_project_plan,
        "blender_create_project": blender_create_project,
        "blender_refine_project": blender_refine_project,
        "blender_create_advanced_project": blender_create_advanced_project,
        "freecad_create_project": freecad_create_project,
        "openscad_create_project": openscad_create_project,
        "resolve_create_project": resolve_create_project,
        "native_project_open": native_project_open,
        "install_application": app_installer.install,
        "installation_status": app_installer.status,
        "project_session_start": project_workflow.start,
        "project_session_resume": project_workflow.resume,
        "project_session_status": project_workflow.status,
        "project_session_close": project_workflow.close,
    }
    if name not in handlers:
        return {"ok": False, "error": f"Unknown tool: {name}"}
    effective_arguments = dict(arguments)
    if name == "install_application" and context:
        effective_arguments.update({
            "_request_id": str(context.get("request_id", "")),
            "_task_id": str(context.get("task_id", "")),
        })
    if name in {"design_project_plan", "blender_create_project", "blender_refine_project", "blender_create_advanced_project", "freecad_create_project", "openscad_create_project", "resolve_create_project"} and context:
        effective_arguments["_request_id"] = str(context.get("request_id", ""))
    result = execution_supervisor.execute(
        name,
        effective_arguments,
        lambda: recovery.execute(name, effective_arguments, handlers[name]),
        task_id=str((context or {}).get("task_id", "")),
        request_id=str((context or {}).get("request_id", "")),
    )
    if result.get("ok") and name in {"open_application", "browser_navigate"}:
        application = str(result.get("application") or result.get("browser") or arguments.get("name") or "").strip()
        if application:
            staged = desktop.arrange_windows([application], confirmed=True)
            result["workspace_staged"] = bool(staged.get("ok"))
            activity.record_step("stage_application_window", application, staged)
    return result


def result_summary(name: str, arguments: dict, result: dict) -> str:
    """Natural zero-token confirmation for successful, unambiguous tool results."""
    if not result.get("ok"):
        return ""
    if name == "open_application":
        return f"{result.get('application') or arguments.get('name', 'The application')} is open."
    if name == "native_project_open":
        return f"I opened {result.get('project') or arguments.get('project_name')} in {result.get('application') or arguments.get('application')}."
    if name == "quit_application":
        return f"{result.get('application') or arguments.get('name', 'The application')} is closed."
    if name == "browser_navigate":
        return f"Done — {result.get('url') or arguments.get('url')} is open."
    if name == "set_system_volume":
        return f"Volume set to {result.get('volume', arguments.get('level'))} percent."
    if name == "spotify_control":
        action = arguments.get("action", "")
        return {"pause": "Paused.", "play": "Playing.", "next": "Skipped.", "previous": "Going back."}.get(action, "Done.")
    if name == "spotify_play_playlist":
        return f"Playing {result.get('name') or arguments.get('name', 'your playlist')}."
    if name == "show_notification":
        return "Notification shown."
    if name == "create_reminder":
        return f"Reminder created: {result.get('title') or arguments.get('title')}."
    if name == "create_note":
        return f"Note created: {result.get('title') or arguments.get('title')}."
    if name == "todoist_create_task":
        return f"Todoist task created: {arguments.get('content', 'your task')}."
    if name == "desktop_action":
        return "Done."
    if name in {"desktop_accessibility_set", "desktop_accessibility_press"}:
        return "Done."
    if name == "desktop_window_arrange":
        return "The requested workspace is staged beside ORION."
    if name == "desktop_window_restore":
        return "The application windows are back in their original positions."
    if name == "git_commit":
        return f"Committed {result.get('repository')} as {result.get('commit')}."
    if name in {"git_commit_and_push", "git_push"}:
        return f"{result.get('repository')} is pushed and synchronized with GitHub."
    if name == "memory_store":
        return f"I’ll remember {arguments.get('key')}."
    if name == "memory_forget":
        return f"I forgot {arguments.get('key')}."
    if name == "orion_teach_workflow":
        return f"I learned {result.get('name') or arguments.get('name')} as a reusable workflow."
    if name == "codex_generate":
        return f"Codex is working on {result.get('repository')}. I’ll monitor job {result.get('job_id')} in the background."
    if name == "generation_cancel":
        return "The generation job is cancelled."
    if name == "google_create_spreadsheet":
        return f"I created {result.get('title', 'the spreadsheet')} in Google Drive and verified its {len(result.get('sheets', []))} sheets."
    if name == "google_create_document":
        return f"I created {result.get('title', 'the document')} in Google Drive."
    if name == "google_create_presentation":
        return f"I created {result.get('title', 'the presentation')} in Google Drive."
    if name in {"blender_create_project", "freecad_create_project", "openscad_create_project", "resolve_create_project"}:
        opened = " and opened it" if result.get("opened") else ""
        return f"I created and verified the editable {result.get('application')} project {result.get('project')}{opened}. Its files are in {result.get('folder')}."
    if name == "blender_refine_project":
        opened = " and reopened it" if result.get("opened") else ""
        return f"I refined and rerendered {result.get('project')}{opened} in Blender."
    if name == "blender_create_advanced_project":
        opened = " and opened it" if result.get("opened") else ""
        return f"I procedurally modeled, verified, and rendered {result.get('project')}{opened} in Blender."
    if name == "install_application":
        application = result.get("application") or arguments.get("application") or "The application"
        if result.get("status") == "installed":
            return f"{application} is already installed and verified."
        return f"I started installing {application}. I’ll notify you when verification finishes."
    if name == "installation_status":
        application = result.get("application") or arguments.get("application") or "The application"
        status = result.get("status")
        if status in {"completed", "installed"} and result.get("verified"):
            return f"{application} is installed and verified."
        if status in {"running", "starting", "installing"}:
            return f"{application} is still installing."
        if status == "not_installed":
            return f"{application} is not installed."
        return f"The {application} installation failed."
    if name == "project_session_start":
        return f"Project session started for {result.get('repository')}."
    if name == "project_session_resume":
        return f"Resumed {result.get('repository')}."
    if name == "project_session_close":
        warning = result.get("warning", "")
        return f"Project session closed. {warning}".strip()
    return ""


def failure_summary(result: dict) -> str:
    code = result.get("error_code", "")
    if code == "repository_ambiguous":
        return "I need the repository name before I can continue. Options are: " + ", ".join(result.get("candidates", [])) + "."
    if code in {"remote_permission_denied", "authentication_required"}:
        committed = " Your commit is saved locally, so I won’t create another one." if result.get("committed") else ""
        return "GitHub rejected the push because this account is not authenticated or lacks write access." + committed
    if code == "unsaved_changes_dialog":
        return "The app is waiting on unsaved changes. I stopped without discarding anything."
    if code in {"accessibility_permission_required", "permission_required"}:
        return "I need Accessibility permission for that application before I can continue."
    if code == "confirmation_required":
        return "I need your explicit confirmation before performing that action."
    if code == "application_not_allowlisted":
        return " ".join(part for part in (str(result.get("error", "")), str(result.get("recovery", ""))) if part)
    if code in {"playlist_not_found", "track_not_found", "target_not_found", "control_not_found"}:
        return str(result.get("error", "I couldn't find the requested target."))
    recovery = str(result.get("recovery", "")).strip()
    return " ".join(part for part in (str(result.get("error", "I couldn't complete that action.")), recovery) if part)


def parse_command(command: str) -> None:
    """Legacy command adapter; new code uses structured function calls."""
    action = command.strip().lower()
    mapping = {"skip": "next", "spotify": "current"}
    if action in {"play", "pause", "skip", "previous", "spotify"}:
        spotify_control(mapping.get(action, action))
