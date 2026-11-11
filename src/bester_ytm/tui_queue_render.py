"""Draw queue rows and titles while preserving the selection cursor."""

from __future__ import annotations

from collections.abc import Sequence

from textual.widgets import ListView

from .tui_rows import QueueRow, queue_heading


class QueueRenderer:
    """Mixin that serializes queue rebuilds and restores the held cursor."""

    _queue_render_active: bool
    _queue_render_pending: bool
    _queue_render_focus: int | None

    def _update_queue_title(self, video_ids: Sequence[str]) -> None:
        """Name, size and running time in the queue's border; an empty queue says so."""
        candidates = [self.candidates_by_video_id.get(video_id) for video_id in video_ids]
        seconds = sum(candidate.duration_seconds or 0 for candidate in candidates if candidate)
        pane = self._query_optional("#center")
        if pane is not None:
            pane.border_title = queue_heading(
                self.playlist_title,
                len(video_ids),
                seconds,
                width=max(0, pane.outer_size.width - 4),
            )
            if self.build_in_progress:
                self._update_build_progress()
        empty = self._query_optional("#queue-empty")
        if empty is not None:
            empty.display = not video_ids

    async def _render_queue(self, focus_index: int | None = None) -> None:
        """Serialize rebuilds so a direct render and a tick render cannot interleave into dupes."""
        self._queue_render_focus = focus_index
        self._queue_render_pending = True
        if self._queue_render_active:
            return
        self._queue_render_active = True
        try:
            while self._queue_render_pending:
                self._queue_render_pending = False
                await self._draw_queue(self._queue_render_focus)
        finally:
            self._queue_render_active = False

    async def _draw_queue(self, focus_index: int | None) -> None:
        queue = self.query_one("#queue", ListView)
        held_cursor_index = queue.index if queue.children else self.selected_queue_index
        try:
            current = self.playback.status().current_video_id
        except AttributeError:
            current = getattr(self.playback, "current_video_id", None)
        # Set before the first await so a tick firing mid-rebuild sees no change and skips a render.
        self._rendered_now_playing_id = current
        playing_index = self._playing_queue_index(current)
        self._rendered_playing_index = playing_index
        await queue.clear()
        video_ids = list(self.playlist_video_ids or self.playback.queue)
        self._update_queue_title(video_ids)
        favorite_ids = self._favorite_video_ids()
        rows = [
            QueueRow(
                video_id,
                position,
                self.candidates_by_video_id.get(video_id),
                is_playing=position - 1 == playing_index,
                is_played=playing_index is not None and position - 1 < playing_index,
                is_favorite=video_id in favorite_ids,
            )
            for position, video_id in enumerate(video_ids, start=1)
        ]
        await queue.extend(rows)
        cursor_index = focus_index if focus_index is not None else held_cursor_index
        self._set_queue_cursor(queue, len(video_ids), cursor_index)

    def _set_queue_cursor(self, queue: ListView, count: int, target_index: int | None) -> None:
        """Keep the selection cursor on the user's row across a rebuild, not the now-playing row."""
        if not count:
            self.selected_queue_index = None
            return
        if target_index is None:
            return  # no cursor yet: do not draw one on a pane the user has not entered
        index = min(max(target_index, 0), count - 1)
        queue.index = index
        self.selected_queue_index = index
