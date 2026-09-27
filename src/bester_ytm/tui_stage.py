"""The stage widget: draws the chosen scene into strips and keeps them on screen."""

from __future__ import annotations

from textual import events
from textual.strip import Strip
from textual.theme import Theme
from textual.widget import Widget

from .tui_canvas import Palette, PixelCanvas, theme_ramp
from .tui_visuals import STILL_FRAME, AudioFrame, draw_scene


class Stage(Widget):
    """An audio-reactive canvas that redraws itself when its size or the theme changes.

    The app calls ``show`` on every frame while music plays and once whenever the
    scene or the playback state changes; in between, the last frame stays up.
    Clicking the stage toggles the fullscreen view.
    """

    def __init__(self, scene: str, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.scene = scene
        self._frame = STILL_FRAME
        self._canvas: PixelCanvas | None = None
        self._palette: Palette | None = None
        self._strips: list[Strip] = []

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self._on_theme_changed)

    def show(self, scene: str, frame: AudioFrame) -> None:
        """Draw ``frame`` of ``scene`` and keep it until the next call."""
        self.scene = scene
        self._frame = frame
        self._paint()

    def render_line(self, y: int) -> Strip:
        if y < len(self._strips):
            return self._strips[y]
        return Strip.blank(self.size.width, self.rich_style)

    def on_resize(self, event: events.Resize) -> None:
        self._paint()

    async def on_click(self, event: events.Click) -> None:
        await self.app.run_action("toggle_stage")

    def _on_theme_changed(self, theme: Theme) -> None:
        # The new theme's styles land on the next refresh; build colours from them.
        self._palette = None
        self.call_after_refresh(self._paint)

    def _paint(self) -> None:
        width, rows = self.content_size
        if width <= 0 or rows <= 0:
            return
        canvas = self._canvas
        if canvas is None or (canvas.width, canvas.rows) != (width, rows):
            canvas = self._canvas = PixelCanvas(width, rows)
        if self._palette is None:
            ramp = theme_ramp(self.app.get_css_variables(), is_dark=self.app.current_theme.dark)
            self._palette = Palette(ramp, self.rich_style)
        draw_scene(self.scene, canvas, self._frame)
        self._strips = canvas.strips(self._palette)
        self.refresh()
