from bester_ytm.search_query import parse_search_query


def test_parse_song_title_query() -> None:
    parsed = parse_search_query("song:sepultura")

    assert parsed.kind == "song"
    assert parsed.text == "sepultura"
    assert parsed.view == "songs"


def test_parse_songs_prefix_is_song_query() -> None:
    parsed = parse_search_query("songs:metallica")

    assert parsed.kind == "song"
    assert parsed.text == "metallica"
    assert parsed.view == "songs"


def test_parse_album_query() -> None:
    parsed = parse_search_query("album:metallica")

    assert parsed.kind == "album"
    assert parsed.text == "metallica"
    assert parsed.view == "albums"


def test_parse_albums_prefix_is_album_query() -> None:
    parsed = parse_search_query("albums:ride the lightning")

    assert parsed.kind == "album"
    assert parsed.text == "ride the lightning"
    assert parsed.view == "albums"


def test_parse_artist_songs_query() -> None:
    parsed = parse_search_query("artist:sepultura,songs")

    assert parsed.kind == "artist"
    assert parsed.text == "sepultura"
    assert parsed.view == "songs"
    assert parsed.year is None


def test_parse_artist_year_songs_query() -> None:
    parsed = parse_search_query("artist:sepultura,year:1998,songs")

    assert parsed.kind == "artist"
    assert parsed.text == "sepultura"
    assert parsed.view == "songs"
    assert parsed.year == 1998


def test_parse_artist_albums_query() -> None:
    parsed = parse_search_query("artist:sepultura,albums")

    assert parsed.kind == "artist"
    assert parsed.text == "sepultura"
    assert parsed.view == "albums"


def test_parse_empty_playlist_query_lists_local_playlists() -> None:
    parsed = parse_search_query("playlist:")

    assert parsed.kind == "playlist"
    assert parsed.text == ""
    assert parsed.view == "playlists"
    assert parsed.lists_local_playlists is True


def test_parse_playlist_text_query_searches_community_playlists() -> None:
    parsed = parse_search_query("playlist:sepultura")

    assert parsed.kind == "playlist"
    assert parsed.text == "sepultura"
    assert parsed.view == "playlists"
    assert parsed.lists_local_playlists is False
