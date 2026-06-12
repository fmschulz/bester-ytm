from bester_ytm.search_query import parse_search_query
from bester_ytm.ytm_client import YTMClient


class FakeYTMusic:
    def search(self, query: str, filter: str | None = None, limit: int | None = None):
        if filter == "songs":
            return [
                {
                    "videoId": "song-title-match",
                    "title": "Sepultura Kaiowas",
                    "artists": [{"name": "Sepultura"}],
                },
                {
                    "videoId": "song-title-miss",
                    "title": "Territory",
                    "artists": [{"name": "Sepultura"}],
                },
            ][:limit]
        if filter == "albums":
            return [
                {
                    "browseId": "album-roots",
                    "title": "Roots",
                    "year": "1996",
                    "artists": [{"name": "Sepultura"}],
                },
                {
                    "browseId": "album-against",
                    "title": "Against",
                    "year": "1998",
                    "artists": [{"name": "Sepultura"}],
                },
            ][:limit]
        if filter == "artists":
            return [{"browseId": "artist-sepultura", "artist": "Sepultura"}]
        if filter == "community_playlists":
            return [
                {
                    "browseId": "VLPL-community",
                    "title": "Sepultura Essentials",
                    "author": "Community",
                    "itemCount": "42",
                }
            ]
        raise AssertionError(f"unexpected search: {query} {filter}")

    def get_artist(self, browse_id: str):
        assert browse_id == "artist-sepultura"
        return {
            "songs": {
                "results": [
                    {
                        "videoId": "popular-1",
                        "title": "Roots Bloody Roots",
                        "artists": [{"name": "Sepultura"}],
                    }
                ]
            },
            "albums": {
                "browseId": "artist-albums",
                "params": "albums-params",
                "results": [
                    {
                        "browseId": "album-fallback",
                        "title": "Fallback Album",
                        "year": "1997",
                        "artists": [{"name": "Sepultura"}],
                    }
                ],
            },
            "singles": {"results": []},
        }

    def get_artist_albums(
        self,
        browse_id: str,
        params: str,
        limit: int | None = None,
    ):
        assert browse_id == "artist-albums"
        assert params == "albums-params"
        return [
            {
                "browseId": "album-1998",
                "title": "Against",
                "year": "1998",
                "artists": [{"name": "Sepultura"}],
            },
            {
                "browseId": "album-1996",
                "title": "Roots",
                "year": "1996",
                "artists": [{"name": "Sepultura"}],
            },
        ]

    def get_album(self, browse_id: str):
        assert browse_id == "album-1998"
        return {
            "title": "Against",
            "year": "1998",
            "tracks": [
                {
                    "videoId": "against-1",
                    "title": "Against",
                    "artists": [{"name": "Sepultura"}],
                },
                {
                    "videoId": "against-2",
                    "title": "Choke",
                    "artists": [{"name": "Sepultura"}],
                },
            ],
        }


def _client() -> YTMClient:
    client = YTMClient(authenticated=False)
    client._ytmusic = FakeYTMusic()
    client._backend = "fake"
    return client


def test_structured_song_query_keeps_relevance_order() -> None:
    results = _client().structured_search(parse_search_query("song:sepultura"), limit=10)

    assert [item.video_id for item in results] == ["song-title-match", "song-title-miss"]


def test_structured_album_query_returns_albums() -> None:
    results = _client().structured_search(parse_search_query("album:sepultura"), limit=10)

    assert [item.item_type for item in results] == ["album", "album"]
    assert [item.title for item in results] == ["Roots", "Against"]
    assert all(item.browse_id for item in results)


def test_structured_album_query_filters_by_year() -> None:
    results = _client().structured_search(
        parse_search_query("album:sepultura,year:1998"),
        limit=10,
    )

    assert [item.title for item in results] == ["Against"]


def test_structured_artist_songs_use_artist_popular_songs() -> None:
    results = _client().structured_search(parse_search_query("artist:sepultura"), limit=10)

    assert [item.video_id for item in results] == ["popular-1"]
    assert results[0].title == "Roots Bloody Roots"


def test_structured_artist_albums_return_artist_releases() -> None:
    results = _client().structured_search(
        parse_search_query("artist:sepultura,albums"),
        limit=10,
    )

    assert [(item.title, item.year) for item in results] == [
        ("Against", "1998"),
        ("Roots", "1996"),
    ]


def test_structured_artist_year_songs_expand_matching_album_tracks() -> None:
    results = _client().structured_search(
        parse_search_query("artist:sepultura,year:1998,songs"),
        limit=10,
    )

    assert [item.video_id for item in results] == ["against-1", "against-2"]


def test_structured_playlist_query_returns_community_playlists() -> None:
    results = _client().structured_search(
        parse_search_query("playlist:sepultura"),
        limit=10,
    )

    assert results[0].item_type == "playlist"
    assert results[0].playlist_id == "VLPL-community"
    assert results[0].track_count == 42
