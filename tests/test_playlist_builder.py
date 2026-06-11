from pathlib import Path

from bester_ytm.playlist_builder import PlaylistBuilder
from bester_ytm.playlist_plan import SongCandidate


class FakeClient:
    def search_songs(self, query: str, limit: int = 5) -> list[SongCandidate]:
        if query in {"Beach House Myth", "My Bloody Valentine Soon"}:
            artist, title = query.rsplit(" ", 1)
            return [
                SongCandidate(
                    video_id=f"seed-{title.lower()}",
                    title=title,
                    artists=[artist],
                    result_type="song",
                    duration_seconds=258,
                )
            ]
        return [
            SongCandidate(
                video_id=f"fill-{query.replace(' ', '-')}",
                title="Deep Cut",
                artists=[query],
                result_type="song",
                duration_seconds=210,
            )
        ]

    def get_related_candidates(self, video_id: str, limit: int = 10) -> list[SongCandidate]:
        assert video_id in {"seed-myth", "seed-soon"}
        return [
            SongCandidate(
                video_id=f"{video_id}-related1",
                title="Silver Soul",
                artists=["Beach House"],
                result_type="song",
                duration_seconds=290,
            ),
            SongCandidate(
                video_id=f"{video_id}-related2",
                title="Space Song",
                artists=["Beach House"],
                result_type="song",
                duration_seconds=320,
            ),
        ]


def test_builder_resolves_seeds_and_related_tracks(tmp_path: Path) -> None:
    favs = tmp_path / "favs.md"
    favs.write_text("- 2026-05-12 23:56:24 [ByteFM] Beach House - Myth\n", encoding="utf-8")

    plan = PlaylistBuilder(client=FakeClient()).build_from_favorites(
        source=favs,
        name="ByteFM Inspired 3",
        count=3,
    )

    assert len(plan.planned_tracks) == 3
    assert plan.resolved_count == 3
    assert plan.selected_video_ids == ["seed-myth", "seed-myth-related1", "seed-myth-related2"]
    assert plan.planned_tracks[0].role == "seed"
    assert "related to seed" in plan.planned_tracks[1].reason


def test_builder_supports_pasted_seed_text() -> None:
    plan = PlaylistBuilder(client=FakeClient()).build_from_text(
        "Beach House - Myth\nMy Bloody Valentine - Soon",
        source="paste",
        name="Pasted Seeds",
        count=2,
        brief="dreamy late night",
    )

    assert plan.brief == "dreamy late night"
    assert [seed.source for seed in plan.seed_tracks] == ["paste", "paste"]
    assert plan.selected_video_ids == ["seed-myth", "seed-soon"]


def test_artist_similarity_does_not_use_candidate_title() -> None:
    assert PlaylistBuilder._artist_similarity("Beach House", ["Beach House"]) == 1.0
    assert PlaylistBuilder._artist_similarity("Beach House", ["Unrelated Artist"]) < 0.55
