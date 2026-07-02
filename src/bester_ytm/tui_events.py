# mypy: disable-error-code="attr-defined"
# Mixin typed against the composed BesterYTMApp; attribute lookups across
# sibling mixins resolve at runtime (same policy as the tui_* overrides in
# pyproject.toml).
"""Input, click, focus, and action-dispatch event handling for the TUI."""

from __future__ import annotations

import inspect
from collections.abc import Mapping

from textual import events
from textual.actions import ActionParseResult
from textual.dom import DOMNode
from textual.widgets import Button, Input, ListView

from .tui_layout import BuilderTextArea


class EventHandlers:
    """Mixin for BesterYTMApp: widget events and action dispatch guards."""

    _pending_playlist_delete: str | None

    BUTTON_ACTIONS = {
        "prev-button": "previous_track",
        "rewind-button": "seek_backward",
        "play-button": "pause_resume",
        "forward-button": "seek_forward",
        "next-button": "next_track",
        "shuffle-button": "shuffle_queue",
        "transition-button": "cycle_transition",
        "clear-button": "clear_queue",
        "fade-down-button": "fade_shorter",
        "fade-up-button": "fade_longer",
        "volume-down-button": "volume_down",
        "volume-up-button": "volume_up",
        "mute-button": "mute",
        "rate-down-button": "rate_down",
        "rate-up-button": "rate_up",
        "save-tags-button": "save_tags",
        "new-playlist-button": "new_playlist",
        "add-local-playlist-button": "add_to_local_playlist",
        "remove-local-playlist-button": "remove_from_playlist",
        "save-queue-button": "save_queue_playlist",
        "build-button": "build_playlist",
    }

    CONTEXT_ACTIONS = {
        "toggle_select": {"results"},
        "range_select": {"results"},
        "add_to_queue": {"results"},
        "play_album": {"results"},
        "shuffle_queue": {"queue", "results"},
        "play_selected": {"results", "queue"},
        "remove_from_queue": {"queue", "results"},
        "move_queue_track_up": {"queue"},
        "move_queue_track_down": {"queue"},
        "clear_queue": {"queue"},
        "save_queue_playlist": {"queue"},
    }

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            await self._search(event.value)

    async def on_builder_text_area_submitted(self, event: BuilderTextArea.Submitted) -> None:
        await self.action_build_playlist()

    async def run_action(
        self,
        action: str | ActionParseResult,
        default_namespace: DOMNode | None = None,
        namespaces: Mapping[str, DOMNode] | None = None,
    ) -> bool:
        """Any action other than d (remove/delete) disarms a pending playlist delete."""
        if isinstance(action, str) and action != "remove_from_queue":
            self._pending_playlist_delete = None
        return await super().run_action(  # type: ignore[misc]  # textual App, via the app MRO
            action, default_namespace, namespaces
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Hide queue/results-specific footer keys unless that pane is focused."""
        contexts = self.CONTEXT_ACTIONS.get(action)
        if contexts is None:
            return True
        return True if self._focus_context() in contexts else None

    def _focus_context(self) -> str:
        try:
            node: DOMNode | None = self.focused
        except Exception:
            # No screen stack outside a running app; treat as no pane focus.
            return "other"
        while node is not None:
            if node.id == "album-tree":
                return "results"
            if node.id in ("results", "queue"):
                return node.id
            node = node.parent
        return "other"

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self.refresh_bindings()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.control.id == "results":
            event.stop()
            await self.action_play_selected()
        elif event.control.id == "queue":
            event.stop()
            await self._play_queue_item(event.item)

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.control.id != "queue":
            return
        self.selected_queue_video_id = getattr(event.item, "video_id", None)
        self._update_track_metadata(self.selected_queue_video_id)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        action_name = self.BUTTON_ACTIONS.get(event.button.id or "")
        if action_name is None:
            return
        self._pending_playlist_delete = None
        result = getattr(self, f"action_{action_name}")()
        if inspect.iscoroutine(result):
            await result

    async def on_click(self, event: events.Click) -> None:
        widget = event.widget
        while widget is not None and getattr(widget, "id", None) != "progress":
            widget = getattr(widget, "parent", None)
        if widget is None:
            return
        status = self.playback.status()
        if not status.duration_seconds:
            return
        width = max(1, widget.size.width)
        ratio = min(1.0, max(0.0, event.x / width))
        self._seek_absolute(status.duration_seconds * ratio)
