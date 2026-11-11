"""Playlist-builder actions: seeds or briefs in, a built plan out, off the UI thread."""

from __future__ import annotations

import re
from functools import partial
from pathlib import Path
from threading import Event
from time import monotonic

from textual.timer import Timer
from textual.widgets import TextArea

from .config import ConfigError, resolve_existing_input
from .config_options import AppOptions
from .intelligence.llm import resolve_provider
from .intelligence.settings import IntelligenceError, IntelligenceSettings
from .playlist_brief import count_from_brief, name_from_brief
from .playlist_builder import PlaylistBuilder, PlaylistBuildError
from .playlist_plan import PlaylistPlan, parse_seed_text
from .stores import PlanStore
from .tui_radio import parse_add_station_request

# "Add 5 songs similar to Four Tet" grows the queue; it is not a new playlist.
ADD_TRACKS_PATTERN = re.compile(r"^\s*(?:please\s+)?(?:add|queue|append)\b", re.IGNORECASE)


def _normalize_build_inputs(builder_text: str, brief: str) -> tuple[str, str]:
    """Treat prose typed into the seed box ('make me a playlist...') as a brief."""
    if builder_text and not parse_seed_text(builder_text, "tui-paste"):
        merged = f"{builder_text}; {brief}" if brief else builder_text
        return "", merged
    return builder_text, brief


class BuilderActions:
    """Mixin for BesterYTMApp: i (or Enter in the brief field) builds playlist plans."""

    build_in_progress: bool
    intelligence_settings: IntelligenceSettings
    app_options: AppOptions
    playlist_video_ids: list[str]
    _build_cancel: Event | None = None
    _build_timer: Timer | None = None
    _build_started: float = 0.0

    async def action_build_playlist(self) -> None:
        if self.build_in_progress:
            self._set_status("A playlist build is already running; wait for it to finish.")
            return
        builder_text = self.query_one("#builder", TextArea).text.strip()
        station_request = parse_add_station_request(builder_text)
        if station_request:
            self._start_add_radio_station(station_request)
            return
        if ADD_TRACKS_PATTERN.match(builder_text):
            self._start_add_tracks_brief(builder_text)
            return
        builder_text, brief = _normalize_build_inputs(builder_text, "")
        if not builder_text and not brief and not self._has_default_favorites():
            self._set_status(
                "Describe the playlist you want (e.g. '10 songs similar to ...') "
                "or paste 'Artist - Title' lines, then press Build."
            )
            return
        cancel = self._begin_build()
        self._set_status(self._build_start_message(builder_text, brief))
        self.run_worker(
            partial(self._build_playlist_worker, builder_text, brief, cancel=cancel),
            name="builder",
            group="builder",
            thread=True,
        )

    def _begin_build(self) -> Event:
        self.build_in_progress = True
        self._build_cancel = Event()
        self._build_started = monotonic()
        self.query_one("#cancel-build-button").display = True
        self._update_build_progress()
        self._build_timer = self.set_interval(1.0, self._update_build_progress)
        return self._build_cancel

    def _update_build_progress(self) -> None:
        if self.build_in_progress:
            elapsed = max(0, int(monotonic() - self._build_started))
            minutes, seconds = divmod(elapsed, 60)
            self.query_one("#center").border_title = f"Building playlist… {minutes}:{seconds:02d}"

    def _end_build(self) -> None:
        self.build_in_progress = False
        if self._build_timer is not None:
            self._build_timer.stop()
            self._build_timer = None
        self.query_one("#cancel-build-button").display = False
        self._update_queue_title(self.playlist_video_ids or self.playback.queue)

    def action_cancel_build(self) -> None:
        if not self.build_in_progress or self._build_cancel is None:
            return
        self._build_cancel.set()
        self._end_build()
        self._set_status("Playlist build cancelled.")

    def _favorites_source(self) -> Path:
        configured = self.app_options.favorites_file
        if configured is None:
            raise ConfigError("Set [builder] favorites_file to use a seeds file.")
        return resolve_existing_input(configured)

    def _has_default_favorites(self) -> bool:
        try:
            self._favorites_source()
        except ConfigError:
            return False
        return True

    def _build_start_message(self, builder_text: str, brief: str) -> str:
        if builder_text or not brief:
            return "Building playlist..."
        try:
            provider = resolve_provider(self.intelligence_settings)
        except IntelligenceError:
            return "Building playlist from brief..."
        return f"Building playlist from brief via {provider} (this can take a minute)..."

    def _build_playlist_worker(self, builder_text: str, brief: str, *, cancel: Event) -> None:
        """Runs on a worker thread so slow AI/network builds never freeze the UI."""
        try:
            plan, message = self._run_playlist_build(builder_text, brief, cancel)
        except (ConfigError, PlaylistBuildError, IntelligenceError) as exc:
            self.call_from_thread(self._report_build_failure, str(exc), cancel)
            return
        self.call_from_thread(self._complete_playlist_build, plan, message, cancel)

    def _complete_playlist_build(self, plan: PlaylistPlan, message: str, cancel: Event) -> None:
        if cancel.is_set() or cancel is not self._build_cancel:
            return
        self._end_build()
        self._finish_playlist_build(plan, message)

    def _report_build_failure(self, message: str, cancel: Event) -> None:
        if cancel.is_set() or cancel is not self._build_cancel:
            return
        self._end_build()
        self._report_error(message)

    def _run_playlist_build(
        self, builder_text: str, brief: str, cancel: Event | None = None
    ) -> tuple[PlaylistPlan, str]:
        if builder_text:
            plan = PlaylistBuilder().build_from_text(
                builder_text,
                source="tui-paste",
                name="TUI Inspired 30",
                count=30,
                brief=brief,
            )
        elif brief:
            plan = PlaylistBuilder().build_from_brief(
                brief, name=name_from_brief(brief), count=count_from_brief(brief), cancel=cancel
            )
        else:
            source = self._favorites_source()
            plan = PlaylistBuilder().build_from_favorites(
                source,
                name="Favorites Inspired 30",
                count=30,
                brief=brief,
            )
        if cancel is not None and cancel.is_set():
            raise IntelligenceError("Playlist build cancelled.")
        json_path, _ = PlanStore().save(plan)
        message = (
            f"plan saved: {json_path.name} ({plan.resolved_count}/{plan.target_count} resolved)."
        )
        return plan, message
