"""Optional Spotify integration, initialized only when requested."""

from __future__ import annotations

import os
import random
import subprocess
import time
from collections import Counter
from datetime import datetime

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth


def _failure(message: str, code: str, *, retryable: bool = False, requires_user: bool = False) -> dict:
    return {"ok": False, "error": message, "error_code": code, "retryable": retryable, "requires_user": requires_user}


def _client() -> spotipy.Spotify:
    missing = [
        name
        for name in ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI")
        if not os.getenv(name)
    ]
    if missing:
        raise RuntimeError("Spotify is not configured; missing " + ", ".join(missing))
    auth = SpotifyOAuth(
        scope=(
            "user-read-playback-state user-read-currently-playing user-modify-playback-state "
            "playlist-read-private playlist-read-collaborative playlist-modify-private "
            "user-top-read user-read-recently-played"
        ),
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth)


def _api(spotify: spotipy.Spotify, method: str, path: str, **kwargs) -> dict:
    response = None
    for attempt in range(4):
        token = spotify.auth_manager.get_access_token(as_dict=False)
        response = requests.request(
            method,
            f"https://api.spotify.com/v1/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
            **kwargs,
        )
        if response.status_code == 429:
            delay = min(float(response.headers.get("Retry-After", "1")), 5.0)
            time.sleep(delay)
            continue
        if response.status_code >= 500 and attempt < 3:
            time.sleep(0.5 * (2 ** attempt))
            continue
        response.raise_for_status()
        return response.json() if response.content else {}
    assert response is not None
    response.raise_for_status()
    return {}


def _collect_offset(
    spotify: spotipy.Spotify,
    path: str,
    *,
    limit: int,
    maximum: int,
    extra_params: dict | None = None,
) -> list[dict]:
    collected: list[dict] = []
    offset = 0
    while len(collected) < maximum:
        params = {"limit": min(limit, maximum - len(collected)), "offset": offset}
        params.update(extra_params or {})
        page = _api(spotify, "GET", path, params=params)
        items = page.get("items", [])
        collected.extend(items)
        if not items or not page.get("next"):
            break
        offset += len(items)
    return collected[:maximum]


def create_discovery_playlist(name: str = "Jarvis Discoveries") -> dict:
    """Build recommendations locally so Spotify metadata never reaches the LLM."""
    spotify = _client()
    profile = _api(spotify, "GET", "me")
    top_artists = _collect_offset(
        spotify, "me/top/artists", limit=50, maximum=50, extra_params={"time_range": "short_term"}
    )
    top_tracks = _collect_offset(
        spotify, "me/top/tracks", limit=50, maximum=50, extra_params={"time_range": "short_term"}
    )
    recent = _api(
        spotify, "GET", "me/player/recently-played", params={"limit": 50}
    ).get("items", [])

    heard = {track.get("uri") for track in top_tracks if track.get("uri")}
    artist_scores: Counter[str] = Counter()
    for position, artist in enumerate(top_artists):
        if artist.get("name"):
            artist_scores[artist["name"]] += max(1, 50 - position) * 2
    for track in top_tracks:
        for artist in track.get("artists", []):
            if artist.get("name"):
                artist_scores[artist["name"]] += 3
    heard.update(
        item.get("track", {}).get("uri")
        for item in recent
        if item.get("track", {}).get("uri")
    )
    for item in recent:
        for artist in item.get("track", {}).get("artists", []):
            if artist.get("name"):
                artist_scores[artist["name"]] += 8
    playlists = _collect_offset(spotify, "me/playlists", limit=50, maximum=200)
    inspected = 0
    for playlist in playlists:
        owner_id = playlist.get("owner", {}).get("id")
        if owner_id != profile.get("id") and not playlist.get("collaborative"):
            continue
        try:
            playlist_items = _collect_offset(
                spotify, f"playlists/{playlist['id']}/items", limit=100, maximum=500
            )
        except requests.HTTPError:
            continue
        for entry in playlist_items:
            track = entry.get("item") or entry.get("track") or {}
            if track.get("uri"):
                heard.add(track["uri"])
        inspected += 1
        if inspected >= 50:
            break

    candidates: list[str] = []
    seen = set(heard)
    current_year = datetime.now().year
    for artist_name, _score in artist_scores.most_common(25):
        for search_query in (
            f'artist:"{artist_name}" year:{current_year - 2}-{current_year}',
            f'artist:"{artist_name}"',
        ):
            results = _api(
                spotify,
                "GET",
                "search",
                params={"q": search_query, "type": "track", "limit": 10},
            )
            added_for_artist = 0
            for track in results.get("tracks", {}).get("items", []):
                uri = track.get("uri")
                if not uri or not uri.startswith("spotify:track:") or uri in seen:
                    continue
                seen.add(uri)
                candidates.append(uri)
                added_for_artist += 1
                if added_for_artist >= 2 or len(candidates) >= 30:
                    break
            if added_for_artist or len(candidates) >= 30:
                break
        if len(candidates) >= 30:
            break

    if not candidates:
        return _failure("No unfamiliar tracks were found from your Spotify history.", "no_recommendations")

    playlist_name = name.strip() or "Jarvis Discoveries"
    created = _api(
        spotify,
        "POST",
        "me/playlists",
        json={
            "name": playlist_name,
            "public": False,
            "description": "Fresh tracks selected locally from your Spotify listening patterns by Jarvis.",
        },
    )
    _api(
        spotify,
        "POST",
        f"playlists/{created['id']}/items",
        json={"uris": candidates[:30]},
    )
    return {
        "ok": True,
        "playlist": playlist_name,
        "tracks_added": min(30, len(candidates)),
        "playlists_checked": inspected,
        "privacy": "Spotify metadata was processed locally and was not sent to the AI model.",
    }


def play_playlist(name: str = "") -> dict:
    spotify = _client()
    profile = _api(spotify, "GET", "me")
    available = _collect_offset(spotify, "me/playlists", limit=50, maximum=500)
    playlists = [
        playlist
        for playlist in available
        if playlist.get("owner", {}).get("id") == profile.get("id")
        or bool(playlist.get("collaborative"))
    ]
    if not playlists:
        return _failure("No owned or collaborative Spotify playlists are available in this account.", "no_owned_playlists")
    requested = name.strip().casefold()
    if requested:
        exact = [p for p in playlists if (p.get("name") or "").casefold() == requested]
        partial = [p for p in playlists if requested in (p.get("name") or "").casefold()]
        matches = exact or partial
        if not matches:
            return _failure("No accessible playlist matched the requested name.", "playlist_not_found", requires_user=True)
        playlist = matches[0]
    else:
        playlist = random.SystemRandom().choice(playlists)
    uri = playlist.get("uri")
    if not uri:
        return _failure("The selected playlist has no playable Spotify URI.", "playlist_unplayable")
    try:
        _play_context(spotify, uri)
    except RuntimeError as exc:
        return _failure(str(exc), "playback_device_unavailable", retryable=True)
    return {
        "ok": True,
        "action": "play_existing_playlist",
        "selection": "requested playlist" if requested else "random library playlist",
    }


def _local_play(uri: str | None = None) -> None:
    if uri:
        subprocess.run(["/usr/bin/open", "-a", "Spotify", uri], check=True, timeout=20)
    else:
        subprocess.run(["/usr/bin/open", "-a", "Spotify"], check=True, timeout=20)
    subprocess.run(
        ["/usr/bin/osascript", "-e", 'tell application "Spotify" to play'],
        check=True,
        timeout=20,
        capture_output=True,
        text=True,
    )


def _play_context(spotify: spotipy.Spotify, uri: str) -> None:
    """Start the selected playlist context instead of resuming the current track."""
    try:
        spotify.start_playback(context_uri=uri)
        return
    except spotipy.SpotifyException as exc:
        if exc.http_status not in {403, 404}:
            raise

    # Wake Spotify on this Mac, wait for its Connect device, then target the
    # selected playlist explicitly. Merely opening a playlist URI does not play it.
    subprocess.run(["/usr/bin/open", "-a", "Spotify", uri], check=True, timeout=20)
    for _ in range(12):
        devices = spotify.devices().get("devices", [])
        usable = [
            device
            for device in devices
            if device.get("id") and not device.get("is_restricted")
        ]
        active = next((device for device in usable if device.get("is_active")), None)
        computer = next((device for device in usable if device.get("type") == "Computer"), None)
        device = active or computer or (usable[0] if usable else None)
        if device:
            spotify.transfer_playback(device["id"], force_play=False)
            spotify.start_playback(device_id=device["id"], context_uri=uri)
            return
        time.sleep(0.5)
    raise RuntimeError(
        "Spotify opened the playlist, but this Mac did not appear as an available Connect device."
    )


def _local_command(action: str) -> None:
    commands = {
        "pause": 'tell application "Spotify" to pause',
        "next": 'tell application "Spotify" to next track',
        "previous": 'tell application "Spotify" to previous track',
    }
    subprocess.run(
        ["/usr/bin/osascript", "-e", commands[action]],
        check=True,
        timeout=20,
        capture_output=True,
        text=True,
    )


def _connect_or_local(action: str, remote_action) -> None:
    try:
        remote_action()
    except spotipy.SpotifyException as exc:
        if exc.http_status not in {403, 404}:
            raise
        _local_command(action)


def control(action: str, query: str = "") -> dict:
    spotify = _client()
    if action == "play":
        if query:
            results = spotify.search(q=query, type="track", limit=1)
            tracks = results.get("tracks", {}).get("items", [])
            if not tracks:
                return _failure(f"No Spotify track found for: {query}", "track_not_found", requires_user=True)
            track = tracks[0]
            _local_play(track["uri"])
            return {
                "ok": True,
                "action": "play",
                "title": track.get("name"),
                "artists": [artist["name"] for artist in track.get("artists", [])],
                "device": "this Mac",
            }
        try:
            spotify.start_playback()
        except spotipy.SpotifyException as exc:
            if exc.http_status not in {403, 404}:
                raise
            _local_play()
    elif action == "pause":
        _connect_or_local("pause", spotify.pause_playback)
    elif action == "next":
        _connect_or_local("next", spotify.next_track)
    elif action == "previous":
        _connect_or_local("previous", spotify.previous_track)
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
        return _failure(f"Unknown Spotify action: {action}", "unsupported_spotify_action", requires_user=True)
    return {"ok": True, "action": action}


# Compatibility wrappers.
def start_music(): return control("play")
def stop_music(): return control("pause")
def skip_to_next(): return control("next")
def skip_to_previous(): return control("previous")
def get_current_playing_info(): return control("current")
