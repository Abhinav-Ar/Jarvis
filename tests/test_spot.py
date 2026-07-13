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

    @patch("spot._play_context")
    @patch("spot._collect_offset")
    @patch("spot._api", return_value={"id": "me"})
    @patch("spot._client")
    def test_named_playlist_playback_does_not_create_playlist(self, client, api, collect, play_context):
        collect.return_value = [
            {"name": "UG", "uri": "spotify:playlist:123", "owner": {"id": "me"}, "collaborative": False}
        ]
        result = spot.play_playlist("ug")
        self.assertTrue(result["ok"])
        play_context.assert_called_once_with(client.return_value, "spotify:playlist:123")

    @patch("spot._play_context")
    @patch("spot._collect_offset")
    @patch("spot._api", return_value={"id": "me"})
    @patch("spot._client")
    def test_my_playlists_excludes_followed_lists_owned_by_others(self, client, api, collect, play_context):
        collect.return_value = [
            {"name": "Someone Else", "uri": "spotify:playlist:other", "owner": {"id": "other"}, "collaborative": False},
            {"name": "Shared", "uri": "spotify:playlist:shared", "owner": {"id": "other"}, "collaborative": True},
        ]
        result = spot.play_playlist("")
        self.assertTrue(result["ok"])
        play_context.assert_called_once_with(client.return_value, "spotify:playlist:shared")

    @patch("spot.time.sleep")
    @patch("spot.subprocess.run")
    def test_playlist_context_activates_connect_device_before_playing(self, run, sleep):
        spotify = Mock()
        spotify.start_playback.side_effect = [
            spotipy.SpotifyException(404, -1, "No active device"),
            None,
        ]
        spotify.devices.return_value = {
            "devices": [
                {
                    "id": "mac",
                    "type": "Computer",
                    "is_active": False,
                    "is_restricted": False,
                }
            ]
        }
        spot._play_context(spotify, "spotify:playlist:123")
        spotify.transfer_playback.assert_called_once_with("mac", force_play=False)
        spotify.start_playback.assert_called_with(
            device_id="mac", context_uri="spotify:playlist:123"
        )

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
