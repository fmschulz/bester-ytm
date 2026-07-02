import logging
from pathlib import Path

import pytest

from bester_ytm.config import ConfigError
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.stores import LocalPlaylist, LocalPlaylistStore, PlanStore, TrackMetadataStore


def test_track_metadata_store_clamps_ratings_and_normalizes_tags(
    tmp_path: Path,
) -> None:
    store = TrackMetadataStore(path=tmp_path / "metadata.json")

    assert store.set_rating("v1", 9).rating == 3
    assert store.set_rating("v1", -2).rating == 0
    # Legacy entries rated on the old 0-5 scale clamp to the new maximum.
    assert store.set_rating("v2", 5).rating == 3

    metadata = store.set_tags("v1", [" Metal ", "metal", "", "Thrash"])

    assert metadata.tags == ["metal", "thrash"]
    assert store.get("v1").tags == ["metal", "thrash"]


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


def test_track_metadata_store_raises_config_error_for_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "metadata.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ConfigError, match="metadata.json"):
        TrackMetadataStore(path=path).get("v1")


def test_track_metadata_store_raises_config_error_for_non_object_payload(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metadata.json"
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(ConfigError, match="metadata.json"):
        TrackMetadataStore(path=path).get("v1")


def test_track_metadata_store_raises_config_error_for_invalid_entry(tmp_path: Path) -> None:
    path = tmp_path / "metadata.json"
    path.write_text('{"v1": {"rating": "loud"}}', encoding="utf-8")

    with pytest.raises(ConfigError, match="metadata.json"):
        TrackMetadataStore(path=path).get("v1")


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
