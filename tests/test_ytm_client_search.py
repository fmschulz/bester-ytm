from __future__ import annotations

from typing import Any

import pytest

from bester_ytm.search_query import parse_search_query
from bester_ytm.ytm_client import YTMClient, YTMClientError


def _client(fake: Any = None) -> YTMClient:
    client = YTMClient(authenticated=False)
    client._ytmusic = fake if fake is not None else object()
    client._backend = "fake"
    return client


class FallbackSearch:
    """search() that fails or returns nothing for filtered queries."""

    def __init__(self, filtered: Any, unfiltered: Any) -> None:
        self.filtered = filtered
        self.unfiltered = unfiltered

    def search(self, query: str, filter: str | None = None, limit: int | None = None):
        result = self.filtered if filter else self.unfiltered
        if isinstance(result, Exception):
            raise result
        return result


SONG_RAW = {"videoId": "v1", "title": "Myth", "artists": [{"name": "Beach House"}]}


def test_search_songs_falls_back_when_filtered_search_fails() -> None:
    client = _client(FallbackSearch(RuntimeError("bad filter"), [SONG_RAW]))

    candidates = client.search_songs("myth")

    assert [candidate.video_id for candidate in candidates] == ["v1"]


def test_search_songs_retries_when_filtered_search_is_empty() -> None:
    client = _client(FallbackSearch([], [SONG_RAW, "junk"]))

    candidates = client.search_songs("myth")

    assert [candidate.video_id for candidate in candidates] == ["v1"]


def test_search_songs_wraps_total_failure() -> None:
    client = _client(FallbackSearch([], RuntimeError("offline")))

    with pytest.raises(YTMClientError, match="search failed for 'myth'"):
        client.search_songs("myth")


def test_search_albums_filters_results_and_wraps_errors() -> None:
    class AlbumSearch:
        def search(self, query, filter=None, limit=None):
            assert filter == "albums"
            return [{"browseId": "b1", "title": "Bloom"}, "junk", {"title": "no id"}]

    items = _client(AlbumSearch()).search_albums("bloom")
    assert [item.browse_id for item in items] == ["b1"]

    failing = _client(FallbackSearch(RuntimeError("offline"), []))
    with pytest.raises(YTMClientError, match="album search failed"):
        failing.search_albums("bloom")


def test_search_community_playlists_wraps_errors() -> None:
    client = _client(FallbackSearch(RuntimeError("offline"), []))

    with pytest.raises(YTMClientError, match="community playlist search failed"):
        client.search_community_playlists("mix")


def test_first_artist_requires_results_and_wraps_errors() -> None:
    with pytest.raises(YTMClientError, match="No artist found"):
        _client(FallbackSearch([], []))._first_artist("nobody")

    failing = _client(FallbackSearch(RuntimeError("offline"), []))
    with pytest.raises(YTMClientError, match="artist search failed"):
        failing._first_artist("nobody")


def test_artist_payload_wraps_lookup_errors() -> None:
    class ArtistSearch:
        def search(self, query, filter=None, limit=None):
            return [{"browseId": "b1", "artist": "Sepultura"}]

        def get_artist(self, browse_id: str):
            raise RuntimeError("offline")

    with pytest.raises(YTMClientError, match="artist lookup failed"):
        _client(ArtistSearch())._artist_payload("sepultura")


def test_artist_releases_handles_missing_and_failing_expansion() -> None:
    class FailingAlbums:
        def get_artist_albums(self, browse_id, params, limit=None):
            raise RuntimeError("offline")

    client = _client(FailingAlbums())
    assert client._artist_releases({"albums": "junk"}, "albums") == []

    payload = {
        "albums": {
            "browseId": "b1",
            "params": "p1",
            "results": [{"browseId": "embedded", "title": "Roots"}],
        }
    }
    releases = client._artist_releases(payload, "albums")
    assert [release["browseId"] for release in releases] == ["embedded"]


def test_search_artist_albums_filters_by_year(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    payload = {
        "albums": {
            "results": [
                {"browseId": "b1998", "title": "Against", "year": "1998"},
                {"browseId": "b1996", "title": "Roots", "year": "1996"},
            ]
        }
    }
    monkeypatch.setattr(client, "_artist_payload", lambda query: payload)

    items = client.search_artist_albums("sepultura", year=1998)

    assert [item.title for item in items] == ["Against"]


def test_search_artist_songs_year_skips_unusable_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Albums:
        def get_album(self, browse_id: str):
            if browse_id == "bad":
                raise RuntimeError("offline")
            return {
                "title": "Against",
                "year": "1998",
                "tracks": [
                    {"videoId": "t1", "title": "Against"},
                    {"videoId": "t2", "title": "Choke"},
                ],
            }

    client = _client(Albums())
    payload = {
        "albums": {
            "results": [
                {"title": "no browse id", "year": "1998"},
                {"browseId": "bad", "year": "1998"},
                {"browseId": "good", "year": "1998"},
                {"browseId": "never-read", "year": "1998"},
            ]
        },
        "singles": {"results": []},
    }
    monkeypatch.setattr(client, "_artist_payload", lambda query: payload)

    items = client.search_artist_songs("sepultura", year=1998, limit=2)

    assert [item.video_id for item in items] == ["t1", "t2"]


def test_structured_search_playlist_requires_text() -> None:
    parsed = parse_search_query("playlist:")

    assert _client().structured_search(parsed) == []


def test_structured_search_free_text_uses_song_search() -> None:
    client = _client(FallbackSearch([SONG_RAW], []))

    items = client.structured_search(parse_search_query("beach house"))

    assert [item.video_id for item in items] == ["v1"]
    assert items[0].source == "free"
    assert items[0].candidate is not None


def test_get_related_candidates_filters_seed_and_wraps_errors() -> None:
    class Related:
        def get_watch_playlist(self, videoId: str, limit: int):
            return {
                "tracks": [
                    {"videoId": videoId, "title": "Seed"},
                    {"videoId": "r1", "title": "Related"},
                    "junk",
                ]
            }

    candidates = _client(Related()).get_related_candidates("v0", limit=5)
    assert [candidate.video_id for candidate in candidates] == ["r1"]

    class Failing:
        def get_watch_playlist(self, videoId: str, limit: int):
            raise RuntimeError("offline")

    with pytest.raises(YTMClientError, match="related lookup failed"):
        _client(Failing()).get_related_candidates("v0")
