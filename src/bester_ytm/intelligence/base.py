from __future__ import annotations

from abc import ABC, abstractmethod

from ..playlist_plan import PlannedTrack, PlaylistPlan, RankedCandidate, SeedTrack, SongCandidate


class IntelligenceProvider(ABC):
    @abstractmethod
    def build_playlist_plan(
        self,
        seeds: list[SeedTrack],
        count: int,
        brief: str,
        name: str,
    ) -> PlaylistPlan:
        """Create a draft plan before YouTube Music resolution."""

    @abstractmethod
    def rank_candidates(
        self,
        target: PlannedTrack,
        candidates: list[SongCandidate],
    ) -> RankedCandidate | None:
        """Rank concrete YouTube Music candidates for a planned track."""
