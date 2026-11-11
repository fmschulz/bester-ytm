"""Switch workspace focus, tools, help, and the full-screen stage."""

from __future__ import annotations

from textual.widget import Widget
from textual.widgets import Button, Input

from .tui_help import HelpScreen


class WorkspaceActions:
    """Mixin for workspace navigation and stage actions."""

    _stage_focus: Widget | None

    async def action_focus_search(self) -> None:
        self.action_leave_stage()
        self.query_one("#search", Input).focus()

    def action_help(self) -> None:
        if isinstance(self.screen, HelpScreen):
            self.screen.dismiss(None)
        else:
            self.push_screen(HelpScreen())

    def action_toggle_tools(self) -> None:
        self.action_leave_stage()
        if not self.screen.has_class("compact"):
            self.query_one("#playlist-name", Input).focus()
            return
        self.screen.toggle_class("tools-open")
        if self.screen.has_class("tools-open"):
            self.query_one("#playlist-name", Input).focus()
        else:
            self.query_one("#search", Input).focus()

    def action_toggle_stage(self) -> None:
        immersive = not self.screen.has_class("immersive")
        if immersive:
            self._stage_focus = self.focused
            self.set_focus(None)
        self.screen.set_class(immersive, "immersive")
        self.query_one("#stage-button", Button).label = "Back" if immersive else "Full screen"
        if not immersive and self._stage_focus is not None:
            self.set_focus(self._stage_focus)

    def action_leave_stage(self) -> None:
        if not self.is_running:
            return
        if self.screen.has_class("immersive"):
            self.action_toggle_stage()
        elif isinstance(self.focused, Input):
            self.set_focus(None)

    def action_cancel_or_leave(self) -> None:
        if self.build_in_progress:
            self.action_cancel_build()
        elif self._similar_digits is not None:
            self._cancel_similar_count()
            self._set_status("Add similar cancelled.")
        else:
            self.action_leave_stage()

    async def action_show_radio(self) -> None:
        self.action_leave_stage()
        self.query_one("#search", Input).value = "radio:"
        await self._search("radio:")
