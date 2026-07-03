"""Playlist-builder actions: seeds or briefs in, a built plan out, off the UI thread."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from textual.widgets import Label, TextArea

from .config import ConfigError, resolve_existing_input
from .config_options import AppOptions
from .intelligence.llm import IntelligenceError, IntelligenceSettings, resolve_provider
from .playlist_builder import (
    PlaylistBuilder,
    PlaylistBuildError,
    count_from_brief,
    name_from_brief,
)
from .playlist_plan import PlaylistPlan, parse_seed_text
from .stores import FavoritesStore, PlanStore
from .tui_radio import parse_add_station_request

FALLBACK_FAVORITES = Path("../tuiradio/favs.md")


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

    async def action_build_playlist(self) -> None:
        if self.build_in_progress:
            self._set_status("A playlist build is already running; wait for it to finish.")
            return
        builder_text = self.query_one("#builder", TextArea).text.strip()
        station_request = parse_add_station_request(builder_text)
        if station_request:
            self._start_add_radio_station(station_request)
            return
        builder_text, brief = _normalize_build_inputs(builder_text, "")
        if not builder_text and not brief and not self._has_default_favorites():
            self._set_status(
                "Describe the playlist you want (e.g. '10 songs similar to ...') "
                "or paste 'Artist - Title' lines, then press Build."
            )
            return
        self.build_in_progress = True
        title = self._query_optional("#queue-title", Label)
        if title:
            title.update("Building playlist...")
        self._set_status(self._build_start_message(builder_text, brief))
        self.run_worker(
            partial(self._build_playlist_worker, builder_text, brief),
            name="builder",
            group="builder",
            thread=True,
        )

    def _favorites_source(self) -> Path:
        configured = self.app_options.favorites_file
        return resolve_existing_input(configured or FALLBACK_FAVORITES)

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

    def _build_playlist_worker(self, builder_text: str, brief: str) -> None:
        """Runs on a worker thread so slow AI/network builds never freeze the UI."""
        try:
            plan, message = self._run_playlist_build(builder_text, brief)
        except (ConfigError, PlaylistBuildError, IntelligenceError) as exc:
            self.call_from_thread(self._report_build_failure, str(exc))
            return
        self.call_from_thread(self._finish_playlist_build, plan, message)

    def _report_build_failure(self, message: str) -> None:
        self.build_in_progress = False
        self._update_queue_title(len(self.playlist_video_ids or self.playback.queue))
        self._set_status(message)

    def _run_playlist_build(self, builder_text: str, brief: str) -> tuple[PlaylistPlan, str]:
        if builder_text:
            imported = 0
            plan = PlaylistBuilder().build_from_text(
                builder_text,
                source="tui-paste",
                name="TUI Inspired 30",
                count=30,
                brief=brief,
            )
        elif brief:
            imported = 0
            plan = PlaylistBuilder().build_from_brief(
                brief, name=name_from_brief(brief), count=count_from_brief(brief)
            )
        else:
            source = self._favorites_source()
            imported = FavoritesStore().import_tuiradio(source)
            plan = PlaylistBuilder().build_from_favorites(
                source,
                name="ByteFM Inspired 30",
                count=30,
                brief=brief,
            )
        json_path, _ = PlanStore().save(plan)
        imported_text = f"Imported {imported} favorites; " if imported else ""
        message = (
            f"{imported_text}plan saved: {json_path.name} "
            f"({plan.resolved_count}/{plan.target_count} resolved)."
        )
        return plan, message
