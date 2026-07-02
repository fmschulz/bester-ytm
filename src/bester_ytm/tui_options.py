# mypy: disable-error-code="attr-defined"
# Mixin typed against the composed BesterYTMApp; attribute lookups across
# sibling mixins resolve at runtime (same policy as the tui_* overrides in
# pyproject.toml).
"""Visualizer, theme, and pane-width option handling for the TUI."""

from __future__ import annotations

from textual.widgets import Select

from .config import ConfigError
from .config_options import save_ui_options
from .tui_splitter import PaneSplitter
from .tui_theme import EMBER_THEME
from .tui_visuals import EFFECT_ORDER


class UiOptionsActions:
    """Mixin for BesterYTMApp: persisted visualizer, theme, and pane options."""

    visualizer_effect: str

    def action_cycle_visualizer(self) -> None:
        names = list(EFFECT_ORDER)
        position = names.index(self.visualizer_effect) if self.visualizer_effect in names else 0
        self._apply_visualizer_effect(names[(position + 1) % len(names)])
        select = self._query_optional("#effect-select", Select)
        if select is not None:
            select.value = self.visualizer_effect

    def _apply_visualizer_effect(self, effect: str) -> None:
        self.visualizer_effect = effect
        self._refresh_playback()
        self._save_ui_options()
        self._set_status(f"Visualizer: {effect}.")

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "effect-select" or not isinstance(event.value, str):
            return
        if event.value != self.visualizer_effect:
            self._apply_visualizer_effect(event.value)

    def on_pane_splitter_resized(self, event: PaneSplitter.Resized) -> None:
        self._save_ui_options(
            left_width=self.query_one("#left").size.width,
            right_width=self.query_one("#right").size.width,
        )

    def _save_ui_options(
        self, left_width: int | None = None, right_width: int | None = None
    ) -> None:
        try:
            save_ui_options(
                self.visualizer_effect, left_width, right_width, theme=str(self.theme)
            )
        except ConfigError as exc:
            self._set_status(f"Settings not saved: {exc}")

    def _apply_saved_pane_widths(self) -> None:
        for selector, width in (
            ("#left", self.app_options.left_width),
            ("#right", self.app_options.right_width),
        ):
            if width is not None:
                self.query_one(selector).styles.width = width

    def _apply_branded_theme(self) -> None:
        """Register the ember theme, restore the saved choice, then persist future changes."""
        self.register_theme(EMBER_THEME)
        if self.app_options.theme in self.available_themes:
            self.theme = self.app_options.theme
        self.theme_changed_signal.subscribe(self, self._on_theme_changed)

    def _on_theme_changed(self, _theme: object) -> None:
        self._save_ui_options()
