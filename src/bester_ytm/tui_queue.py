"""Queue editing: load built plans, remove/reorder tracks, save as local playlist."""

from __future__ import annotations

import random

from textual.widgets import Input, ListView

from .playback import PlaybackError
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

    def _upcoming_queue_start(self, order: list[str]) -> int | None:
        """Return the upcoming suffix boundary when both lists are in step."""
        start = len(order) - len(self.playback.queue)
        if start >= 0 and order[start:] == self.playback.queue:
            return start
        return None

    def _playing_queue_index(self, current_video_id: str | None) -> int | None:
        """Find the current occurrence by the upcoming suffix, with an ID fallback."""
        if current_video_id is None:
            return None
        order = self.playlist_video_ids or self.playback.queue
        upcoming_start = self._upcoming_queue_start(order)
        if upcoming_start is not None and upcoming_start > 0:
            index = upcoming_start - 1
            if order[index] == current_video_id:
                return index
        return order.index(current_video_id) if current_video_id in order else None

    async def action_shuffle_queue(self) -> None:
        try:
            status = self.playback.status()
        except PlaybackError as exc:
            self._set_status(str(exc))
            return

        current = status.current_video_id if status.running else None
        visible = list(self.playlist_video_ids or self.playback.queue)
        if current:
            playing_index = self._playing_queue_index(current)
            prefix = visible[: playing_index + 1] if playing_index is not None else [current]
            visible = list(self.playback.queue)
            if not visible:
                self._set_status("Nothing else to shuffle.")
                return
            random.shuffle(visible)
            self.playlist_video_ids = [*prefix, *visible]
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

    def _finish_playlist_build(self, plan: PlaylistPlan, message: str) -> None:
        self.build_in_progress = False
        self.run_worker(self._load_plan_into_queue(plan, message), exclusive=False)

    async def _load_plan_into_queue(self, plan: PlaylistPlan, message: str) -> None:
        candidates = plan.resolved_candidates()
        if not candidates:
            self._set_status(f"{message} No resolved tracks to queue.")
            return
        self._supersede_queue_load()
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
        await self._refresh_local_playlist_library(playlist.id)
        self._set_status(f"{message} Created local playlist {plan.name!r}; {verb} {EDIT_HINT}")

    async def action_new_playlist(self) -> None:
        """Start a fresh playlist: clear the queue, detach the active one, name it next."""
        current = self.playback.current_video_id
        is_playing = bool(self.playback.status().running and current)
        kept = current if is_playing else None
        self._supersede_queue_load()
        self.playback.queue = []
        self.playlist_video_ids = [kept] if kept else []
        self.playlist_title = "New Playlist"
        self.active_local_playlist_id = None
        self.active_youtube_playlist_id = None
        # Retarget the track context to the kept playing track (or nothing), so a
        # later Add/Remove does not act on a row that just left the queue.
        self.selected_queue_index = 0 if kept else None
        self._sync_current_track(kept)
        name_input = self._query_optional("#playlist-name", Input)
        if name_input:
            name_input.value = ""
            focus = getattr(name_input, "focus", None)
            if callable(focus):
                focus()
        await self._render_queue()
        kept = " The playing track keeps playing." if is_playing else ""
        self._set_status(f"New playlist started.{kept} Add tracks with a, name it, then Save (w).")

    async def action_clear_queue(self) -> None:
        if not self.playlist_video_ids and not self.playback.queue:
            self._set_status("The queue is already empty.")
            return
        current = self.playback.current_video_id
        is_playing = self.playback.status().running and current
        self._supersede_queue_load()
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
        index = self._highlighted_queue_index()
        order = list(self.playlist_video_ids or self.playback.queue)
        if index is None:
            self._set_status("Highlight a queue track first; d removes it.")
            return
        if not 0 <= index < len(order):
            self._set_status("That track is no longer in the queue.")
            return
        status = self.playback.status()
        current = status.current_video_id if status.running else None
        playing_index = self._playing_queue_index(current)
        if index == playing_index:
            self._set_status("Cannot remove the playing track; press n to skip it.")
            return
        self._supersede_queue_load()
        upcoming_start = self._upcoming_queue_start(order)
        video_id = order.pop(index)
        if upcoming_start is not None:
            if index >= upcoming_start:
                self.playback.queue.pop(index - upcoming_start)
        elif video_id in self.playback.queue:
            self.playback.queue.remove(video_id)
        self.playlist_video_ids = order
        focus = min(index, len(order) - 1) if order else None
        await self._render_queue(focus_index=focus)
        name = self._track_display_name(video_id)
        self._set_status(
            f"Removed {name} from the queue." if name else "Removed track from the queue."
        )

    async def action_move_queue_track_up(self) -> None:
        await self._move_queue_track(-1)

    async def action_move_queue_track_down(self) -> None:
        await self._move_queue_track(1)

    async def _move_queue_track(self, delta: int) -> None:
        index = self._highlighted_queue_index()
        order = list(self.playlist_video_ids or self.playback.queue)
        if index is None or not 0 <= index < len(order):
            self._set_status("Highlight a queue track first; j/k move it.")
            return
        video_id = order[index]
        target = index + delta
        if not 0 <= target < len(order):
            return
        self._supersede_queue_load()
        status = self.playback.status()
        current = status.current_video_id if status.running else None
        upcoming_start = self._upcoming_queue_start(order)
        playing_index = self._playing_queue_index(current)
        other_video_id = order[target]
        order[index], order[target] = order[target], order[index]
        if upcoming_start is not None:
            if playing_index == index:
                upcoming_start = target + 1
            elif playing_index == target:
                upcoming_start = index + 1
            self.playback.queue = order[upcoming_start:]
        else:
            self._swap_upcoming_ids(video_id, other_video_id)
        self.playlist_video_ids = order
        await self._render_queue(focus_index=target)
        name = self._track_display_name(video_id)
        direction = "up" if delta < 0 else "down"
        self._set_status(f"Moved {name} {direction}." if name else f"Moved track {direction}.")

    def _swap_upcoming_ids(self, video_id: str, other_video_id: str) -> None:
        """Swap one copy of each ID when the displayed order is out of step."""
        upcoming = self.playback.queue
        if video_id in upcoming and other_video_id in upcoming:
            index = upcoming.index(video_id)
            target = upcoming.index(other_video_id)
            upcoming[index], upcoming[target] = upcoming[target], upcoming[index]

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
        self._schedule_library_refresh(playlist.id)
        self._set_status(
            f"Saved {len(candidates)} track(s) to local playlist {playlist.name!r}. "
            "Load it anytime with Ctrl+P."
        )

    def _schedule_library_refresh(self, highlight_id: str | None) -> None:
        """Refresh the left playlist library off the UI thread; no-op without a results pane."""
        if self._query_optional("#results", ListView) is None:
            return
        self.run_worker(self._refresh_local_playlist_library(highlight_id), exclusive=False)

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
