"""Search, result loading, and focus-preservation actions for the TUI."""

from __future__ import annotations

from functools import partial

from textual import events
from textual.widgets import Input, Label, ListItem, ListView, TextArea

from .config import ConfigError
from .local_files import local_search_items
from .playback import PlaybackError
from .playlist_plan import SongCandidate
from .radio import station_search_items
from .search_query import ParsedSearch, SearchItem, parse_search_query
from .stores import FAVORITE_SUFFIX, FavoritesStore, LocalPlaylistStore
from .ytm_client import PlaylistSnapshot, YTMClientError


class ResultListItem(ListItem):
    """Search result row with shift-click range selection before ListView activation."""

    def _on_click(self, event: events.Click) -> None:  # type: ignore[override]
        if event.shift and self.app._range_select_clicked_result(self):
            event.stop()
            event.prevent_default()
            return
        super()._on_click(event)


class LibraryActions:
    """Mixin with search, result loading, and current-track lookup helpers."""

    selected_queue_video_id: str | None
    candidates_by_video_id: dict[str, SongCandidate]
    current_candidate: SongCandidate | None
    build_in_progress: bool
    active_youtube_playlist_id: str | None
    _pending_playlist_delete: str | None
    _results_load_id: int
    _results_focus_snapshot: tuple[object | None, str | None]

    async def _search(self, query: str) -> None:
        results = self.query_one("#results", ListView)
        await results.clear()
        self.selected_queue_video_id = None
        self._clear_result_selection()
        # A newer search or playlist listing supersedes any in-flight one.
        self._results_load_id += 1
        self._note_results_focus()
        if not query.strip():
            self._show_results_list()
            return
        self._set_status(f"Searching {query!r}...")
        parsed = parse_search_query(query)
        if parsed.lists_local_playlists:
            await self._show_search_results(
                parsed, LocalPlaylistStore().search_items(), self._results_load_id
            )
            return
        if parsed.lists_favorites:
            try:
                items = FavoritesStore().search_items(parsed.text)
            except ConfigError as exc:
                self._set_status(str(exc))
                return
            await self._show_search_results(parsed, items, self._results_load_id)
            return
        if parsed.lists_radio_stations:
            await self._show_search_results(
                parsed, station_search_items(), self._results_load_id
            )
            return
        worker = (
            self._local_search_worker if parsed.lists_local_files else self._search_worker
        )
        self.run_worker(
            partial(worker, parsed, self._results_load_id),
            name="search",
            group="search",
            thread=True,
        )

    def _search_worker(self, parsed: ParsedSearch, load_id: int) -> None:
        """Runs on a worker thread so slow searches never freeze the UI."""
        try:
            items = self.client.structured_search(parsed, limit=25)
        except YTMClientError as exc:
            self.call_from_thread(self._finish_search_error, str(exc), load_id)
            return
        self.call_from_thread(self._finish_search, parsed, items, load_id)

    def _local_search_worker(self, parsed: ParsedSearch, load_id: int) -> None:
        """Scans directories on a worker thread; large trees must not freeze the UI."""
        try:
            items = local_search_items(parsed.text)
        except ConfigError as exc:
            self.call_from_thread(self._finish_search_error, str(exc), load_id)
            return
        self.call_from_thread(self._finish_search, parsed, items, load_id)

    def _finish_search_error(self, message: str, load_id: int) -> None:
        if load_id == self._results_load_id:
            self._set_status(message)

    def _finish_search(
        self, parsed: ParsedSearch, items: list[SearchItem], load_id: int
    ) -> None:
        if load_id != self._results_load_id:
            return  # superseded by a newer search or playlist listing
        self.run_worker(self._show_search_results(parsed, items, load_id), exclusive=False)

    async def _show_search_results(
        self, parsed: ParsedSearch, items: list[SearchItem], load_id: int
    ) -> None:
        if load_id != self._results_load_id:
            return  # a newer search or listing started after this was scheduled
        if parsed.kind == "album":
            await self._populate_album_tree(items)
            self._set_status(
                f"{len(items)} album(s). Enter expands; space/x mark; "
                "shift+space ranges."
            )
            return
        results = self.query_one("#results", ListView)
        self._show_results_list()
        favorite_ids = self._favorite_video_ids()
        for search_item in items:
            await results.append(self._result_item(search_item, favorite_ids))
        self._focus_first_result(results, bool(items))
        self._set_status(f"{len(items)} {parsed.view} result(s).")

    async def _refresh_local_playlist_library(self, highlight_id: str | None = None) -> None:
        """Repopulate the left pane with local playlists (offline; no YouTube fetch) so a
        freshly built or saved playlist appears at once; highlight the named one if given."""
        results = self._query_optional("#results", ListView)
        if results is None:
            return
        self._show_results_list()
        await results.clear()
        highlight_index: int | None = None
        for index, search_item in enumerate(LocalPlaylistStore().search_items()):
            await results.append(self._result_item(search_item))
            if highlight_id and search_item.playlist_id == highlight_id:
                highlight_index = index
        if highlight_index is not None:
            try:
                results.index = highlight_index
            except AttributeError:
                pass

    def _result_item(
        self, search_item: SearchItem, favorite_ids: set[str] | None = None
    ) -> ListItem:
        display = search_item.display_name
        candidate_id = search_item.candidate.video_id if search_item.candidate else None
        if favorite_ids and candidate_id in favorite_ids:
            display += FAVORITE_SUFFIX
        label_widget = Label(display)
        item = ResultListItem(label_widget)
        item.search_item = search_item  # type: ignore[attr-defined]
        item.base_label = display  # type: ignore[attr-defined]
        item.label_widget = label_widget  # type: ignore[attr-defined]
        if search_item.candidate:
            item.candidate = search_item.candidate  # type: ignore[attr-defined]
            self.candidates_by_video_id[search_item.candidate.video_id] = search_item.candidate
        if search_item.playlist_id:
            item.playlist_id = search_item.playlist_id  # type: ignore[attr-defined]
            item.playlist_title = search_item.title  # type: ignore[attr-defined]
        return item

    async def _load_search_item(self, item: SearchItem) -> bool:
        if item.item_type == "song":
            return False
        if item.item_type == "album":
            if not item.browse_id:
                self._set_status("Album result has no browse id.")
                return True
            # Deferred: the fetch runs on a worker thread and fills the queue later.
            self._load_album_queue(item.browse_id, item.title)
            return True
        if item.item_type == "playlist":
            if not item.playlist_id:
                self._set_status("Playlist result has no playlist id.")
                return True
            # Search playlists are public; keep the unauthenticated client.
            await self._load_playlist_queue(item.playlist_id, authenticated=False)
            return True
        if item.item_type == "local_playlist":
            return await self._load_local_playlist_item(item)
        return False

    async def _load_local_playlist_item(self, item: SearchItem) -> bool:
        if not item.playlist_id:
            self._set_status("Local playlist result has no id.")
            return True
        try:
            playlist = LocalPlaylistStore().load(item.playlist_id)
        except (ConfigError, FileNotFoundError) as exc:
            self._set_status(str(exc))
            return True
        snapshot = PlaylistSnapshot(
            playlist_id=playlist.id,
            title=playlist.name,
            track_count=len(playlist.tracks),
            video_ids=playlist.video_ids,
            tracks=playlist.tracks,
        )
        await self._load_snapshot(snapshot, playlist.name, local_playlist_id=playlist.id)
        self._set_status(
            f"Loaded local playlist {playlist.name}: {len(playlist.tracks)} track(s)."
        )
        return True

    async def _load_snapshot(
        self,
        snapshot,
        title: str,
        *,
        local_playlist_id: str | None,
        youtube_playlist_id: str | None = None,
    ) -> None:
        # This queue is now the user's newest choice; drop any older in-flight load.
        self._supersede_queue_load()
        for track in snapshot.tracks:
            self.candidates_by_video_id[track.video_id] = track
        self.playback.replace_queue(list(snapshot.video_ids))
        self.playlist_video_ids = list(snapshot.video_ids)
        self.playlist_title = title
        self.active_local_playlist_id = local_playlist_id
        self.active_youtube_playlist_id = youtube_playlist_id
        self.selected_queue_video_id = snapshot.video_ids[0] if snapshot.video_ids else None
        name_input = self._query_optional("#playlist-name", Input)
        if name_input:
            # Pre-fill the save name so w writes straight back to this playlist.
            name_input.value = title
        self.current_candidate = None
        self._update_track_label("No track playing.")
        await self._render_queue()

    def _favorite_video_ids(self) -> set[str]:
        """Faved ids for row markers; a corrupt store degrades to a status message."""
        try:
            return FavoritesStore().ids()
        except ConfigError as exc:
            self._set_status(str(exc))
            return set()

    def _refresh_favorite_markers(self, video_id: str, faved: bool) -> None:
        """Reflect a favorite toggle in the result rows, the queue, and Now Playing."""
        self._relabel_result_favorite(video_id, faved)
        self.run_worker(self._render_queue(), exclusive=True, group="queue-render")
        current = self.current_candidate
        if current is not None and current.video_id == video_id:
            self._update_track_label(
                current.display_name + (FAVORITE_SUFFIX if faved else "")
            )

    def _relabel_result_favorite(self, video_id: str, faved: bool) -> None:
        results = self._query_optional("#results", ListView)
        if results is None:
            return
        for item in getattr(results, "children", []):
            candidate = getattr(item, "candidate", None)
            base = getattr(item, "base_label", None)
            if candidate is None or base is None or candidate.video_id != video_id:
                continue
            if base.endswith(FAVORITE_SUFFIX):
                base = base[: -len(FAVORITE_SUFFIX)]
            if faved:
                base += FAVORITE_SUFFIX
            item.base_label = base
            self._render_result_marker(item, video_id in self.selected_result_video_ids)

    def _focus_first_result(self, results: ListView, has_items: bool) -> None:
        if not has_items:
            return
        try:
            results.index = 0
        except AttributeError:
            pass
        if self._input_focus_changed_since_load():
            return  # the user is typing in an input; do not yank focus away
        focus = getattr(results, "focus", None)
        if callable(focus):
            focus()

    def _note_results_focus(self) -> None:
        """Record focus at load start so a deferred completion can tell whether
        the user has since focused or typed into an input."""
        self._results_focus_snapshot = self._focus_snapshot()

    def _focus_snapshot(self) -> tuple[object | None, str | None]:
        try:
            focused = self.focused
        except Exception:
            return (None, None)
        value: str | None = None
        if isinstance(focused, Input):
            value = focused.value
        elif isinstance(focused, TextArea):
            value = focused.text
        return (focused, value)

    def _input_focus_changed_since_load(self) -> bool:
        focused, value = self._focus_snapshot()
        if not isinstance(focused, (Input, TextArea)):
            return False
        baseline_widget, baseline_value = self._results_focus_snapshot
        return focused is not baseline_widget or value != baseline_value

    def _highlighted_queue_video_id(self) -> str | None:
        try:
            focused = self.focused
        except Exception:
            focused = None
        queue = self._query_optional("#queue", ListView)
        if queue and getattr(focused, "id", None) == "queue":
            item = getattr(queue, "highlighted_child", None)
            video_id = getattr(item, "video_id", None) if item else None
            if video_id:
                return video_id
        return self.selected_queue_video_id

    def _highlighted_result_candidate(self):
        results = self._query_optional("#results", ListView)
        item = getattr(results, "highlighted_child", None) if results else None
        return getattr(item, "candidate", None) if item else None

    def _current_video_id(self) -> str | None:
        highlighted = self._highlighted_queue_video_id()
        if highlighted:
            return highlighted
        result_candidate = self._highlighted_result_candidate()
        if result_candidate:
            return result_candidate.video_id
        if self.current_candidate:
            return self.current_candidate.video_id
        try:
            return self.playback.status().current_video_id
        except PlaybackError:
            return None

    def _current_candidate(self):
        video_id = self._current_video_id()
        if video_id and video_id in self.candidates_by_video_id:
            return self.candidates_by_video_id[video_id]
        result_candidate = self._highlighted_result_candidate()
        if result_candidate:
            return result_candidate
        return self.current_candidate
