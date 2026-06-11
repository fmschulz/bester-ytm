from pathlib import Path

from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.stores import LocalPlaylistStore, TrackMetadataStore


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
