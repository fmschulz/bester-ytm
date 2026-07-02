import logging
from pathlib import Path

import pytest

from bester_ytm.config import ConfigError
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.stores import FavoritesStore, LocalPlaylist, LocalPlaylistStore, PlanStore


def _favorites(tmp_path: Path) -> FavoritesStore:
    return FavoritesStore(
        path=tmp_path / "favorites.json", legacy_path=tmp_path / "favorites.md"
    )


def test_favorites_store_toggle_favs_and_unfavs(tmp_path: Path) -> None:
    store = _favorites(tmp_path)
    candidate = SongCandidate(video_id="v1", title="Myth", artists=["Beach House"])

    assert store.toggle(candidate) is True
    assert store.ids() == {"v1"}
    assert store.list()[0].display_name == "Beach House - Myth"

    assert store.toggle(candidate) is False
    assert store.ids() == set()


def test_favorites_store_search_items_filter_by_text(tmp_path: Path) -> None:
    store = _favorites(tmp_path)
    store.toggle(SongCandidate(video_id="v1", title="Myth", artists=["Beach House"]))
    store.toggle(SongCandidate(video_id="v2", title="Territory", artists=["Sepultura"]))

    items = store.search_items()
    assert [item.candidate.video_id for item in items] == ["v1", "v2"]
    assert items[0].item_type == "song"

    filtered = store.search_items("sepul")
    assert [item.candidate.video_id for item in filtered] == ["v2"]


def test_favorites_store_migrates_legacy_markdown_once(tmp_path: Path) -> None:
    legacy = tmp_path / "favorites.md"
    legacy.write_text(
        "# bester-ytm Favorites\n"
        "\n"
        "- Sepultura - Territory (v1)\n"
        "- Artist Only - No Id Line\n",  # tuiradio import line: no video id, skipped
        encoding="utf-8",
    )
    store = _favorites(tmp_path)

    favorites = store.list()

    assert [candidate.video_id for candidate in favorites] == ["v1"]
    assert favorites[0].title == "Sepultura - Territory"
    assert store.path.exists()  # migrated to JSON so later toggles persist there


def test_favorites_store_raises_config_error_for_corrupt_json(tmp_path: Path) -> None:
    store = _favorites(tmp_path)
    store.path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ConfigError, match="favorites.json"):
        store.list()


def test_favorites_store_raises_config_error_for_non_array_payload(tmp_path: Path) -> None:
    store = _favorites(tmp_path)
    store.path.write_text('{"v1": {}}', encoding="utf-8")

    with pytest.raises(ConfigError, match="favorites.json"):
        store.ids()


def test_local_playlist_store_adds_removes_and_lists_tracks(tmp_path: Path) -> None:
    store = LocalPlaylistStore(playlists_dir=tmp_path / "playlists")
    candidate = SongCandidate(
        video_id="v1",
        title="Territory",
        artists=["Sepultura"],
        album="Chaos A.D.",
    )

    playlist = store.add_track("Metal Picks", candidate)
    duplicate = store.add_track("Metal Picks", candidate)

    assert playlist.id == "metal-picks"
    assert duplicate.video_ids == ["v1"]
    assert store.search_items()[0].display_name == "LOCAL PLAYLIST  Metal Picks"

    updated = store.remove_track("metal-picks", "v1")

    assert updated.video_ids == []


def test_plan_store_load_raises_config_error_for_corrupt_json(tmp_path: Path) -> None:
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    (plans_dir / "myplan.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigError, match="myplan.json"):
        PlanStore(plans_dir=plans_dir).load("myplan")


def test_local_playlist_store_load_raises_config_error_for_corrupt_json(
    tmp_path: Path,
) -> None:
    store = LocalPlaylistStore(playlists_dir=tmp_path)
    (tmp_path / "mix.json").write_text("not json", encoding="utf-8")

    with pytest.raises(ConfigError, match="mix.json"):
        store.load("mix")


def test_local_playlist_store_list_skips_corrupt_file_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = LocalPlaylistStore(playlists_dir=tmp_path)
    store.save(LocalPlaylist(id="good", name="Good"))
    (tmp_path / "bad.json").write_text("{oops", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="bester_ytm.stores"):
        playlists = store.list()

    assert [playlist.id for playlist in playlists] == ["good"]
    assert "bad.json" in caplog.text
