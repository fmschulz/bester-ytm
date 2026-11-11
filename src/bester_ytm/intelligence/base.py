from __future__ import annotations

from abc import ABC, abstractmethod

from ..playlist_plan import PlaylistPlan, SeedTrack


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
