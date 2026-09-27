"""Half-block pixel canvas for the stage: two square pixels per terminal cell.

Each cell draws its upper pixel as the foreground of ``▀`` and its lower pixel as
the background, which doubles the vertical resolution. Pixels hold light
intensities in 0..1 that index a colour ramp built from the active theme, and the
canvas emits Textual strips directly, so a frame never goes through markup.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import groupby

from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.strip import Strip

RAMP_STEPS = 40
UPPER_HALF = "▀"
LOWER_HALF = "▄"
FULL_BLOCK = "█"
WHITE = Color(255, 255, 255)
BLACK = Color(0, 0, 0)


def theme_ramp(
    variables: Mapping[str, str], *, is_dark: bool, steps: int = RAMP_STEPS
) -> list[Color]:
    """Blend resolved theme colours into a ramp that starts at the background.

    The theme's accents are ordered by brightness so light always grows along the
    ramp; on a light theme "more light" means darker ink, so the order flips.

    Args:
        variables: Resolved CSS variables, as from ``App.get_css_variables()``.
        is_dark: Whether the theme is dark.
        steps: Number of colours in the ramp; step 0 is the background.
    """
    background = Color.parse(variables["background"])
    accents = sorted(
        (Color.parse(variables[name]) for name in ("secondary", "primary", "accent")),
        key=lambda color: color.brightness,
        reverse=not is_dark,
    )
    foreground = Color.parse(variables["foreground"])
    crest = foreground.blend(WHITE if is_dark else BLACK, 0.6)
    stops = [background, background.blend(accents[0], 0.35), *accents, foreground, crest]
    return [_sample(stops, step / (steps - 1)) for step in range(steps)]


class Palette:
    """The glyph and style for every (upper, lower) pair of ramp steps."""

    def __init__(self, colors: Sequence[Color], base: Style) -> None:
        """Map ramp colours onto cells drawn over ``base``.

        Args:
            colors: The ramp; step 0 is treated as empty and shows the base background.
            base: The widget's own style. Every segment carries it, because Textual's
                ``NO_COLOR`` filter fails on unstyled segments and half-filled cells
                need its background.
        """
        self.size = len(colors)
        self._colors = [color.rich_color for color in colors]
        self._base = base
        self._cells: dict[int, tuple[str, Style]] = {}

    def strip(self, upper: Sequence[int], lower: Sequence[int]) -> Strip:
        """One terminal row from two rows of ramp steps, runs merged into segments."""
        size = self.size
        keys = (top * size + bottom for top, bottom in zip(upper, lower, strict=True))
        segments = [self._segment(key, sum(1 for _ in run)) for key, run in groupby(keys)]
        return Strip(segments, len(upper))

    def _segment(self, key: int, length: int) -> Segment:
        cell = self._cells.get(key)
        if cell is None:
            cell = self._cells[key] = self._cell(*divmod(key, self.size))
        glyph, style = cell
        return Segment(glyph * length, style)

    def _cell(self, upper: int, lower: int) -> tuple[str, Style]:
        colors, base = self._colors, self._base
        if upper == lower:
            return (" ", base) if upper == 0 else (FULL_BLOCK, base + Style(color=colors[upper]))
        if lower == 0:
            return UPPER_HALF, base + Style(color=colors[upper])
        if upper == 0:
            return LOWER_HALF, base + Style(color=colors[lower])
        return UPPER_HALF, base + Style(color=colors[upper], bgcolor=colors[lower])


class PixelCanvas:
    """A ``width`` by ``2 * rows`` grid of light intensities, stored row-major.

    Scenes write values of 0 or more; 0 is dark and anything above 1 clips.
    """

    def __init__(self, width: int, rows: int) -> None:
        self.width = width
        self.rows = rows
        self.height = rows * 2
        self.pixels = [0.0] * (width * self.height)

    def clear(self) -> None:
        """Turn every pixel dark."""
        self.pixels = [0.0] * len(self.pixels)

    def fade(self, factor: float) -> None:
        """Dim every pixel by ``factor``, leaving trails of earlier frames."""
        self.pixels = [value * factor for value in self.pixels]

    def plot(self, x: int, y: int, value: float) -> None:
        """Raise one pixel to at least ``value``; points off the canvas are ignored."""
        if 0 <= x < self.width and 0 <= y < self.height:
            index = y * self.width + x
            if value > self.pixels[index]:
                self.pixels[index] = value

    def strips(self, palette: Palette) -> list[Strip]:
        """Quantise to ramp steps and pair pixel rows into one strip per terminal row."""
        top = palette.size - 1
        steps = [min(top, int(value * top + 0.5)) for value in self.pixels]
        width = self.width
        return [
            palette.strip(steps[start : start + width], steps[start + width : start + 2 * width])
            for start in range(0, len(steps), 2 * width)
        ]


def _sample(stops: Sequence[Color], position: float) -> Color:
    """The colour at ``position`` (0..1) along evenly spaced gradient stops."""
    scaled = position * (len(stops) - 1)
    index = min(int(scaled), len(stops) - 2)
    return stops[index].blend(stops[index + 1], scaled - index)
