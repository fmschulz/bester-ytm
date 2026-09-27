"""Astra: the black hole scene fills any canvas and brightens with loud music."""

from __future__ import annotations

import pytest

from bester_ytm.tui_astra import astra_layout, draw_astra
from bester_ytm.tui_canvas import PixelCanvas
from bester_ytm.tui_visuals import AudioFrame


def _frame(level: float, onset: float = 0.0) -> AudioFrame:
    return AudioFrame(level=level, onset=onset, phase=24.0, history=(level,), samples=1)


@pytest.mark.parametrize("size", [(8, 3), (84, 13), (140, 34), (200, 60)])
def test_astra_lights_compact_and_fullscreen_canvases(size: tuple[int, int]) -> None:
    width, rows = size
    canvas = PixelCanvas(width, rows)

    draw_astra(canvas, _frame(0.85))

    assert len(canvas.pixels) == width * rows * 2
    assert max(canvas.pixels) > 0.3
    assert min(canvas.pixels) >= 0.0


def test_astra_brightens_on_loud_passages() -> None:
    quiet, loud = PixelCanvas(100, 25), PixelCanvas(100, 25)

    draw_astra(quiet, _frame(0.05))
    draw_astra(loud, _frame(1.0))

    assert sum(loud.pixels) > sum(quiet.pixels) * 1.3


def test_onsets_flare_the_photon_ring() -> None:
    steady, onset = PixelCanvas(100, 25), PixelCanvas(100, 25)

    draw_astra(steady, _frame(0.5))
    draw_astra(onset, _frame(0.5, onset=0.4))

    assert sum(onset.pixels) > sum(steady.pixels)


def test_the_shadow_is_dark_above_the_disk() -> None:
    """The far half of the disk hides behind the hole; only the near half crosses it."""
    width, rows = 100, 25
    canvas = PixelCanvas(width, rows)

    draw_astra(canvas, _frame(1.0))

    center_x, center_y = (width - 1) // 2, (rows * 2 - 1) // 2
    above_center = (center_y - 3) * width + center_x
    assert canvas.pixels[above_center] == 0.0


def test_layout_is_computed_once_per_canvas_size() -> None:
    assert astra_layout(60, 20) is astra_layout(60, 20)
