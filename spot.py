"""Optional Spotify integration, initialized only when requested."""

from __future__ import annotations

import os

import spotipy
from spotipy.oauth2 import SpotifyOAuth


def _client() -> spotipy.Spotify:
    missing = [
        name
        for name in ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI")
        if not os.getenv(name)
    ]
    if missing:
        raise RuntimeError("Spotify is not configured; missing " + ", ".join(missing))
    auth = SpotifyOAuth(
        scope="user-read-playback-state user-read-currently-playing user-modify-playback-state",
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth)


def control(action: str) -> dict:
    spotify = _client()
    if action == "play":
        spotify.start_playback()
    elif action == "pause":
        spotify.pause_playback()
    elif action == "next":
        spotify.next_track()
    elif action == "previous":
        spotify.previous_track()
    elif action == "current":
        state = spotify.current_user_playing_track()
        if not state or not state.get("item"):
            return {"ok": True, "playing": False}
        track = state["item"]
        return {
            "ok": True,
            "playing": bool(state.get("is_playing")),
            "title": track.get("name"),
            "artists": [artist["name"] for artist in track.get("artists", [])],
            "album": track.get("album", {}).get("name"),
        }
    else:
        return {"ok": False, "error": f"Unknown Spotify action: {action}"}
    return {"ok": True, "action": action}


# Compatibility wrappers.
def start_music(): return control("play")
def stop_music(): return control("pause")
def skip_to_next(): return control("next")
def skip_to_previous(): return control("previous")
def get_current_playing_info(): return control("current")
