"""Safe, structured tools available to Jarvis."""

from __future__ import annotations

import os
import webbrowser
from urllib.parse import quote_plus

import requests


TOOL_DEFINITIONS = [
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
        "description": "Control Spotify or report the currently playing track.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "next", "previous", "current"],
                }
            },
            "required": ["action"],
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


def spotify_control(action: str) -> dict:
    # Import lazily so Spotify credentials are optional for every other feature.
    import spot

    return spot.control(action)


def execute(name: str, arguments: dict) -> dict:
    handlers = {
        "get_weather": get_weather,
        "open_search": open_search,
        "spotify_control": spotify_control,
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
