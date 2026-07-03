"""TUI action that queues AI-suggested tracks similar to what is playing."""

from __future__ import annotations

from functools import partial

from textual import events
from textual.timer import Timer

from .intelligence.llm import IntelligenceError, IntelligenceSettings, resolve_provider
from .playlist_builder import count_from_brief
from .playlist_plan import SongCandidate
from .radio import is_radio_video_id
from .similar import SIMILAR_COUNT, find_similar_candidates
from .tui_radio import NO_TRACK_INFO_MESSAGE
from .ytm_client import YTMClientError

COUNT_WINDOW_SECONDS = 1.0
SIMILAR_MAX = 30
NEED_SEEDS_MESSAGE = "Play or queue something first; g then adds similar tracks."


class SimilarActions:
    """Mixin for BesterYTMApp: g asks the configured AI for tracks that fit the queue.

    g arms a short digit window: g alone queues SIMILAR_COUNT similar songs,
    g11 queues eleven, escape cancels.
    """

    intelligence_settings: IntelligenceSettings
    playlist_video_ids: list[str]
    _similar_digits: str | None = None
    _similar_timer: Timer | None = None

    def action_add_similar(self) -> None:
        if self._similar_digits is not None:
            self._flush_similar_count()
            return
        self._begin_similar_count()

    def _begin_similar_count(self) -> None:
        if not self._similar_seeds():
            self._set_status(self._no_seeds_message())
            return
        self._similar_digits = ""
        self._set_status(
            f"Adding {SIMILAR_COUNT} similar songs; type a number to change (g11 adds 11)."
        )
        self._restart_similar_timer()

    def on_key(self, event: events.Key) -> None:
        """Digits typed right after g set how many similar tracks to fetch."""
        if self._similar_digits is None:
            return
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self._cancel_similar_count()
            self._set_status("Add similar cancelled.")
            return
        if event.character is not None and event.character.isdigit():
            event.stop()
            event.prevent_default()
            self._similar_digits += event.character
            self._set_status(f"Adding {self._pending_similar_count()} similar songs...")
            self._restart_similar_timer()
            return
        if event.key == "g":
            # Consume the key: on_key runs before binding dispatch, so the g
            # binding would otherwise fire too and arm a second window.
            event.stop()
            event.prevent_default()
        self._flush_similar_count()

    def _pending_similar_count(self) -> int:
        count = int(self._similar_digits) if self._similar_digits else SIMILAR_COUNT
        return max(1, min(SIMILAR_MAX, count))

    def _restart_similar_timer(self) -> None:
        if self._similar_timer is not None:
            self._similar_timer.stop()
        self._similar_timer = self.set_timer(COUNT_WINDOW_SECONDS, self._flush_similar_count)

    def _cancel_similar_count(self) -> None:
        self._similar_digits = None
        if self._similar_timer is not None:
            self._similar_timer.stop()
            self._similar_timer = None

    def _flush_similar_count(self) -> None:
        if self._similar_digits is None:
            return
        count = self._pending_similar_count()
        self._cancel_similar_count()
        self._launch_similar(count)

    def _start_add_tracks_brief(self, brief: str) -> None:
        """Builder briefs like 'add 5 songs similar to Four Tet' append to the
        queue instead of building a new playlist."""
        self._launch_similar(count_from_brief(brief, default=SIMILAR_COUNT), brief)

    def _launch_similar(self, count: int, brief: str = "") -> None:
        seeds = self._similar_seeds()
        if not seeds and not brief:
            self._set_status(self._no_seeds_message())
            return
        try:
            provider = resolve_provider(self.intelligence_settings)
        except IntelligenceError as exc:
            self._set_status(str(exc))
            return
        self._set_status(f"Finding {count} similar songs via {provider}...")
        self.run_worker(
            partial(self._add_similar_worker, count, brief),
            name="similar",
            group="similar",
            thread=True,
        )

    def _similar_seeds(self) -> list[SongCandidate]:
        video_ids: list[str] = []
        if self.playback.current_video_id:
            video_ids.append(self.playback.current_video_id)
        video_ids.extend(self.playback.queue)
        seeds: list[SongCandidate] = []
        for video_id in video_ids:
            if is_radio_video_id(video_id):
                # Seed from the station's live track; the station is not a song.
                seed = self._radio_track_seed(video_id)
                if seed is not None:
                    seeds.append(seed)
                continue
            if video_id in self.candidates_by_video_id:
                seeds.append(self.candidates_by_video_id[video_id])
        return seeds

    def _no_seeds_message(self) -> str:
        current = self.playback.current_video_id
        if current and is_radio_video_id(current):
            return NO_TRACK_INFO_MESSAGE
        return NEED_SEEDS_MESSAGE

    def _add_similar_worker(self, count: int, brief: str = "") -> None:
        """Runs on a worker thread; all UI updates go through call_from_thread."""
        try:
            candidates, provider = find_similar_candidates(
                self.client,
                self._similar_seeds(),
                count,
                self.intelligence_settings,
                brief=brief,
            )
        except (IntelligenceError, YTMClientError) as exc:
            self.call_from_thread(self._set_status, str(exc))
            return
        self.call_from_thread(self._finish_add_similar, candidates, provider)

    def _finish_add_similar(self, candidates: list[SongCandidate], provider: str) -> None:
        self._supersede_queue_load()
        for candidate in candidates:
            self.candidates_by_video_id[candidate.video_id] = candidate
        video_ids = [candidate.video_id for candidate in candidates]
        self.playback.enqueue(video_ids)
        self.playlist_video_ids.extend(video_ids)
        self.run_worker(self._render_queue(), exclusive=False)
        names = "; ".join(candidate.display_name for candidate in candidates)
        self._set_status(f"Added {len(candidates)} similar track(s) via {provider}: {names}")
