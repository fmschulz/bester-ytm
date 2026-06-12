"""Multi-select of search-result songs for batch queueing."""

from __future__ import annotations

from textual.widgets import ListView

from .playback import PlaybackError
from .playlist_plan import SongCandidate

SELECTED_PREFIX = "* "


class SelectionActions:
    """Mixin that lets the user mark several search results and queue them in order."""

    selected_result_video_ids: set[str]
    playlist_video_ids: list[str]
    playlist_title: str

    def action_toggle_select(self) -> None:
        if self._album_tree_active():
            self._toggle_album_tree_selection()
            return
        results = self._query_optional("#results", ListView)
        item = getattr(results, "highlighted_child", None) if results else None
        if not self._toggle_result_item(item):
            self._set_status(
                "Select marks songs in the search results (x or shift+click), "
                "then Enter queues them."
            )

    def _toggle_clicked_result(self, widget: object) -> bool:
        item = widget
        while item is not None and getattr(item, "candidate", None) is None:
            item = getattr(item, "parent", None)
        return self._toggle_result_item(item)

    def _toggle_result_item(self, item: object) -> bool:
        candidate = getattr(item, "candidate", None) if item is not None else None
        if candidate is None:
            return False
        video_id = candidate.video_id
        if video_id in self.selected_result_video_ids:
            self.selected_result_video_ids.discard(video_id)
        else:
            self.selected_result_video_ids.add(video_id)
        self._render_result_marker(item, video_id in self.selected_result_video_ids)
        count = len(self.selected_result_video_ids)
        self._set_status(f"{count} track(s) selected; Enter queues them in order.")
        return True

    def _render_result_marker(self, item: object, selected: bool) -> None:
        label = getattr(item, "label_widget", None)
        base = getattr(item, "base_label", None)
        if label is None or base is None:
            return
        label.update(f"{SELECTED_PREFIX}{base}" if selected else base)

    def _clear_result_selection(self) -> None:
        self.selected_result_video_ids.clear()

    async def _queue_selected_results(self) -> bool:
        """Queue every selected result in display order; True if selection was handled."""
        candidates = self._selected_candidates_in_display_order()
        if not candidates:
            return False
        for candidate in candidates:
            self.candidates_by_video_id[candidate.video_id] = candidate
        video_ids = [candidate.video_id for candidate in candidates]
        try:
            message = self._start_or_extend_queue(video_ids)
        except PlaybackError as exc:
            await self._report_playback_error(exc)
            return True
        self._clear_selection_markers()
        await self._render_queue()
        self._set_status(message)
        return True

    def _start_or_extend_queue(self, video_ids: list[str]) -> str:
        if self.playback.status().running:
            self.playback.enqueue(video_ids)
            self.playlist_video_ids.extend(video_ids)
            return f"Queued {len(video_ids)} track(s)."
        if self.playlist_video_ids or self.playback.queue:
            # A playlist is loaded but not playing: grow it instead of replacing it.
            self.playback.enqueue(video_ids)
            self.playlist_video_ids.extend(video_ids)
            return f"Added {len(video_ids)} track(s) to {self.playlist_title}."
        self.playback.replace_queue(video_ids)
        self.playlist_video_ids = list(video_ids)
        self.playlist_title = "Queue"
        status = self.playback.play_queue()
        self.playback_was_active = True
        self._sync_current_track(status.current_video_id)
        return f"Playing 1/{len(video_ids)} queued track(s); auto-advance plays the rest."

    def _selected_candidates_in_display_order(self) -> list[SongCandidate]:
        if not self.selected_result_video_ids:
            return []
        results = self._query_optional("#results", ListView)
        if results is None:
            return []
        ordered: list[SongCandidate] = []
        for item in list(results.children):
            candidate = getattr(item, "candidate", None)
            if candidate is not None and candidate.video_id in self.selected_result_video_ids:
                ordered.append(candidate)
        return ordered

    def _clear_selection_markers(self) -> None:
        results = self._query_optional("#results", ListView)
        if results is not None:
            for item in list(results.children):
                self._render_result_marker(item, False)
        self._clear_result_selection()
