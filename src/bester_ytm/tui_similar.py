"""TUI action that queues AI-suggested tracks similar to what is playing."""

from __future__ import annotations

from .intelligence.llm import IntelligenceError, IntelligenceSettings, resolve_provider
from .playlist_plan import SongCandidate
from .similar import SIMILAR_COUNT, find_similar_candidates
from .ytm_client import YTMClientError


class SimilarActions:
    """Mixin for BesterYTMApp: g asks the configured AI for tracks that fit the queue."""

    intelligence_settings: IntelligenceSettings
    playlist_video_ids: list[str]

    def action_add_similar(self) -> None:
        seeds = self._similar_seeds()
        if not seeds:
            self._set_status("Play or queue something first; g then adds similar tracks.")
            return
        try:
            provider = resolve_provider(self.intelligence_settings)
        except IntelligenceError as exc:
            self._set_status(str(exc))
            return
        self._set_status(f"Asking {provider} for {SIMILAR_COUNT} similar tracks...")
        self.run_worker(self._add_similar_worker, name="similar", group="similar", thread=True)

    def _similar_seeds(self) -> list[SongCandidate]:
        video_ids: list[str] = []
        if self.playback.current_video_id:
            video_ids.append(self.playback.current_video_id)
        video_ids.extend(self.playback.queue)
        return [
            self.candidates_by_video_id[video_id]
            for video_id in video_ids
            if video_id in self.candidates_by_video_id
        ]

    def _add_similar_worker(self) -> None:
        """Runs on a worker thread; all UI updates go through call_from_thread."""
        try:
            candidates, provider = find_similar_candidates(
                self.client,
                self._similar_seeds(),
                SIMILAR_COUNT,
                self.intelligence_settings,
            )
        except (IntelligenceError, YTMClientError) as exc:
            self.call_from_thread(self._set_status, str(exc))
            return
        self.call_from_thread(self._finish_add_similar, candidates, provider)

    def _finish_add_similar(self, candidates: list[SongCandidate], provider: str) -> None:
        for candidate in candidates:
            self.candidates_by_video_id[candidate.video_id] = candidate
        video_ids = [candidate.video_id for candidate in candidates]
        self.playback.enqueue(video_ids)
        self.playlist_video_ids.extend(video_ids)
        self.run_worker(self._render_queue(), exclusive=False)
        names = "; ".join(candidate.display_name for candidate in candidates)
        self._set_status(f"Added {len(candidates)} similar track(s) via {provider}: {names}")
