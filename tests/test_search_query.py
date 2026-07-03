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


def test_parse_favs_query_lists_favorites() -> None:
    parsed = parse_search_query("favs:")

    assert parsed.kind == "favorites"
    assert parsed.text == ""
    assert parsed.view == "songs"
    assert parsed.lists_favorites is True


def test_parse_favs_text_query_filters_favorites() -> None:
    parsed = parse_search_query("favorites:sepultura")

    assert parsed.kind == "favorites"
    assert parsed.text == "sepultura"
    assert parsed.lists_favorites is True


def test_free_query_does_not_list_favorites() -> None:
    assert parse_search_query("favourite tunes").lists_favorites is False


def test_parse_local_prefix_keeps_raw_path() -> None:
    parsed = parse_search_query("local:~/Music/mixes, best of")

    assert parsed.kind == "local"
    assert parsed.text == "~/Music/mixes, best of"
    assert parsed.view == "songs"
    assert parsed.lists_local_files is True


def test_parse_pasted_paths_are_local() -> None:
    for query in ("/home/me/Music", "~/Music", "./examples/music"):
        parsed = parse_search_query(query)
        assert parsed.kind == "local"
        assert parsed.text == query


def test_free_query_is_not_local() -> None:
    assert parse_search_query("localize this song").lists_local_files is False


def test_parse_radio_query_lists_stations() -> None:
    parsed = parse_search_query("radio:")

    assert parsed.kind == "radio"
    assert parsed.view == "songs"
    assert parsed.lists_radio_stations is True


def test_parse_liked_aliases_favorites() -> None:
    parsed = parse_search_query("liked:")

    assert parsed.kind == "favorites"
    assert parsed.lists_favorites is True
    assert parse_search_query("liked:beach").text == "beach"
