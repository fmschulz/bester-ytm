from __future__ import annotations

from bester_ytm.ytm_client import (
    _artist_names,
    _duration_to_seconds,
    normalize_album,
    normalize_playlist_result,
    normalize_song,
    playlist_item_to_candidate,
)


def test_duration_to_seconds_parses_clock_formats() -> None:
    assert _duration_to_seconds("4:05") == 245
    assert _duration_to_seconds("1:02:03") == 3723
    assert _duration_to_seconds("45") == 45
    assert _duration_to_seconds(None) is None
    assert _duration_to_seconds("") is None
    assert _duration_to_seconds("4:xx") is None


def test_artist_names_handles_strings_dicts_and_noise() -> None:
    assert _artist_names(None) == []
    assert _artist_names("Solo Artist") == ["Solo Artist"]
    assert _artist_names([{"name": "A"}, {"name": ""}, "B", None, 7]) == ["A", "B", "7"]


def test_normalize_song_maps_all_fields() -> None:
    candidate = normalize_song(
        {
            "videoId": "v1",
            "title": "Myth",
            "artists": [{"name": "Beach House"}],
            "album": {"name": "Bloom"},
            "year": 2012,
            "duration": "4:18",
            "resultType": "song",
            "isExplicit": False,
        }
    )

    assert candidate is not None
    assert candidate.video_id == "v1"
    assert candidate.album == "Bloom"
    assert candidate.year == "2012"
    assert candidate.duration_seconds == 258
    assert candidate.result_type == "song"


def test_normalize_song_requires_video_id_and_accepts_string_album() -> None:
    assert normalize_song({"title": "No id"}) is None

    candidate = normalize_song({"video_id": "v2", "name": "Alt", "album": "Souvlaki"})
    assert candidate is not None
    assert candidate.album == "Souvlaki"
    assert candidate.title == "Alt"


def test_normalize_album_requires_browse_id() -> None:
    assert normalize_album({"title": "No browse id"}) is None

    item = normalize_album(
        {
            "browseId": "b1",
            "title": "Bloom",
            "artists": [{"name": "Beach House"}],
            "audioPlaylistId": "OLAK1",
            "year": "2012",
        }
    )
    assert item is not None
    assert item.playlist_id == "OLAK1"
    assert item.subtitle == "Beach House"
    assert item.year == "2012"


def test_normalize_playlist_result_handles_fallbacks() -> None:
    assert normalize_playlist_result({"title": "No id"}) is None

    item = normalize_playlist_result(
        {"browseId": "VLPL1", "title": "Mix", "channelTitle": "Channel", "count": "bad"}
    )
    assert item is not None
    assert item.playlist_id == "VLPL1"
    assert item.subtitle == "Channel"
    assert item.track_count is None


def test_playlist_item_to_candidate_requires_snippet_shape() -> None:
    assert playlist_item_to_candidate({"snippet": "junk"}, "PL1") is None
    assert playlist_item_to_candidate({"snippet": {"resourceId": {}}}, "PL1") is None

    candidate = playlist_item_to_candidate(
        {
            "snippet": {
                "title": "One",
                "channelTitle": "Uploader",
                "resourceId": {"videoId": "v1"},
            }
        },
        "PL1",
    )
    assert candidate is not None
    assert candidate.video_id == "v1"
    assert candidate.artists == ["Uploader"]
    assert candidate.source == "playlist:PL1"
