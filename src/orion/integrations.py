"""Optional external services configured exclusively through environment variables."""

from __future__ import annotations

import os

import requests


def todoist_create_task(content: str, due_string: str = "") -> dict:
    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        return {"ok": False, "error": "Todoist is not configured; TODOIST_API_TOKEN is missing."}
    payload = {"content": content}
    if due_string:
        payload["due_string"] = due_string
    response = requests.post(
        "https://api.todoist.com/api/v1/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    task = response.json()
    return {"ok": True, "id": task.get("id"), "content": task.get("content"), "url": task.get("url")}


def home_assistant_control(domain: str, service: str, entity_id: str) -> dict:
    base_url = os.getenv("HOME_ASSISTANT_URL", "").rstrip("/")
    token = os.getenv("HOME_ASSISTANT_TOKEN")
    if not base_url or not token:
        return {"ok": False, "error": "Home Assistant is not configured; URL or token is missing."}
    allowed = {
        "light": {"turn_on", "turn_off", "toggle"},
        "switch": {"turn_on", "turn_off", "toggle"},
        "scene": {"turn_on"},
        "script": {"turn_on"},
        "media_player": {"media_play", "media_pause", "media_next_track", "media_previous_track"},
        "climate": {"turn_on", "turn_off"},
    }
    if service not in allowed.get(domain, set()):
        return {"ok": False, "error": f"Service {domain}.{service} is not allowed."}
    response = requests.post(
        f"{base_url}/api/services/{domain}/{service}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"entity_id": entity_id},
        timeout=15,
    )
    response.raise_for_status()
    return {"ok": True, "service": f"{domain}.{service}", "entity_id": entity_id}
