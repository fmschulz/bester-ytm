from pathlib import Path

from bester_ytm.playlist_plan import (
    PlannedTrack,
    PlaylistPlan,
    SeedTrack,
    SongCandidate,
    new_plan_id,
    plan_to_markdown,
)
from bester_ytm.stores import PlanStore


def test_plan_id_slug_is_stable() -> None:
    plan_id = new_plan_id("ByteFM Inspired 30")
    assert plan_id.endswith("-bytefm-inspired-30")


def test_plan_store_roundtrip(tmp_path: Path) -> None:
    plan = PlaylistPlan(
        id="20260608-bytefm-inspired-30",
        name="ByteFM Inspired 30",
        target_count=1,
        seed_tracks=[
            SeedTrack(artist="Beach House", title="Myth", source="favs.md"),
        ],
        planned_tracks=[
            PlannedTrack(
                artist="Beach House",
                title="Myth",
                reason="Seed favorite.",
                role="seed",
                query="Beach House Myth",
                candidates=[
                    SongCandidate(
                        video_id="abc123",
                        title="Myth",
                        artists=["Beach House"],
                    )
                ],
                selected_video_id="abc123",
                confidence=0.95,
            )
        ],
    )
    store = PlanStore(tmp_path)
    json_path, md_path = store.save(plan)

    loaded = store.load("20260608-bytefm")

    assert json_path.exists()
    assert md_path.exists()
    assert loaded.selected_video_ids == ["abc123"]
    assert "Beach House - Myth" in plan_to_markdown(loaded)
