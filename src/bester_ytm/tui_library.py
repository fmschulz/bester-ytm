"""Search, metadata, and local playlist actions for the TUI."""

from __future__ import annotations

from textual import events
from textual.widgets import Input, Label, ListItem, ListView

from .config import ConfigError
from .playback import PlaybackError
from .playlist_plan import SongCandidate
from .search_query import SearchItem, parse_search_query
from .stores import MAX_RATING, FavoritesStore, LocalPlaylistStore, TrackMetadataStore
from .ytm_client import PlaylistSnapshot, YTMClient, YTMClientError


class ResultListItem(ListItem):
    """Search result row with shift-click range selection before ListView activation."""

    def _on_click(self, event: events.Click) -> None:  # type: ignore[override]
        if event.shift and self.app._range_select_clicked_result(self):
            event.stop()
            event.prevent_default()
            return
        super()._on_click(event)


class LibraryActions:
    """Mixin with search, rating, tagging, and local playlist actions."""

    selected_queue_video_id: str | None
    candidates_by_video_id: dict[str, SongCandidate]
    current_candidate: SongCandidate | None
    build_in_progress: bool
    active_youtube_playlist_id: str | None
    _pending_playlist_delete: str | None

    async def _search(self, query: str) -> None:
        results = self.query_one("#results", ListView)
        await results.clear()
        self.selected_queue_video_id = None
        self._clear_result_selection()
        if not query.strip():
            self._show_results_list()
            return
        self._set_status(f"Searching {query!r}...")
        parsed = parse_search_query(query)
        try:
            if parsed.lists_local_playlists:
                items = LocalPlaylistStore().search_items()
            else:
                items = self.client.structured_search(parsed, limit=25)
        except YTMClientError as exc:
            self._set_status(str(exc))
            return
        if parsed.kind == "album":
            await self._populate_album_tree(items)
            self._set_status(
                f"{len(items)} album(s). Enter expands; space/x mark; "
                "shift+space ranges."
            )
            return
        self._show_results_list()
        for search_item in items:
            await results.append(self._result_item(search_item))
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

    def _result_item(self, search_item: SearchItem) -> ListItem:
        label_widget = Label(search_item.display_name)
        item = ResultListItem(label_widget)
        item.search_item = search_item  # type: ignore[attr-defined]
        item.base_label = search_item.display_name  # type: ignore[attr-defined]
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
        try:
            if item.item_type == "album":
                if not item.browse_id:
                    self._set_status("Album result has no browse id.")
                    return True
                snapshot = self.client.get_album(item.browse_id)
                await self._load_snapshot(snapshot, item.title, local_playlist_id=None)
                self._set_status(f"Loaded album {item.title}: {len(snapshot.video_ids)} track(s).")
                return True
            if item.item_type == "playlist":
                if not item.playlist_id:
                    self._set_status("Playlist result has no playlist id.")
                    return True
                snapshot = self.client.get_playlist(item.playlist_id)
                await self._load_snapshot(
                    snapshot,
                    item.title,
                    local_playlist_id=None,
                    youtube_playlist_id=item.playlist_id,
                )
                self._set_status(
                    f"Loaded playlist {item.title}: {len(snapshot.video_ids)} track(s)."
                )
                return True
            if item.item_type == "local_playlist":
                if not item.playlist_id:
                    self._set_status("Local playlist result has no id.")
                    return True
                playlist = LocalPlaylistStore().load(item.playlist_id)
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
        except (ConfigError, YTMClientError, FileNotFoundError) as exc:
            self._set_status(str(exc))
            return True
        return False

    async def _load_snapshot(
        self,
        snapshot,
        title: str,
        *,
        local_playlist_id: str | None,
        youtube_playlist_id: str | None = None,
    ) -> None:
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
        self._update_track_metadata(self.selected_queue_video_id)
        await self._render_queue()

    def _focus_first_result(self, results: ListView, has_items: bool) -> None:
        if not has_items:
            return
        try:
            results.index = 0
        except AttributeError:
            pass
        focus = getattr(results, "focus", None)
        if callable(focus):
            focus()

    def action_rate_up(self) -> None:
        self._change_rating(1)

    def action_rate_down(self) -> None:
        self._change_rating(-1)

    def action_cycle_rating(self) -> None:
        video_id = self._current_video_id()
        if not video_id:
            self._set_status("No track selected for rating.")
            return
        store = TrackMetadataStore()
        next_rating = (store.get(video_id).rating + 1) % (MAX_RATING + 1)
        metadata = store.set_rating(video_id, next_rating)
        self._update_track_metadata(video_id, sync_tags_input=False)
        self._set_status(f"Rating {metadata.rating}/{MAX_RATING}.")

    def _change_rating(self, delta: int) -> None:
        video_id = self._current_video_id()
        if not video_id:
            self._set_status("No track selected for rating.")
            return
        store = TrackMetadataStore()
        current = store.get(video_id)
        metadata = store.set_rating(video_id, current.rating + delta)
        self._update_track_metadata(video_id, sync_tags_input=False)
        self._set_status(f"Rating {metadata.rating}/{MAX_RATING}.")

    def action_save_tags(self) -> None:
        video_id = self._current_video_id()
        if not video_id:
            self._set_status("No track selected for tags.")
            return
        tags_input = self._query_optional("#tags-input", Input)
        raw = tags_input.value if tags_input else ""
        tags = [part.strip() for part in raw.split(",")]
        metadata = TrackMetadataStore().set_tags(video_id, tags)
        self._update_track_metadata(video_id)
        self._set_status("Tags saved: " + (", ".join(metadata.tags) or "none"))

    def action_add_to_local_playlist(self) -> None:
        candidate = self._current_candidate()
        if candidate is None:
            self._set_status("No track selected to add.")
            return
        name_input = self._query_optional("#playlist-name", Input)
        name = name_input.value.strip() if name_input and name_input.value.strip() else ""
        if not name and self.active_local_playlist_id:
            try:
                name = LocalPlaylistStore().load(self.active_local_playlist_id).name
            except FileNotFoundError:
                name = ""
        playlist = LocalPlaylistStore().add_track(name or "TUI Playlist", candidate)
        self.active_local_playlist_id = playlist.id
        if name_input:
            name_input.value = playlist.name
        self._set_status(f"Added to {playlist.name}.")

    async def action_remove_from_playlist(self) -> None:
        video_id = self._current_video_id()
        if not video_id:
            self._set_status("No current track to remove.")
            return
        if self.active_local_playlist_id:
            await self._remove_from_local_playlist(self.active_local_playlist_id, video_id)
            return
        if self.active_youtube_playlist_id:
            await self._remove_from_youtube_playlist(self.active_youtube_playlist_id, video_id)
            return
        name_input = self._query_optional("#playlist-name", Input)
        typed = name_input.value.strip() if name_input and name_input.value else ""
        if typed:
            from .playlist_plan import slugify

            await self._remove_from_local_playlist(slugify(typed), video_id)
            return
        self._set_status("Load a playlist first (Ctrl+P); Remove drops the highlighted track.")

    async def _remove_from_local_playlist(self, playlist_id: str, video_id: str) -> None:
        try:
            playlist = LocalPlaylistStore().remove_track(playlist_id, video_id)
        except FileNotFoundError as exc:
            self._set_status(str(exc))
            return
        if self.active_local_playlist_id == playlist.id:
            snapshot = PlaylistSnapshot(
                playlist_id=playlist.id,
                title=playlist.name,
                track_count=len(playlist.tracks),
                video_ids=playlist.video_ids,
                tracks=playlist.tracks,
            )
            await self._load_snapshot(snapshot, playlist.name, local_playlist_id=playlist.id)
        self._set_status(f"Removed from {playlist.name}.")

    async def _remove_from_youtube_playlist(self, playlist_id: str, video_id: str) -> None:
        title = self.playlist_title or playlist_id
        self._set_status(f"Removing track from YouTube playlist {title!r}...")
        try:
            removed = YTMClient(authenticated=True).remove_playlist_item(playlist_id, video_id)
        except (ConfigError, YTMClientError) as exc:
            self._set_status(str(exc))
            return
        if not removed:
            self._set_status(f"Track is not in YouTube playlist {title!r}.")
            return
        self.playlist_video_ids = [v for v in self.playlist_video_ids if v != video_id]
        self.playback.queue = [v for v in self.playback.queue if v != video_id]
        await self._render_queue()
        self._set_status(f"Removed track from YouTube playlist {title!r}.")

    async def _delete_highlighted_playlist(self) -> None:
        results = self._query_optional("#results", ListView)
        item = getattr(results, "highlighted_child", None) if results else None
        if item is None:
            self._set_status("Highlight a playlist first (Ctrl+P lists them); d deletes it.")
            return
        search_item = getattr(item, "search_item", None)
        if search_item is not None and search_item.item_type == "local_playlist":
            await self._delete_local_playlist(item, search_item.playlist_id or "")
            return
        playlist_id = getattr(item, "playlist_id", None)
        if playlist_id:
            await self._delete_youtube_playlist(item, str(playlist_id))
            return
        self._set_status(
            "d deletes the highlighted playlist: local ones immediately, "
            "YouTube ones after a confirming second press."
        )

    async def _delete_local_playlist(self, item: object, playlist_id: str) -> None:
        try:
            playlist = LocalPlaylistStore().delete(playlist_id)
        except FileNotFoundError as exc:
            self._set_status(str(exc))
            return
        if self.active_local_playlist_id == playlist.id:
            self.active_local_playlist_id = None
        await item.remove()  # type: ignore[attr-defined]
        self._set_status(f"Deleted local playlist {playlist.name!r}.")

    async def _delete_youtube_playlist(self, item: object, playlist_id: str) -> None:
        title = getattr(item, "playlist_title", None) or playlist_id
        if self._pending_playlist_delete != playlist_id:
            self._pending_playlist_delete = playlist_id
            self._set_status(
                f"Press d again to permanently delete {title!r} from your YouTube account."
            )
            return
        self._pending_playlist_delete = None
        try:
            YTMClient(authenticated=True).delete_playlist(playlist_id)
        except (ConfigError, YTMClientError) as exc:
            self._set_status(str(exc))
            return
        await item.remove()  # type: ignore[attr-defined]
        self._set_status(f"Deleted YouTube playlist {title!r}.")

    async def action_favorite_current(self) -> None:
        if self.current_candidate is None:
            self._set_status("No current track to favorite.")
            return
        FavoritesStore().append(self.current_candidate)
        self._set_status("Favorite saved.")

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
