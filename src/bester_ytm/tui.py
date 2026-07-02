"""Application shell for the bester-ytm Textual TUI."""

from __future__ import annotations

import random

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, Static

from .config import (
    ConfigError,
    get_paths,
    load_intelligence_settings,
    load_transition_settings,
)
from .config_options import AppOptions, load_app_options
from .intelligence.llm import IntelligenceSettings
from .playback import PlaybackController, PlaybackError, PlaybackStatus
from .transitions import DEFAULT_APP_SETTINGS
from .tui_album import AlbumActions
from .tui_album_actions import AlbumQueueActions
from .tui_builder import BuilderActions
from .tui_effects import PlaybackRenderer, render_deck_status
from .tui_events import EventHandlers
from .tui_help import HelpScreen
from .tui_layout import build_layout
from .tui_library import LibraryActions
from .tui_metadata import TrackMetadataActions
from .tui_options import UiOptionsActions
from .tui_playback import PlaybackActions
from .tui_playlists import PlaylistLoadActions
from .tui_queue import QueueEditActions
from .tui_selection import SelectionActions
from .tui_similar import SimilarActions
from .tui_styles import APP_CSS
from .tui_visuals import EFFECT_ORDER, AudioLevelMeter
from .ytm_client import YTMClient


class BesterYTMApp(
    PlaylistLoadActions,
    EventHandlers,
    UiOptionsActions,
    SimilarActions,
    SelectionActions,
    QueueEditActions,
    BuilderActions,
    AlbumQueueActions,
    AlbumActions,
    PlaybackActions,
    PlaybackRenderer,
    TrackMetadataActions,
    LibraryActions,
    App[None],
):
    TITLE = "bester-ytm"
    SUB_TITLE = "YouTube Music"

    CSS = APP_CSS

    BINDINGS = [
        ("/", "focus_search", "Search"),
        ("space", "pause_resume", "Select/Pause"),
        ("n", "next_track", "Next"),
        ("s", "shuffle_queue", "Shuffle"),
        ("x", "toggle_select", "Select"),
        ("t", "cycle_transition", "Mix"),
        ("g", "add_similar", "Similar"),
        ("i", "build_playlist", "Build"),
        Binding("ctrl+p", "show_playlists", "Playlists", priority=True),
        ("q", "quit", "Quit"),
        Binding("enter", "play_selected", "Play/Add"),
        Binding("shift+space", "range_select", "Range select", show=False),
        Binding("p", "previous_track", "Previous", show=False),
        Binding("b", "previous_track", "Previous", show=False),
        Binding("v", "cycle_visualizer", "Visuals", show=False),
        Binding("left_square_bracket", "fade_shorter", "Fade-", key_display="[", show=False),
        Binding("right_square_bracket", "fade_longer", "Fade+", key_display="]", show=False),
        Binding("left", "seek_backward", "-10s", show=False),
        Binding("right", "seek_forward", "+10s", show=False),
        Binding("comma", "seek_large_backward", "-30s", key_display=",", show=False),
        Binding("full_stop", "seek_large_forward", "+30s", key_display=".", show=False),
        Binding("minus", "volume_down", "Vol-", key_display="-", show=False),
        Binding("equals_sign", "volume_up", "Vol+", key_display="=", show=False),
        Binding("plus", "volume_up", "Vol+", key_display="+", show=False),
        Binding("m", "mute", "Mute", show=False),
        Binding("r", "cycle_rating", "Rate", show=False),
        Binding("c", "clear_queue", "Clear"),
        Binding("d", "remove_from_queue", "Remove"),
        Binding("k", "move_queue_track_up", "Move up", show=False),
        Binding("j", "move_queue_track_down", "Move down", show=False),
        Binding("w", "save_queue_playlist", "Save"),
        Binding("f", "favorite_current", "Favorite", show=False),
        Binding("tab", "focus_next", "Next pane", show=False),
        Binding("shift+tab", "focus_previous", "Previous pane", show=False),
        Binding("a", "add_to_queue", "Add"),
        Binding("A", "play_album", "Play album", show=False),
        Binding("ctrl+a", "auth_status", "Auth", show=False),
        Binding("question_mark", "help", "Help", key_display="?"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.client = YTMClient(authenticated=False)
        self._config_error: str | None = None
        try:
            self.transition_settings = load_transition_settings()
        except ConfigError as exc:
            self.transition_settings = DEFAULT_APP_SETTINGS
            self._config_error = str(exc)
        try:
            self.intelligence_settings = load_intelligence_settings()
        except ConfigError as exc:
            self.intelligence_settings = IntelligenceSettings()
            self._config_error = self._config_error or str(exc)
        try:
            self.app_options = load_app_options()
        except ConfigError as exc:
            self.app_options = AppOptions()
            self._config_error = self._config_error or str(exc)
        self.playback = PlaybackController(
            transition=self.transition_settings,
            master_volume=self.app_options.volume,
        )
        self.current_candidate = None
        self.candidates_by_video_id = {}
        self.playlist_video_ids: list[str] = []
        self.playlist_title = "Queue"
        self.active_local_playlist_id: str | None = None
        self.active_youtube_playlist_id: str | None = None
        self._pending_playlist_delete: str | None = None
        self._results_load_id = 0
        self._results_focus_snapshot: tuple[object | None, str | None] = (None, None)
        self._queue_load_id = 0
        self._play_queue_after_load = False
        self.selected_queue_video_id: str | None = None
        self._rendered_now_playing_id: str | None = None
        self._synced_current_video_id: str | None = None
        self._queue_render_active = False
        self._queue_render_pending = False
        self._queue_render_focus: str | None = None
        self._last_visual_state: str | None = "unset"
        self.visual_fps = self.app_options.visual_fps
        self.playback_was_active = False
        self.auto_advance_pending = False
        self.was_mixing = False
        self.visualizer_effect = (
            self.app_options.visualizer
            if self.app_options.visualizer in EFFECT_ORDER
            else "mythos"
        )
        self.selected_result_video_ids: set[str] = set()
        self.result_selection_anchor_video_id: str | None = None
        self.build_in_progress = False
        self.visual_phase = 0.0
        self.audio_levels: list[float] = []
        self.last_playback_status: PlaybackStatus | None = None
        self.audio_meter = AudioLevelMeter(
            1.0 / self.visual_fps if self.visual_fps else 1.0
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield from build_layout(self._idle_visualizer_text(), self.visualizer_effect)
        yield Footer()

    def _idle_visualizer_text(self) -> str:
        return render_deck_status(
            PlaybackStatus(
                running=False,
                transition_style=self.transition_settings.style.value,
                fade_seconds=self.transition_settings.fade_seconds,
            )
        )

    async def on_mount(self) -> None:
        self._apply_branded_theme()
        self._apply_saved_pane_widths()
        self.query_one("#search", Input).focus()
        self._set_status(self._startup_status())
        self.set_interval(0.75, self._refresh_playback)
        self._animate_visual_panel()  # draw an initial frame even when visuals are off
        if self.visual_fps > 0:
            self.set_interval(1.0 / self.visual_fps, self._animate_visual_panel)

    def _startup_status(self) -> str:
        if self._config_error:
            return self._config_error
        paths = get_paths()
        if paths.oauth_token.exists() or paths.browser_auth.exists():
            return "Logged in to YouTube Music."
        return (
            "Not logged in: search and playback work now; "
            "run 'bester-ytm auth login' for library and playlist features."
        )

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _query_optional(self, selector: str, widget_type=None):
        try:
            if widget_type is None:
                return self.query_one(selector)
            return self.query_one(selector, widget_type)
        except Exception:
            return None

    async def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    async def action_shuffle_queue(self) -> None:
        try:
            status = self.playback.status()
        except PlaybackError as exc:
            self._set_status(str(exc))
            return

        current = status.current_video_id
        visible = list(self.playlist_video_ids or self.playback.queue)
        if current:
            visible = [video_id for video_id in visible if video_id != current]
            if not visible:
                self._set_status("Nothing else to shuffle.")
                return
            random.shuffle(visible)
            self.playlist_video_ids = [current, *visible]
            self.playback.queue = list(visible)
        else:
            visible = list(visible)
            if len(visible) < 2:
                self._set_status("Nothing to shuffle.")
                return
            random.shuffle(visible)
            self.playlist_video_ids = visible
            self.playback.replace_queue(visible)
            self.playback_was_active = False

        await self._render_queue()
        self._set_status(f"Shuffled {len(visible)} upcoming track(s).")

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    async def action_quit(self) -> None:
        """Stop the live mpv and any crossfade decks before exiting."""
        self.playback.stop()
        self.exit()

    async def action_auth_status(self) -> None:
        try:
            status = YTMClient(authenticated=True).auth_status()
        except ConfigError as exc:
            self._set_status(str(exc))
            return
        self._set_status(
            f"Auth {status.authenticated} via {status.backend}; "
            f"library playlists seen {status.library_playlists_seen}."
        )


def run_tui() -> None:
    app = BesterYTMApp()
    try:
        app.run()
    finally:
        # Reap mpv decks even when the app exits via crash or Ctrl+C.
        app.playback.stop()
