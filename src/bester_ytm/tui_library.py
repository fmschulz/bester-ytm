"""Search the music library and load result snapshots into the queue."""

from __future__ import annotations

from functools import partial

from textual.content import Content
from textual.widgets import Input, ListView, Static

from .config import ConfigError
from .local_files import local_search_items
from .playlist_plan import SongCandidate
from .radio import RadioError, station_search_items
from .search_query import ParsedSearch, SearchItem, parse_search_query
from .stores import FavoritesStore, LocalPlaylistStore
from .tui_effects import NO_TRACK
from .tui_rows import ResultRow
from .ytm_client import PlaylistSnapshot, YTMClientError


class LibraryActions:
    """Mixin with library searches and queue snapshot loading."""

    selected_queue_index: int | None
    result_selection_anchor_video_id: str | None
    candidates_by_video_id: dict[str, SongCandidate]
    current_candidate: SongCandidate | None
    build_in_progress: bool
    active_youtube_playlist_id: str | None
    _pending_playlist_delete: str | None
    _results_load_id: int
    _favorites_query: str | None

    def _update_library_summary(self, title: str, empty_message: str = "") -> None:
        pane = self._query_optional("#left")
        if pane is not None:
            pane.border_title = Content(title)
        empty = self._query_optional("#library-empty", Static)
        if empty is not None:
            empty.update(empty_message)
            empty.display = bool(empty_message)

    async def _search(self, query: str) -> None:
        results = self.query_one("#results", ListView)
        await results.clear()
        self.selected_queue_index = None
        self._clear_result_selection()
        # A newer search or playlist listing supersedes any in-flight one.
        self._results_load_id += 1
        self._note_results_focus()
        if not query.strip():
            self._show_results_list()
            self._update_library_summary("Library", "Search for music or open Favorites.")
            return
        self._update_library_summary("Library / Searching")
        self._set_status(f"Searching {query!r}...")
        parsed = parse_search_query(query)
        self._favorites_query = parsed.text if parsed.lists_favorites else None
        if parsed.lists_local_playlists:
            await self._show_search_results(
                parsed, LocalPlaylistStore().search_items(), self._results_load_id
            )
            return
        if parsed.lists_favorites:
            try:
                items = FavoritesStore().search_items(parsed.text)
            except ConfigError as exc:
                self._show_search_failure(str(exc))
                return
            await self._show_search_results(parsed, items, self._results_load_id)
            return
        if parsed.lists_radio_stations:
            try:
                items = station_search_items()
            except RadioError as exc:
                self._show_search_failure(str(exc))
                return
            await self._show_search_results(parsed, items, self._results_load_id)
            return
        worker = self._local_search_worker if parsed.lists_local_files else self._search_worker
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
            self._show_search_failure(message)

    def _show_search_failure(self, message: str) -> None:
        """Say why the list is empty; the pane must not stay on "Searching"."""
        self._update_library_summary("Library", message)
        self._report_error(message)

    def _finish_search(self, parsed: ParsedSearch, items: list[SearchItem], load_id: int) -> None:
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
            self._update_library_summary(
                f"Library / Albums / {len(items)}",
                "No matching albums. Try another search." if not items else "",
            )
            self._set_status(
                f"{len(items)} album(s). Enter expands; space/x mark; shift+space ranges."
            )
            return
        results = self.query_one("#results", ListView)
        self._show_results_list()
        favorite_ids = self._favorite_video_ids()
        await results.extend([self._result_item(item, favorite_ids) for item in items])
        self._focus_first_result(results, bool(items))
        if parsed.lists_favorites:
            self._update_favorites_summary(len(items))
            self._set_status(f"{len(items)} local favorite(s). f removes; Enter plays; a queues.")
        else:
            self._update_library_summary(
                f"Library / {parsed.view.title()} / {len(items)}",
                "No matches. Try another search or open Favorites." if not items else "",
            )
            self._set_status(f"{len(items)} {parsed.view} result(s).")

    async def _refresh_local_playlist_library(self, highlight_id: str | None = None) -> None:
        """Repopulate the left pane with local playlists (offline; no YouTube fetch) so a
        freshly built or saved playlist appears at once; highlight the named one if given."""
        results = self._query_optional("#results", ListView)
        if results is None:
            return
        self._show_results_list()
        self._favorites_query = None
        await results.clear()
        highlight_index: int | None = None
        items = LocalPlaylistStore().search_items()
        rows: list[ResultRow] = []
        for index, search_item in enumerate(items):
            rows.append(self._result_item(search_item))
            if highlight_id and search_item.playlist_id == highlight_id:
                highlight_index = index
        await results.extend(rows)
        if highlight_index is not None:
            try:
                results.index = highlight_index
            except AttributeError:
                pass
        self._update_library_summary(
            f"Local playlists / {len(items)}",
            "Save the queue with w to create a local playlist." if not items else "",
        )

    def _result_item(
        self, search_item: SearchItem, favorite_ids: set[str] | None = None
    ) -> ResultRow:
        candidate = search_item.candidate
        if candidate:
            self.candidates_by_video_id[candidate.video_id] = candidate
        is_favorite = bool(candidate and favorite_ids and candidate.video_id in favorite_ids)
        return ResultRow(search_item, favorite=is_favorite)

    async def _load_search_item(self, item: SearchItem) -> bool:
        if item.item_type == "song":
            return False
        if item.item_type == "album":
            if not item.browse_id:
                self._report_error("Album result has no browse id.")
                return True
            # Deferred: the fetch runs on a worker thread and fills the queue later.
            self._load_album_queue(item.browse_id, item.title)
            return True
        if item.item_type == "playlist":
            if not item.playlist_id:
                self._report_error("Playlist result has no playlist id.")
                return True
            # Search playlists are public; keep the unauthenticated client.
            await self._load_playlist_queue(item.playlist_id, authenticated=False)
            return True
        if item.item_type == "local_playlist":
            return await self._load_local_playlist_item(item)
        return False

    async def _load_local_playlist_item(self, item: SearchItem) -> bool:
        if not item.playlist_id:
            self._report_error("Local playlist result has no id.")
            return True
        try:
            playlist = LocalPlaylistStore().load(item.playlist_id)
        except (ConfigError, FileNotFoundError) as exc:
            self._report_error(str(exc))
            return True
        snapshot = PlaylistSnapshot(
            playlist_id=playlist.id,
            title=playlist.name,
            track_count=len(playlist.tracks),
            video_ids=playlist.video_ids,
            tracks=playlist.tracks,
        )
        await self._load_snapshot(snapshot, playlist.name, local_playlist_id=playlist.id)
        self._set_status(f"Loaded local playlist {playlist.name}: {len(playlist.tracks)} track(s).")
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
        self.selected_queue_index = 0 if snapshot.video_ids else None
        name_input = self._query_optional("#playlist-name", Input)
        if name_input:
            # Pre-fill the save name so w writes straight back to this playlist.
            name_input.value = title
        self.current_candidate = None
        self._update_track_label(NO_TRACK)
        self._show_playing_favorite(False)
        await self._render_queue()
