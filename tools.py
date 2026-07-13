"""Safe, structured tools available to Jarvis."""

from __future__ import annotations

import os
import webbrowser
from urllib.parse import quote_plus

import requests

import integrations
import mac_tools


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
        "description": "Play one of the user's existing Spotify playlists. Set name to the requested playlist name, or empty only when the user asks for any/random existing playlist. This never creates a playlist.",
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
        "description": "Create a new private Spotify discovery playlist using recent listening taste. Use only when the user explicitly asks to create or make a new discovery/recommendation playlist. Never use for requests to play an existing playlist.",
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
        "description": "Open an installed macOS application by name.",
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
]


def get_weather(location: str) -> dict:
    headers = {"User-Agent": "Jarvis personal voice assistant"}
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
    units = os.getenv("JARVIS_UNITS", "fahrenheit")
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

    return spot.create_discovery_playlist(name or "Jarvis Discoveries")


def execute(name: str, arguments: dict) -> dict:
    handlers = {
        "get_weather": get_weather,
        "open_search": open_search,
        "spotify_control": spotify_control,
        "spotify_play_playlist": spotify_play_playlist,
        "spotify_create_discovery_playlist": spotify_create_discovery_playlist,
        "open_application": mac_tools.open_application,
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
    }
    if name not in handlers:
        return {"ok": False, "error": f"Unknown tool: {name}"}
    return handlers[name](**arguments)


def parse_command(command: str) -> None:
    """Legacy command adapter; new code uses structured function calls."""
    action = command.strip().lower()
    mapping = {"skip": "next", "spotify": "current"}
    if action in {"play", "pause", "skip", "previous", "spotify"}:
        spotify_control(mapping.get(action, action))
