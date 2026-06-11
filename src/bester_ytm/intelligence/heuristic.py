from __future__ import annotations

from datetime import UTC, datetime

from ..playlist_plan import (
    PlannedTrack,
    PlaylistPlan,
    RankedCandidate,
    SeedTrack,
    SongCandidate,
    new_plan_id,
)
from ..resolver import Resolver
from .base import IntelligenceProvider


class HeuristicProvider(IntelligenceProvider):
    """Deterministic fallback provider using seeds and YouTube Music related tracks."""

    def __init__(self, allow_variants: bool = False) -> None:
        self.resolver = Resolver(allow_variants=allow_variants)

    def build_playlist_plan(
        self,
        seeds: list[SeedTrack],
        count: int,
        brief: str,
        name: str,
    ) -> PlaylistPlan:
        selected = seeds[:count]
        planned_tracks = [
            PlannedTrack(
                artist=seed.artist,
                title=seed.title,
                reason=f"Seed track imported from {seed.source}.",
                role="seed",
                query=seed.query,
            )
            for seed in selected
        ]
        return PlaylistPlan(
            id=new_plan_id(name, datetime.now(UTC)),
            name=name,
            target_count=count,
            seed_tracks=seeds,
            planned_tracks=planned_tracks,
            brief=brief,
        )

    def plan_related_track(
        self,
        candidate: SongCandidate,
        seed: SeedTrack,
        existing_video_ids: set[str],
    ) -> PlannedTrack | None:
        if candidate.video_id in existing_video_ids:
            return None
        artist = candidate.artists[0] if candidate.artists else "Unknown artist"
        return PlannedTrack(
            artist=artist,
            title=candidate.title,
            reason=(
                f"YouTube Music returned this as related to seed "
                f"{seed.artist} - {seed.title}."
            ),
            role="related",
            query=f"{artist} {candidate.title}",
            candidates=[candidate],
            selected_video_id=candidate.video_id,
            confidence=0.72,
        )

    def rank_candidates(
        self,
        target: PlannedTrack,
        candidates: list[SongCandidate],
    ) -> RankedCandidate | None:
        return self.resolver.select_best(target, candidates)
