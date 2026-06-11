from pathlib import Path

import pytest

from bester_ytm.playlist_create import PlaylistCreateError, create_or_update_playlist
from bester_ytm.playlist_plan import PlannedTrack, PlaylistPlan, SeedTrack, SongCandidate
from bester_ytm.stores import PlanStore
from bester_ytm.ytm_client import PlaylistSnapshot


def _plan(playlist_id: str | None = None) -> PlaylistPlan:
    return PlaylistPlan(
        id="20260608-bytefm-inspired-2",
        name="ByteFM Inspired 2",
        target_count=2,
        playlist_id=playlist_id,
        seed_tracks=[SeedTrack(artist="Beach House", title="Myth", source="favs.md")],
        planned_tracks=[
            PlannedTrack(
                artist="Beach House",
                title="Myth",
                reason="Seed favorite.",
                role="seed",
                query="Beach House Myth",
                candidates=[SongCandidate(video_id="v1", title="Myth", artists=["Beach House"])],
                selected_video_id="v1",
                confidence=1.0,
            ),
            PlannedTrack(
                artist="Beach House",
                title="Silver Soul",
                reason="Related track.",
                role="related",
                query="Beach House Silver Soul",
                candidates=[
                    SongCandidate(video_id="v2", title="Silver Soul", artists=["Beach House"])
                ],
                selected_video_id="v2",
                confidence=0.8,
            ),
        ],
    )


class FakeCreateClient:
    def __init__(self, snapshot_ids: list[str]) -> None:
        self.snapshot_ids = snapshot_ids
        self.created_payload = None
        self.added_payload = None

    def create_playlist(
        self,
        title: str,
        description: str,
        privacy: str,
        video_ids: list[str],
    ) -> str:
        self.created_payload = (title, description, privacy, video_ids)
        return "PL123"

    def add_playlist_items(self, playlist_id: str, video_ids: list[str]) -> None:
        self.added_payload = (playlist_id, video_ids)

    def get_playlist(self, playlist_id: str) -> PlaylistSnapshot:
        return PlaylistSnapshot(playlist_id=playlist_id, video_ids=self.snapshot_ids)


def test_create_playlist_verifies_and_persists_plan(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(tmp_path)
    client = FakeCreateClient(snapshot_ids=["v1", "v2"])

    result = create_or_update_playlist(plan, client, store)

    assert result.verified
    assert result.created
    assert result.playlist_id == "PL123"
    assert client.created_payload is not None
    assert client.created_payload[3] == []
    assert client.added_payload == ("PL123", ["v1", "v2"])
    persisted = store.load(plan.id)
    assert persisted.playlist_id == "PL123"
    assert persisted.verified is True


def test_update_playlist_adds_items_and_verifies(tmp_path: Path) -> None:
    plan = _plan(playlist_id="PL456")
    store = PlanStore(tmp_path)
    client = FakeCreateClient(snapshot_ids=["v1", "v2"])

    result = create_or_update_playlist(plan, client, store)

    assert result.verified
    assert not result.created
    assert client.created_payload is None
    assert client.added_payload == ("PL456", ["v1", "v2"])


def test_create_playlist_records_missing_tracks(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(tmp_path)
    client = FakeCreateClient(snapshot_ids=["v1"])

    result = create_or_update_playlist(plan, client, store)

    assert not result.verified
    assert result.missing_video_ids == ["v2"]
    assert store.load(plan.id).verified is False


def test_create_playlist_requires_resolved_tracks(tmp_path: Path) -> None:
    plan = PlaylistPlan(id="empty", name="Empty", target_count=1)

    with pytest.raises(PlaylistCreateError):
        create_or_update_playlist(plan, FakeCreateClient(snapshot_ids=[]), PlanStore(tmp_path))
