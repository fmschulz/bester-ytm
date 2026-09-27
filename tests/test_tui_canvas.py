"""Pixel canvas: half-block cells, theme ramps, and strips that always carry a style."""

from __future__ import annotations

from rich.style import Style
from textual.color import Color

from bester_ytm.tui_canvas import (
    FULL_BLOCK,
    LOWER_HALF,
    UPPER_HALF,
    Palette,
    PixelCanvas,
    theme_ramp,
)

ASTRA = {
    "background": "#080e1a",
    "foreground": "#dce5f2",
    "primary": "#55d9e8",
    "secondary": "#aa8de0",
    "accent": "#9be9e8",
}
LIGHT = {
    "background": "#e0e0e0",
    "foreground": "#1f1f1f",
    "primary": "#004578",
    "secondary": "#0178d4",
    "accent": "#fea62b",
}
BASE = Style(color="#dce5f2", bgcolor="#080e1a")


def _palette(steps: int = 5) -> Palette:
    return Palette(theme_ramp(ASTRA, is_dark=True, steps=steps), BASE)


def test_theme_ramp_starts_at_the_background_and_brightens() -> None:
    ramp = theme_ramp(ASTRA, is_dark=True)

    assert ramp[0] == Color.parse("#080e1a")
    assert ramp[-1].brightness > ramp[20].brightness > ramp[1].brightness


def test_light_theme_ramp_darkens_towards_the_ink() -> None:
    ramp = theme_ramp(LIGHT, is_dark=False)

    assert ramp[0] == Color.parse("#e0e0e0")
    assert ramp[-1].brightness < ramp[20].brightness < ramp[1].brightness


def test_strips_pair_pixel_rows_into_half_blocks() -> None:
    canvas = PixelCanvas(4, 1)
    canvas.plot(0, 0, 1.0)
    canvas.plot(1, 1, 1.0)
    canvas.plot(2, 0, 1.0)
    canvas.plot(2, 1, 1.0)

    [strip] = canvas.strips(_palette())

    assert strip.text == UPPER_HALF + LOWER_HALF + FULL_BLOCK + " "
    assert strip.cell_length == 4


def test_every_segment_has_a_style_with_a_background() -> None:
    """Textual's NO_COLOR filter fails on unstyled segments; half cells need a background."""
    canvas = PixelCanvas(3, 2)
    canvas.plot(1, 0, 0.5)

    segments = [segment for strip in canvas.strips(_palette()) for segment in strip]

    assert all(segment.style is not None and segment.style.bgcolor for segment in segments)


def test_equal_neighbouring_cells_merge_into_one_segment() -> None:
    canvas = PixelCanvas(6, 1)

    [strip] = canvas.strips(_palette())

    assert len(list(strip)) == 1


def test_light_above_one_clips_to_the_brightest_step() -> None:
    palette = _palette()
    canvas = PixelCanvas(1, 1)
    canvas.plot(0, 0, 5.0)
    canvas.plot(0, 1, 5.0)

    [segment] = list(canvas.strips(palette)[0])

    assert segment.text == FULL_BLOCK
    assert segment.style is not None
    assert segment.style.color == theme_ramp(ASTRA, is_dark=True, steps=5)[-1].rich_color


def test_plot_keeps_the_brighter_value_and_ignores_points_off_canvas() -> None:
    canvas = PixelCanvas(2, 1)

    canvas.plot(1, 1, 0.8)
    canvas.plot(1, 1, 0.3)
    canvas.plot(5, 0, 1.0)
    canvas.plot(0, -1, 1.0)

    assert canvas.pixels == [0.0, 0.0, 0.0, 0.8]


def test_fade_dims_every_pixel() -> None:
    canvas = PixelCanvas(2, 1)
    canvas.plot(0, 0, 1.0)

    canvas.fade(0.5)

    assert canvas.pixels == [0.5, 0.0, 0.0, 0.0]
