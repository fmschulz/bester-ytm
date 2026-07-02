# mypy: disable-error-code="attr-defined"
# Mixin typed against the composed BesterYTMApp; attribute lookups across
# sibling mixins resolve at runtime (same policy as the tui_* overrides in
# pyproject.toml).
"""Playlist listing and deferred playlist/album queue loads for the TUI."""

from __future__ import annotations

from functools import partial

from textual.widgets import Input, Label, ListItem, ListView

from .config import ConfigError
from .playback import PlaybackError
from .search_query import SearchItem
from .stores import LocalPlaylistStore
from .ytm_client import PlaylistSnapshot, YTMClient, YTMClientError


class PlaylistLoadActions:
    """Mixin for BesterYTMApp: threaded playlist listing and deferred loads."""

    playlist_video_ids: list[str]
    _results_load_id: int
    _queue_load_id: int
    _play_queue_after_load: bool

    async def action_show_playlists(self) -> None:
        self.query_one("#search", Input).value = ""
        results = self.query_one("#results", ListView)
        await results.clear()
        self._set_status("Loading playlists...")
        # A newer search or playlist listing supersedes any in-flight one.
        self._results_load_id += 1
        self._note_results_focus()
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
            await super().action_pause_resume()  # type: ignore[misc]  # PlaybackActions, via the app MRO
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
