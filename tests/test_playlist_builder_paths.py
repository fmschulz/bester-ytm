from __future__ import annotations

from pathlib import Path

import pytest

from bester_ytm.playlist_builder import PlaylistBuilder, PlaylistBuildError
from bester_ytm.playlist_plan import SeedTrack, SongCandidate
from bester_ytm.ytm_client import YTMClientError


def _seed(artist: str, title: str) -> SeedTrack:
    return SeedTrack(artist=artist, title=title, source="test")


def _song(video_id: str, title: str, artist: str) -> SongCandidate:
    return SongCandidate(
        video_id=video_id,
        title=title,
        artists=[artist],
        result_type="song",
        duration_seconds=240,
    )


class ScriptedClient:
    """Maps queries to candidate lists and seed videos to related lists."""

    def __init__(
        self,
        searches: dict[str, list[SongCandidate] | Exception] | None = None,
        related: dict[str, list[SongCandidate] | Exception] | None = None,
    ) -> None:
        self.searches = searches or {}
        self.related = related or {}

    def search_songs(self, query: str, limit: int = 5) -> list[SongCandidate]:
        result = self.searches.get(query, [])
        if isinstance(result, Exception):
            raise result
        return result

    def get_related_candidates(self, video_id: str, limit: int = 10) -> list[SongCandidate]:
        result = self.related.get(video_id, [])
        if isinstance(result, Exception):
            raise result
        return result


def test_build_from_favorites_validates_count_and_source(tmp_path: Path) -> None:
    favs = tmp_path / "favs.md"
    favs.write_text("- Beach House - Myth\n", encoding="utf-8")

    builder = PlaylistBuilder(client=ScriptedClient())
    with pytest.raises(PlaylistBuildError, match="count must be at least 1"):
        builder.build_from_favorites(favs, name="Mix", count=0)

    with pytest.raises(PlaylistBuildError, match="does not exist"):
        builder.build_from_favorites(tmp_path / "missing.md", name="Mix", count=1)


def test_build_from_favorites_requires_seed_lines(tmp_path: Path) -> None:
    favs = tmp_path / "favs.md"
    favs.write_text("# only a heading\n", encoding="utf-8")

    with pytest.raises(PlaylistBuildError, match="No seed tracks found"):
        PlaylistBuilder(client=ScriptedClient()).build_from_favorites(
            favs, name="Mix", count=1
        )


def test_build_from_text_validates_count_and_seeds() -> None:
    builder = PlaylistBuilder(client=ScriptedClient())

    with pytest.raises(PlaylistBuildError, match="count must be at least 1"):
        builder.build_from_text("Beach House - Myth", source="paste", name="Mix", count=0)

    with pytest.raises(PlaylistBuildError, match="No seed tracks found in paste"):
        builder.build_from_text("no separator here", source="paste", name="Mix", count=1)


def test_resolution_failure_is_recorded_on_the_track() -> None:
    client = ScriptedClient(searches={"Beach House Myth": YTMClientError("offline")})

    plan = PlaylistBuilder(client=client).build_from_seeds(
        [_seed("Beach House", "Myth")], name="Mix", count=1
    )

    assert plan.resolved_count == 0
    assert "Resolution failed: offline." in plan.planned_tracks[0].reason


def test_unresolved_seeds_are_skipped_for_related_lookup() -> None:
    client = ScriptedClient(searches={"Beach House Myth": []})

    plan = PlaylistBuilder(client=client).build_from_seeds(
        [_seed("Beach House", "Myth")], name="Mix", count=2
    )

    assert plan.resolved_count == 0
    assert len(plan.planned_tracks) == 1


def test_related_lookup_failure_is_recorded_and_fill_continues() -> None:
    client = ScriptedClient(
        searches={
            "Beach House Myth": [_song("seed-1", "Myth", "Beach House")],
            "Beach House": [_song("fill-1", "Lazuli", "Beach House")],
        },
        related={"seed-1": YTMClientError("offline")},
    )

    plan = PlaylistBuilder(client=client).build_from_seeds(
        [_seed("Beach House", "Myth")], name="Mix", count=2
    )

    assert "Related lookup failed: offline." in plan.planned_tracks[0].reason
    assert plan.selected_video_ids == ["seed-1", "fill-1"]


def test_related_round_robin_stops_at_target_count() -> None:
    client = ScriptedClient(
        searches={
            "Beach House Myth": [_song("seed-1", "Myth", "Beach House")],
            "Slowdive Alison": [_song("seed-2", "Alison", "Slowdive")],
        },
        related={
            "seed-1": [_song("rel-1", "PPP", "Beach House")],
            "seed-2": [_song("rel-2", "Souvlaki", "Slowdive")],
        },
    )

    plan = PlaylistBuilder(client=client).build_from_seeds(
        [_seed("Beach House", "Myth"), _seed("Slowdive", "Alison")],
        name="Mix",
        count=3,
    )

    assert plan.selected_video_ids == ["seed-1", "seed-2", "rel-1"]


def test_related_skips_variants_and_duplicates_then_fills_from_artists() -> None:
    client = ScriptedClient(
        searches={
            "Beach House Myth": [_song("seed-1", "Myth", "Beach House")],
            "Slowdive Alison": [_song("seed-2", "Alison", "Slowdive")],
            "Beach House": [
                _song("live-1", "Myth (Live)", "Beach House"),
                _song("rel-a", "Space Song", "Beach House"),
                _song("other-1", "Wrong", "Completely Different Band"),
                _song("fill-1", "Lazuli", "Beach House"),
            ],
            "Slowdive": [_song("fill-2", "Sugar", "Slowdive")],
        },
        related={
            "seed-1": [
                _song("live-2", "Myth (Remix)", "Beach House"),
                _song("seed-1", "Myth", "Beach House"),
                _song("rel-a", "Space Song", "Beach House"),
            ],
            "seed-2": [_song("rel-b", "When the Sun Hits", "Slowdive")],
        },
    )

    plan = PlaylistBuilder(client=client).build_from_seeds(
        [_seed("Beach House", "Myth"), _seed("Slowdive", "Alison")],
        name="Mix",
        count=6,
    )

    assert plan.selected_video_ids == [
        "seed-1",
        "seed-2",
        "rel-b",
        "rel-a",
        "fill-1",
        "fill-2",
    ]
    fill_track = plan.planned_tracks[4]
    assert fill_track.role == "deep_cut"
    assert "Fallback discovery from the seed artist Beach House" in fill_track.reason


def test_fill_search_failures_are_ignored() -> None:
    client = ScriptedClient(
        searches={
            "Beach House Myth": [_song("seed-1", "Myth", "Beach House")],
            "Beach House": YTMClientError("offline"),
        },
        related={"seed-1": []},
    )

    plan = PlaylistBuilder(client=client).build_from_seeds(
        [_seed("Beach House", "Myth")], name="Mix", count=3
    )

    assert plan.selected_video_ids == ["seed-1"]


def test_artist_similarity_returns_zero_without_artists() -> None:
    assert PlaylistBuilder._artist_similarity("Beach House", []) == 0.0
