"""Application shell for the bester-ytm Textual TUI."""

from __future__ import annotations

import inspect
import random
from collections.abc import Mapping
from functools import partial

from textual import events
from textual.actions import ActionParseResult
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.dom import DOMNode
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
)

from .config import (
    ConfigError,
    get_paths,
    load_intelligence_settings,
    load_transition_settings,
)
from .config_options import AppOptions, load_app_options, save_ui_options
from .intelligence.llm import IntelligenceSettings
from .playback import PlaybackController, PlaybackError, PlaybackStatus
from .search_query import SearchItem
from .stores import LocalPlaylistStore
from .transitions import DEFAULT_APP_SETTINGS
from .tui_album import AlbumActions
from .tui_builder import BuilderActions
from .tui_effects import PlaybackRenderer, render_deck_status
from .tui_help import HelpScreen
from .tui_layout import BuilderTextArea, build_layout
from .tui_library import LibraryActions
from .tui_playback import PlaybackActions
from .tui_queue import QueueEditActions
from .tui_selection import SelectionActions
from .tui_similar import SimilarActions
from .tui_splitter import PaneSplitter
from .tui_styles import APP_CSS
from .tui_theme import EMBER_THEME
from .tui_visuals import EFFECT_ORDER, AudioLevelMeter
from .ytm_client import PlaylistSnapshot, YTMClient, YTMClientError


class BesterYTMApp(
    SimilarActions,
    SelectionActions,
    QueueEditActions,
    BuilderActions,
    AlbumActions,
    PlaybackActions,
    PlaybackRenderer,
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

    BUTTON_ACTIONS = {
        "prev-button": "previous_track",
        "rewind-button": "seek_backward",
        "play-button": "pause_resume",
        "forward-button": "seek_forward",
        "next-button": "next_track",
        "shuffle-button": "shuffle_queue",
        "transition-button": "cycle_transition",
        "clear-button": "clear_queue",
        "fade-down-button": "fade_shorter",
        "fade-up-button": "fade_longer",
        "volume-down-button": "volume_down",
        "volume-up-button": "volume_up",
        "mute-button": "mute",
        "rate-down-button": "rate_down",
        "rate-up-button": "rate_up",
        "save-tags-button": "save_tags",
        "new-playlist-button": "new_playlist",
        "add-local-playlist-button": "add_to_local_playlist",
        "remove-local-playlist-button": "remove_from_playlist",
        "save-queue-button": "save_queue_playlist",
        "build-button": "build_playlist",
    }

    CONTEXT_ACTIONS = {
        "toggle_select": {"results"},
        "range_select": {"results"},
        "add_to_queue": {"results"},
        "play_album": {"results"},
        "shuffle_queue": {"queue", "results"},
        "play_selected": {"results", "queue"},
        "remove_from_queue": {"queue", "results"},
        "move_queue_track_up": {"queue"},
        "move_queue_track_down": {"queue"},
        "clear_queue": {"queue"},
        "save_queue_playlist": {"queue"},
    }

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

    def action_cycle_visualizer(self) -> None:
        names = list(EFFECT_ORDER)
        position = names.index(self.visualizer_effect) if self.visualizer_effect in names else 0
        self._apply_visualizer_effect(names[(position + 1) % len(names)])
        select = self._query_optional("#effect-select", Select)
        if select is not None:
            select.value = self.visualizer_effect

    def _apply_visualizer_effect(self, effect: str) -> None:
        self.visualizer_effect = effect
        self._refresh_playback()
        self._save_ui_options()
        self._set_status(f"Visualizer: {effect}.")

    def on_pane_splitter_resized(self, event: PaneSplitter.Resized) -> None:
        self._save_ui_options(
            left_width=self.query_one("#left").size.width,
            right_width=self.query_one("#right").size.width,
        )

    def _save_ui_options(
        self, left_width: int | None = None, right_width: int | None = None
    ) -> None:
        try:
            save_ui_options(
                self.visualizer_effect, left_width, right_width, theme=str(self.theme)
            )
        except ConfigError as exc:
            self._set_status(f"Settings not saved: {exc}")

    def _apply_saved_pane_widths(self) -> None:
        for selector, width in (
            ("#left", self.app_options.left_width),
            ("#right", self.app_options.right_width),
        ):
            if width is not None:
                self.query_one(selector).styles.width = width

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "effect-select" or not isinstance(event.value, str):
            return
        if event.value != self.visualizer_effect:
            self._apply_visualizer_effect(event.value)

    async def on_mount(self) -> None:
        self._apply_branded_theme()
        self._apply_saved_pane_widths()
        self.query_one("#search", Input).focus()
        self._set_status(self._startup_status())
        self.set_interval(0.75, self._refresh_playback)
        self._animate_visual_panel()  # draw an initial frame even when visuals are off
        if self.visual_fps > 0:
            self.set_interval(1.0 / self.visual_fps, self._animate_visual_panel)

    def _apply_branded_theme(self) -> None:
        """Register the ember theme, restore the saved choice, then persist future changes."""
        self.register_theme(EMBER_THEME)
        if self.app_options.theme in self.available_themes:
            self.theme = self.app_options.theme
        self.theme_changed_signal.subscribe(self, self._on_theme_changed)

    def _on_theme_changed(self, _theme: object) -> None:
        self._save_ui_options()

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

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            await self._search(event.value)

    async def on_builder_text_area_submitted(self, event: BuilderTextArea.Submitted) -> None:
        await self.action_build_playlist()

    async def run_action(
        self,
        action: str | ActionParseResult,
        default_namespace: DOMNode | None = None,
        namespaces: Mapping[str, DOMNode] | None = None,
    ) -> bool:
        """Any action other than d (remove/delete) disarms a pending playlist delete."""
        if isinstance(action, str) and action != "remove_from_queue":
            self._pending_playlist_delete = None
        return await super().run_action(action, default_namespace, namespaces)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Hide queue/results-specific footer keys unless that pane is focused."""
        contexts = self.CONTEXT_ACTIONS.get(action)
        if contexts is None:
            return True
        return True if self._focus_context() in contexts else None

    def _focus_context(self) -> str:
        try:
            node: DOMNode | None = self.focused
        except Exception:
            # No screen stack outside a running app; treat as no pane focus.
            return "other"
        while node is not None:
            if node.id == "album-tree":
                return "results"
            if node.id in ("results", "queue"):
                return node.id
            node = node.parent
        return "other"

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self.refresh_bindings()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.control.id == "results":
            event.stop()
            await self.action_play_selected()
        elif event.control.id == "queue":
            event.stop()
            await self._play_queue_item(event.item)

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.control.id != "queue":
            return
        self.selected_queue_video_id = getattr(event.item, "video_id", None)
        self._update_track_metadata(self.selected_queue_video_id)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        action_name = self.BUTTON_ACTIONS.get(event.button.id or "")
        if action_name is None:
            return
        self._pending_playlist_delete = None
        result = getattr(self, f"action_{action_name}")()
        if inspect.iscoroutine(result):
            await result

    async def on_click(self, event: events.Click) -> None:
        widget = event.widget
        while widget is not None and getattr(widget, "id", None) != "progress":
            widget = getattr(widget, "parent", None)
        if widget is None:
            return
        status = self.playback.status()
        if not status.duration_seconds:
            return
        width = max(1, widget.size.width)
        ratio = min(1.0, max(0.0, event.x / width))
        self._seek_absolute(status.duration_seconds * ratio)

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

    async def action_show_playlists(self) -> None:
        self.query_one("#search", Input).value = ""
        results = self.query_one("#results", ListView)
        await results.clear()
        self._set_status("Loading playlists...")
        # A newer search or playlist listing supersedes any in-flight one.
        self._results_load_id += 1
        local_items = LocalPlaylistStore().search_items()
        for search_item in local_items:
            await results.append(self._result_item(search_item))
        self.run_worker(
            partial(self._list_playlists_worker, local_items, self._results_load_id),
            name="playlists",
            group="playlists",
            thread=True,
        )

    def _list_playlists_worker(self, local_items: list[SearchItem], load_id: int) -> None:
        """Runs on a worker thread so a slow YouTube library never freezes the UI."""
        try:
            playlists = YTMClient(authenticated=True).list_playlists(limit=25)
        except (ConfigError, YTMClientError) as exc:
            self.call_from_thread(
                self._finish_show_playlists_error, local_items, str(exc), load_id
            )
            return
        self.call_from_thread(self._finish_show_playlists, local_items, playlists, load_id)

    def _finish_show_playlists_error(
        self, local_items: list[SearchItem], message: str, load_id: int
    ) -> None:
        if load_id != self._results_load_id:
            return
        results = self.query_one("#results", ListView)
        self._focus_first_result(results, bool(local_items))
        self._set_status(
            f"{len(local_items)} local playlist(s). YouTube library unavailable: {message}"
        )

    def _finish_show_playlists(
        self,
        local_items: list[SearchItem],
        playlists: list[PlaylistSnapshot],
        load_id: int,
    ) -> None:
        if load_id != self._results_load_id:
            return  # superseded by a newer search or playlist listing
        self.run_worker(
            self._append_youtube_playlists(local_items, playlists, load_id),
            exclusive=False,
        )

    async def _append_youtube_playlists(
        self,
        local_items: list[SearchItem],
        playlists: list[PlaylistSnapshot],
        load_id: int,
    ) -> None:
        if load_id != self._results_load_id:
            return  # a newer search or listing started after this was scheduled
        results = self.query_one("#results", ListView)
        for playlist in playlists:
            title = playlist.title or playlist.playlist_id
            item = ListItem(Label(f"{title} ({playlist.track_count})"))
            item.playlist_id = playlist.playlist_id  # type: ignore[attr-defined]
            item.playlist_title = title  # type: ignore[attr-defined]
            await results.append(item)
        self._focus_first_result(results, bool(local_items or playlists))
        self._set_status(
            f"{len(local_items)} local + {len(playlists)} YouTube playlist(s)."
        )

    async def action_pause_resume(self) -> None:
        """Space: when it triggers a deferred playlist load, play once tracks arrive."""
        self._play_queue_after_load = True
        try:
            await super().action_pause_resume()
        finally:
            self._play_queue_after_load = False

    def _supersede_queue_load(self) -> None:
        """Queue or playback state the user builds cancels any in-flight deferred load."""
        self._queue_load_id += 1

    async def _load_playlist_queue(
        self, playlist_id: str, *, authenticated: bool = True
    ) -> bool:
        """Start fetching playlist tracks off the UI thread; returns False (deferred)."""
        self._set_status("Loading playlist tracks...")
        self._queue_load_id += 1
        self.run_worker(
            partial(
                self._playlist_load_worker,
                playlist_id,
                authenticated,
                self._play_queue_after_load,
                self._queue_load_id,
            ),
            name="playlist-load",
            group="playlist-load",
            thread=True,
        )
        return False

    def _playlist_load_worker(
        self, playlist_id: str, authenticated: bool, play_after: bool, load_id: int
    ) -> None:
        """Runs on a worker thread so slow playlist fetches never freeze the UI."""
        try:
            client = YTMClient(authenticated=True) if authenticated else self.client
            snapshot = client.get_playlist(playlist_id)
        except (ConfigError, YTMClientError) as exc:
            self.call_from_thread(self._finish_playlist_load_error, str(exc), load_id)
            return
        self.call_from_thread(
            self._finish_playlist_load, snapshot, playlist_id, play_after, load_id
        )

    def _load_album_queue(self, browse_id: str, title: str) -> None:
        """Start fetching album tracks off the UI thread; the queue fills when they land."""
        self._set_status("Loading album tracks...")
        self._queue_load_id += 1
        self.run_worker(
            partial(
                self._album_load_worker,
                browse_id,
                title,
                self._play_queue_after_load,
                self._queue_load_id,
            ),
            name="album-load",
            group="playlist-load",
            thread=True,
        )

    def _album_load_worker(
        self, browse_id: str, title: str, play_after: bool, load_id: int
    ) -> None:
        """Runs on a worker thread so slow album fetches never freeze the UI."""
        try:
            snapshot = self.client.get_album(browse_id)
        except (ConfigError, YTMClientError) as exc:
            self.call_from_thread(self._finish_playlist_load_error, str(exc), load_id)
            return
        self.call_from_thread(self._finish_album_load, snapshot, title, play_after, load_id)

    def _finish_playlist_load_error(self, message: str, load_id: int) -> None:
        if load_id == self._queue_load_id:
            self._set_status(message)

    def _finish_playlist_load(
        self,
        snapshot: PlaylistSnapshot,
        playlist_id: str,
        play_after: bool,
        load_id: int,
    ) -> None:
        if load_id != self._queue_load_id:
            return  # superseded by a newer load or a queue the user built meanwhile
        if not snapshot.video_ids:
            self._set_status(f"Playlist {playlist_id} has no playable tracks.")
            return
        self.run_worker(
            self._apply_playlist_snapshot(snapshot, playlist_id, play_after, load_id),
            exclusive=False,
        )

    def _finish_album_load(
        self, snapshot: PlaylistSnapshot, title: str, play_after: bool, load_id: int
    ) -> None:
        if load_id != self._queue_load_id:
            return  # superseded by a newer load or a queue the user built meanwhile
        if not snapshot.video_ids:
            self._set_status(f"Album {title} has no playable tracks.")
            return
        self.run_worker(
            self._apply_album_snapshot(snapshot, title, play_after, load_id),
            exclusive=False,
        )

    async def _apply_playlist_snapshot(
        self, snapshot: PlaylistSnapshot, playlist_id: str, play_after: bool, load_id: int
    ) -> None:
        if load_id != self._queue_load_id:
            return  # a newer load or user-built queue landed after this was scheduled
        title = snapshot.title or playlist_id
        await self._load_snapshot(
            snapshot,
            title,
            local_playlist_id=None,
            youtube_playlist_id=playlist_id,
        )
        await self._finish_deferred_load(
            f"Loaded {title}: {len(snapshot.video_ids)} track(s).", play_after
        )

    async def _apply_album_snapshot(
        self, snapshot: PlaylistSnapshot, title: str, play_after: bool, load_id: int
    ) -> None:
        if load_id != self._queue_load_id:
            return  # a newer load or user-built queue landed after this was scheduled
        name = snapshot.title or title
        await self._load_snapshot(snapshot, name, local_playlist_id=None)
        await self._finish_deferred_load(
            f"Loaded album {name}: {len(snapshot.video_ids)} track(s).", play_after
        )

    async def _finish_deferred_load(self, message: str, play_after: bool) -> None:
        self._set_status(message)
        if play_after and self.playback.queue and not self.playback.status().running:
            await self._start_loaded_queue()

    async def _start_loaded_queue(self) -> None:
        try:
            status = self.playback.play_queue()
            self.playback_was_active = True
        except PlaybackError as exc:
            await self._report_playback_error(exc)
            return
        await self._show_playback_status(
            status, "Playing." if status.running else "Nothing to play."
        )

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
