"""Queue editing: load built plans, remove/reorder tracks, save as local playlist."""

from __future__ import annotations

from textual.widgets import Input

from .playlist_plan import PlaylistPlan, SongCandidate, slugify
from .stores import LocalPlaylist, LocalPlaylistStore

EDIT_HINT = "Edit: d removes, j/k move, w saves as a local playlist."


class QueueEditActions:
    """Mixin for BesterYTMApp: the queue is an editable, saveable working playlist."""

    playlist_video_ids: list[str]
    playlist_title: str
    active_local_playlist_id: str | None
    active_youtube_playlist_id: str | None
    build_in_progress: bool

    def _finish_playlist_build(self, plan: PlaylistPlan, message: str) -> None:
        self.build_in_progress = False
        self.run_worker(self._load_plan_into_queue(plan, message), exclusive=False)

    async def _load_plan_into_queue(self, plan: PlaylistPlan, message: str) -> None:
        candidates = plan.resolved_candidates()
        if not candidates:
            self._set_status(f"{message} No resolved tracks to queue.")
            return
        for candidate in candidates:
            self.candidates_by_video_id[candidate.video_id] = candidate
        video_ids = [candidate.video_id for candidate in candidates]
        playlist = LocalPlaylist(id=slugify(plan.name), name=plan.name, tracks=candidates)
        LocalPlaylistStore().save(playlist)
        self.active_local_playlist_id = playlist.id
        self.active_youtube_playlist_id = None
        current = self.playback.current_video_id if self.playback.status().running else None
        if current:
            # The build becomes the new playlist; the playing track finishes first.
            self.playback.queue = list(video_ids)
            self.playlist_video_ids = [current, *video_ids]
            verb = f"{len(video_ids)} track(s) queued after the current song."
        else:
            self.playback.replace_queue(video_ids)
            self.playlist_video_ids = list(video_ids)
            self.playback_was_active = False
            verb = f"{len(video_ids)} track(s) loaded; press Space to play."
        self.playlist_title = plan.name
        name_input = self._query_optional("#playlist-name", Input)
        if name_input:
            name_input.value = plan.name
        await self._render_queue()
        self._set_status(
            f"{message} Created local playlist {plan.name!r}; {verb} {EDIT_HINT}"
        )

    async def action_clear_queue(self) -> None:
        if not self.playlist_video_ids and not self.playback.queue:
            self._set_status("The queue is already empty.")
            return
        current = self.playback.current_video_id
        is_playing = self.playback.status().running and current
        self.playback.queue = []
        self.playlist_video_ids = [current] if is_playing and current else []
        if not is_playing:
            self.playlist_title = "Queue"
        await self._render_queue()
        kept = " The playing track keeps playing." if is_playing else ""
        self._set_status(f"Queue cleared.{kept}")

    async def action_remove_from_queue(self) -> None:
        if self._focus_context() == "results":
            await self._delete_highlighted_playlist()
            return
        video_id = self._highlighted_queue_video_id()
        if not video_id:
            self._set_status("Highlight a queue track first; d removes it.")
            return
        if video_id == self.playback.current_video_id:
            self._set_status("Cannot remove the playing track; press n to skip it.")
            return
        removed_index = self.playlist_video_ids.index(video_id)
        self.playlist_video_ids = [v for v in self.playlist_video_ids if v != video_id]
        self.playback.queue = [v for v in self.playback.queue if v != video_id]
        focus = self._neighbor_after_removal(removed_index)
        await self._render_queue(focus_video_id=focus)
        self._set_status(f"Removed {video_id} from the queue.")

    def _neighbor_after_removal(self, removed_index: int) -> str | None:
        """The track now occupying the removed slot, else the previous one."""
        order = self.playlist_video_ids
        if not order:
            return None
        if removed_index < len(order):
            return order[removed_index]
        return order[-1]

    async def action_move_queue_track_up(self) -> None:
        await self._move_queue_track(-1)

    async def action_move_queue_track_down(self) -> None:
        await self._move_queue_track(1)

    async def _move_queue_track(self, delta: int) -> None:
        video_id = self._highlighted_queue_video_id()
        order = list(self.playlist_video_ids or self.playback.queue)
        if not video_id or video_id not in order:
            self._set_status("Highlight a queue track first; j/k move it.")
            return
        index = order.index(video_id)
        target = index + delta
        if not 0 <= target < len(order):
            return
        order[index], order[target] = order[target], order[index]
        self.playlist_video_ids = order
        upcoming = set(self.playback.queue)
        self.playback.queue = [v for v in order if v in upcoming]
        await self._render_queue(focus_video_id=video_id)
        self._set_status(f"Moved {video_id} {'up' if delta < 0 else 'down'}.")

    def action_save_queue_playlist(self) -> None:
        candidates = self._queue_candidates()
        if not candidates:
            self._set_status("The queue is empty; nothing to save.")
            return
        name = self._queue_playlist_name()
        # Replace semantics: the saved playlist mirrors the queue exactly,
        # so removals and reordering done with d/j/k persist.
        playlist = LocalPlaylist(id=slugify(name), name=name, tracks=candidates)
        LocalPlaylistStore().save(playlist)
        self.active_local_playlist_id = playlist.id
        self._set_status(
            f"Saved {len(candidates)} track(s) to local playlist {playlist.name!r}. "
            "Load it anytime with Ctrl+P."
        )

    def _queue_candidates(self) -> list[SongCandidate]:
        video_ids = self.playlist_video_ids or list(self.playback.queue)
        seen: set[str] = set()
        candidates = []
        for video_id in video_ids:
            if video_id in seen or video_id not in self.candidates_by_video_id:
                continue
            candidates.append(self.candidates_by_video_id[video_id])
            seen.add(video_id)
        return candidates

    def _queue_playlist_name(self) -> str:
        name_input = self._query_optional("#playlist-name", Input)
        typed = name_input.value.strip() if name_input and name_input.value else ""
        if typed:
            return typed
        if self.playlist_title and self.playlist_title != "Queue":
            return self.playlist_title
        return "Saved Queue"
