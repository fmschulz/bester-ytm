"""Large audio-reactive visual panel rendered under the queue.

Renderers are pure functions of (phase, width, height, level, levels) so frames
are deterministic and testable. The app feeds in a sliding history of live RMS
loudness (newest last) plus a motion ``phase`` it accumulates in proportion to
loudness. ``bars`` and ``wave`` plot the loudness history directly, so the shape
*is* the music scrolling left; ``pulse``/``scope``/``mythos`` move at a speed set
by the audio. Rows are tinted with a vertical ember gradient via Rich markup.
"""

from __future__ import annotations

import math

BLOCKS = " ▁▂▃▄▅▆▇█"
FULL = "█"
SHADE = "▒"
DOT = "●"
RING = "○"
STAR = "·"

# Warm ember gradient, dim depths to bright crest.
PALETTE = ["#7c3f2e", "#a85638", "#c96442", "#e07a5f", "#eda36c", "#f2cc8f"]
DEFAULT_LEVEL = 0.6


class AudioLevelMeter:
    """Turns raw RMS dB readings into a smoothed 0..1 level that tracks recent dynamics."""

    def __init__(self) -> None:
        self.floor_db = -45.0
        self.ceiling_db = -15.0
        self.level = DEFAULT_LEVEL

    def update(self, rms_db: float | None) -> float:
        if rms_db is None or rms_db < -90.0:
            return self.level
        # Relax the floor/ceiling toward the current reading at 0.85/sample (~1s window),
        # so the meter follows the melody and beat instead of locking onto the song's
        # lifetime min/max and going flat on loudness-normalized tracks.
        self.floor_db = min(rms_db, self.floor_db * 0.85 + rms_db * 0.15)
        self.ceiling_db = max(rms_db, self.ceiling_db * 0.85 + rms_db * 0.15)
        span = max(8.0, self.ceiling_db - self.floor_db)
        instant = (rms_db - self.floor_db) / span
        self.level = min(1.0, max(0.0, self.level * 0.4 + instant * 0.6))
        return self.level


def render_visual_panel(
    effect: str,
    phase: float,
    width: int,
    height: int,
    *,
    running: bool,
    levels: list[float] | None = None,
) -> str:
    if width < 8 or height < 3:
        return ""
    if not running:
        return _tint(_idle(width, height), 0.25)
    history = levels or []
    level = min(1.0, max(0.0, history[-1] if history else DEFAULT_LEVEL))
    renderer = _RENDERERS.get(effect, _mythos)
    rows = renderer(phase, width, height, level, history)
    return _tint(rows, level)


def _history_columns(levels: list[float], width: int) -> list[float]:
    """Recent levels as one value per column, newest on the right, padded with silence."""
    recent = levels[-width:]
    pad = [0.0] * (width - len(recent))
    return pad + [min(1.0, max(0.0, value)) for value in recent]


def _tint(rows: list[str], level: float) -> str:
    """Vertical ember gradient, glowing brighter as the music gets louder."""
    height = len(rows)
    boost = (len(PALETTE) - 1) * 0.35 * level
    tinted = []
    for index, row in enumerate(rows):
        depth = (height - 1 - index) / max(1, height - 1)
        shade = min(len(PALETTE) - 1, int(depth * (len(PALETTE) - 1) * 0.8 + boost))
        tinted.append(f"[{PALETTE[shade]}]{row}[/]")
    return "\n".join(tinted)


def _idle(width: int, height: int) -> list[str]:
    rows = [" " * width for _ in range(height - 1)]
    rows.append("▁" * width)
    label = "awaiting signal"
    middle = height // 2
    pad = max(0, (width - len(label)) // 2)
    rows[middle] = (" " * pad + label).ljust(width)[:width]
    return rows


def _bars(phase: float, width: int, height: int, level: float, levels: list[float]) -> list[str]:
    """A scrolling loudness spectrum: each column is a past RMS reading, newest on the right."""
    rows = [[" "] * width for _ in range(height)]
    for x, value in enumerate(_history_columns(levels, width)):
        cells = value * (height - 0.01)
        full_cells = int(cells)
        for y in range(full_cells):
            rows[height - 1 - y][x] = FULL
        if full_cells < height:
            rows[height - 1 - full_cells][x] = BLOCKS[int((cells - full_cells) * 8)]
    return ["".join(row) for row in rows]


def _wave(phase: float, width: int, height: int, level: float, levels: list[float]) -> list[str]:
    """A symmetric oscilloscope of the loudness history; the band swells on loud passages."""
    rows = [[" "] * width for _ in range(height)]
    mid = (height - 1) / 2
    for x, value in enumerate(_history_columns(levels, width)):
        amp = value * mid
        top = max(0, round(mid - amp))
        bottom = min(height - 1, round(mid + amp))
        for y in range(top + 1, bottom):
            rows[y][x] = SHADE
        rows[top][x] = DOT
        rows[bottom][x] = DOT
    return ["".join(row) for row in rows]


def _pulse(phase: float, width: int, height: int, level: float, levels: list[float]) -> list[str]:
    """Concentric rings driven outward by the audio phase; thicker and brighter on loud beats."""
    rows = [[" "] * width for _ in range(height)]
    center_x = (width - 1) / 2
    center_y = (height - 1) / 2
    thickness = 0.3 + 1.4 * level
    for y in range(height):
        for x in range(width):
            distance = abs(x - center_x) * 0.45 + abs(y - center_y)
            ring = (distance - phase * 0.6) % 5.0
            if ring < thickness:
                rows[y][x] = FULL
            elif ring < thickness + 0.8:
                rows[y][x] = SHADE
    return ["".join(row) for row in rows]


def _scope(phase: float, width: int, height: int, level: float, levels: list[float]) -> list[str]:
    """A Lissajous figure that rotates with the audio phase and swells with loudness."""
    rows = [[" "] * width for _ in range(height)]
    center_x = (width - 1) / 2
    center_y = (height - 1) / 2
    radius = 0.3 + 0.65 * level
    points = max(80, width * 3)
    for step in range(points):
        t = step / points * math.tau
        x = center_x + math.sin(3 * t + phase * 0.11) * center_x * radius
        y = center_y + math.sin(2 * t) * center_y * radius
        rows[round(y)][round(x)] = DOT
    return ["".join(row) for row in rows]


def _mythos(phase: float, width: int, height: int, level: float, levels: list[float]) -> list[str]:
    """A drifting constellation: nodes orbit at audio speed, link up, and flare with the music."""
    grid = [[" "] * width for _ in range(height)]
    # Reseed the backdrop only every ~9 phase units (~1s); per-tick reseeding reads as flicker.
    for y in range(height):
        for x in range(width):
            if (x * 73 + y * 151 + (int(phase) // 9) * 37) % 127 < 2:
                grid[y][x] = STAR
    nodes = _mythos_nodes(phase, width, height)
    reach = (width + height) * (0.10 + 0.22 * level)
    for index, (x1, y1) in enumerate(nodes):
        for x2, y2 in nodes[index + 1 :]:
            if abs(x1 - x2) + abs(y1 - y2) <= reach:
                _draw_link(grid, x1, y1, x2, y2)
    for node_x, node_y in nodes:
        grid[round(node_y)][round(node_x)] = DOT if level > 0.4 else RING
    return ["".join(row) for row in grid]


def _mythos_nodes(phase: float, width: int, height: int) -> list[tuple[float, float]]:
    # Phase advances ~0.2..2.4 per tick; the angle coefficients must stay small so a
    # loud tick reads as a surge of motion, not a teleport to an uncorrelated position.
    nodes = []
    for index in range(9):
        drift = 1.0 + index * 0.17
        x = (0.5 + 0.46 * math.sin(phase * 0.041 * drift + index * 2.4)) * (width - 1)
        y = (0.5 + 0.42 * math.sin(phase * 0.029 * drift + index * 1.7 + 1.3)) * (height - 1)
        nodes.append((x, y))
    return nodes


def _draw_link(grid: list[list[str]], x1: float, y1: float, x2: float, y2: float) -> None:
    steps = max(2, int(abs(x1 - x2) + abs(y1 - y2)))
    for step in range(1, steps):
        t = step / steps
        x = round(x1 + (x2 - x1) * t)
        y = round(y1 + (y2 - y1) * t)
        if grid[y][x] == " ":
            grid[y][x] = STAR


_RENDERERS = {
    "mythos": _mythos,
    "bars": _bars,
    "wave": _wave,
    "pulse": _pulse,
    "scope": _scope,
}
