"""Favorites and playlist maintenance actions for the TUI."""

from __future__ import annotations

from textual.widgets import Input, ListView

from .config import ConfigError
from .stores import FavoritesStore, LocalPlaylistStore
from .ytm_client import PlaylistSnapshot, YTMClient, YTMClientError


class TrackMetadataActions:
    """Mixin with favorite toggle and playlist add/remove/delete actions."""

    active_local_playlist_id: str | None
    active_youtube_playlist_id: str | None
    playlist_title: str
    playlist_video_ids: list[str]
    _pending_playlist_delete: str | None

    def action_toggle_favorite(self) -> None:
        """Fav/unfav the highlighted song, falling back to the playing track."""
        candidate = self._favorite_target()
        if candidate is None:
            self._set_status("No track to favorite.")
            return
        try:
            faved = FavoritesStore().toggle(candidate)
        except ConfigError as exc:
            self._set_status(str(exc))
            return
        self._refresh_favorite_markers(candidate.video_id, faved)
        if faved:
            self._set_status(f"Favorited {candidate.display_name}.")
        else:
            self._set_status(f"Removed {candidate.display_name} from favorites.")

    def _favorite_target(self):
        """The song f acts on: the highlighted row of the FOCUSED pane, else the
        playing track — never the queue's remembered row while browsing results."""
        context = self._focus_context()
        if context == "results":
            candidate = self._highlighted_result_candidate()
            if candidate is not None:
                return candidate
        if context == "queue":
            queue = self._query_optional("#queue", ListView)
            item = getattr(queue, "highlighted_child", None) if queue else None
            video_id = getattr(item, "video_id", None) if item else None
            if video_id and video_id in self.candidates_by_video_id:
                return self.candidates_by_video_id[video_id]
        return self.current_candidate

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
            await self._delete_local_playlist(
                item, search_item.playlist_id or "", search_item.title
            )
            return
        playlist_id = getattr(item, "playlist_id", None)
        if playlist_id:
            await self._delete_youtube_playlist(item, str(playlist_id))
            return
        self._set_status(
            "d deletes the highlighted playlist (local or YouTube) "
            "after a confirming second press."
        )

    async def _delete_local_playlist(
        self, item: object, playlist_id: str, title: str
    ) -> None:
        name = title or playlist_id
        if self._pending_playlist_delete != playlist_id:
            self._pending_playlist_delete = playlist_id
            self._set_status(
                f"Press d again to permanently delete local playlist {name!r}."
            )
            return
        self._pending_playlist_delete = None
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
