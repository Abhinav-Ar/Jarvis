import unittest
from unittest.mock import Mock, patch

import spot
import spotipy


class SpotifyTests(unittest.TestCase):
    @patch("spot.time.sleep")
    @patch("spot.requests.request")
    def test_api_retries_rate_limit(self, request, sleep):
        spotify = Mock()
        spotify.auth_manager.get_access_token.return_value = "token"
        limited = Mock(status_code=429, headers={"Retry-After": "1"}, content=b"")
        success = Mock(status_code=200, headers={}, content=b"{}")
        success.json.return_value = {"ok": True}
        request.side_effect = [limited, success]
        self.assertTrue(spot._api(spotify, "GET", "me")["ok"])
        sleep.assert_called_once_with(1.0)

    @patch("spot.create_discovery_playlist", return_value={"ok": True, "tracks_added": 8})
    def test_taste_playlist_is_built_inside_spotify_integration(self, create_playlist):
        result = spot.control("taste_playlist", "Fresh Finds")
        self.assertTrue(result["ok"])
        create_playlist.assert_called_once_with("Fresh Finds")

    @patch("spot._local_play")
    @patch("spot._client")
    def test_no_active_connect_device_falls_back_to_mac_app(self, client, local_play):
        spotify = Mock()
        spotify.start_playback.side_effect = spotipy.SpotifyException(404, -1, "No active device")
        client.return_value = spotify
        result = spot.control("play")
        self.assertTrue(result["ok"])
        local_play.assert_called_once_with()

    @patch("spot._local_play")
    @patch("spot._client")
    def test_song_query_opens_matching_track_on_mac(self, client, local_play):
        spotify = Mock()
        spotify.search.return_value = {
            "tracks": {"items": [{"uri": "spotify:track:123", "name": "Test Song", "artists": [{"name": "Artist"}]}]}
        }
        client.return_value = spotify
        result = spot.control("play", "test song")
        self.assertTrue(result["ok"])
        local_play.assert_called_once_with("spotify:track:123")


if __name__ == "__main__":
    unittest.main()
