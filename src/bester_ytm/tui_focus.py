"""Track workspace focus and resolve the highlighted or playing song."""

from __future__ import annotations

from textual.widgets import Input, ListView, TextArea

from .playback import PlaybackError
from .playlist_plan import SongCandidate


class FocusActions:
    """Mixin for focus preservation and current-song lookup."""

    _results_focus_snapshot: tuple[object | None, str | None]
    _favorites_query: str | None

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
        self._favorites_query = None

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

    def _highlighted_queue_index(self) -> int | None:
        try:
            focused = self.focused
        except Exception:
            focused = None
        queue = self._query_optional("#queue", ListView)
        if queue and getattr(focused, "id", None) == "queue":
            return queue.index
        return self.selected_queue_index

    def _highlighted_queue_video_id(self) -> str | None:
        index = self._highlighted_queue_index()
        order = self.playlist_video_ids or self.playback.queue
        return order[index] if index is not None and 0 <= index < len(order) else None

    def _highlighted_result_candidate(self) -> SongCandidate | None:
        if self._album_tree_active():
            tree = self._album_tree()
            return self._selection_candidate(getattr(tree, "cursor_node", None))
        results = self._query_optional("#results", ListView)
        item = getattr(results, "highlighted_child", None) if results else None
        return getattr(item, "candidate", None) if item else None

    def _current_video_id(self) -> str | None:
        if self._focus_context() == "results":
            candidate = self._highlighted_result_candidate()
            return candidate.video_id if candidate else None
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

    def _current_candidate(self) -> SongCandidate | None:
        if self._focus_context() == "results":
            return self._highlighted_result_candidate()
        video_id = self._current_video_id()
        if video_id and video_id in self.candidates_by_video_id:
            return self.candidates_by_video_id[video_id]
        result_candidate = self._highlighted_result_candidate()
        if result_candidate:
            return result_candidate
        return self.current_candidate
