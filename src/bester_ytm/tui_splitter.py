"""Draggable one-cell splitters that resize the side panes of the main layout."""

from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import Static

MIN_PANE_WIDTH = 16
MIN_CENTER_WIDTH = 20
SPLITTER_CELLS = 2  # both handles together


def clamped_pane_width(desired: int, total_width: int, other_pane_width: int) -> int:
    """Clamp a dragged side-pane width so neither it nor the center pane can collapse."""
    upper = total_width - other_pane_width - SPLITTER_CELLS - MIN_CENTER_WIDTH
    if upper < MIN_PANE_WIDTH:
        return MIN_PANE_WIDTH
    return max(MIN_PANE_WIDTH, min(desired, upper))


class PaneSplitter(Static):
    """Drag to resize the adjacent side pane; the center pane absorbs the change."""

    class Resized(Message):
        """Posted once per completed drag so the app can persist the layout."""

    def __init__(self, pane_id: str, other_pane_id: str, *, grows_leftward: bool) -> None:
        super().__init__("", id=f"splitter-{pane_id}")
        self._pane_id = pane_id
        self._other_pane_id = other_pane_id
        self._direction = -1 if grows_leftward else 1
        self._dragging = False
        self._start_x = 0
        self._start_width = 0

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragging = True
        self._start_x = event.screen_x
        self._start_width = self.app.query_one(f"#{self._pane_id}").size.width
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        delta = (event.screen_x - self._start_x) * self._direction
        total = self.app.query_one("#main").size.width
        other = self.app.query_one(f"#{self._other_pane_id}").size.width
        width = clamped_pane_width(self._start_width + delta, total, other)
        self.app.query_one(f"#{self._pane_id}").styles.width = width

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self.release_mouse()
        self.post_message(self.Resized())
