"""Large audio-reactive visual panels rendered in the bottom of each pane.

Each effect is a pure painter of a brightness *field* (``grid[y][x]`` in 0..1);
a single shared renderer turns that field into glyphs with a per-cell ember glow
and an optional bloom pass, so every effect lights up the same way. The app feeds
in a sliding history of live RMS loudness (newest last) plus a motion ``phase`` it
accumulates in proportion to loudness, so the visuals lock to the music: ``bars``
and ``wave`` plot the loudness history directly, while ``mythos``/``oracle``/
``pulse``/``scope`` move at a speed and brightness set by the audio.
"""

from __future__ import annotations

import math
import re
from collections import deque

FULL = "█"
# Glyph ramp from faint to incandescent; index = round(brightness * (len - 1)).
RAMP = " ·∙•●◉▓█"
STAR = "·"

# Warm ember gradient, dim depths to white-hot crest.
PALETTE = [
    "#5b2f22", "#7c3f2e", "#a85638", "#c96442",
    "#e07a5f", "#eda36c", "#f2cc8f", "#ffe6c0",
]
DEFAULT_LEVEL = 0.6
# mpv's astats filter measures audio as it is filtered, which runs ahead of the
# speakers by the output buffer (--audio-buffer 0.2s plus the device buffer).
# Readings are held back this long so the visuals move with what is heard.
MPV_AUDIO_LEAD_SECONDS = 0.25

EFFECT_ORDER = ("mythos", "oracle", "bars", "wave", "pulse", "scope")
EFFECT_LABELS = {
    "mythos": "Mythos",
    "oracle": "Oracle",
    "bars": "Bars",
    "wave": "Wave",
    "pulse": "Pulse",
    "scope": "Scope",
}
EFFECT_OPTIONS = [(EFFECT_LABELS[key], key) for key in EFFECT_ORDER]

_TAG = re.compile(r"\[[^\]]*\]")


def strip_markup(panel: str) -> str:
    """Drop Rich color tags, leaving the raw glyph grid (handy for tests)."""
    return _TAG.sub("", panel)


class AudioLevelMeter:
    """Turns raw RMS dB readings into a smoothed 0..1 level that tracks recent dynamics.

    Readings pass through a short delay line that cancels mpv's filter-to-speaker
    lead, then drive the level with an instant attack and a smooth release so a
    beat lights up the frame on which it becomes audible. Smoothing constants are
    expressed per second, so behaviour is the same at any sampling rate.
    """

    def __init__(self, sample_interval: float = 0.05) -> None:
        self.sample_interval = max(0.01, sample_interval)
        self.floor_db = -45.0
        self.ceiling_db = -15.0
        self.level = DEFAULT_LEVEL
        self._pending: deque[float] = deque()
        self._delay_samples = round(MPV_AUDIO_LEAD_SECONDS / self.sample_interval)

    def update(self, rms_db: float | None) -> float:
        if rms_db is None or rms_db < -90.0:
            return self.level
        self._pending.append(rms_db)
        if len(self._pending) <= self._delay_samples:
            return self.level
        return self._absorb(self._pending.popleft())

    def _absorb(self, rms_db: float) -> float:
        # Relax the floor/ceiling toward the current reading (~1s window), so the
        # meter follows the melody and beat instead of locking onto the song's
        # lifetime min/max and going flat on loudness-normalized tracks.
        adapt = 0.27 ** self.sample_interval
        self.floor_db = min(rms_db, self.floor_db * adapt + rms_db * (1 - adapt))
        self.ceiling_db = max(rms_db, self.ceiling_db * adapt + rms_db * (1 - adapt))
        span = max(8.0, self.ceiling_db - self.floor_db)
        instant = min(1.0, max(0.0, (rms_db - self.floor_db) / span))
        if instant >= self.level:
            self.level = instant
        else:
            release = 0.004 ** self.sample_interval
            self.level = self.level * release + instant * (1 - release)
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
        return _render_idle(width, height)
    history = levels or []
    level = min(1.0, max(0.0, history[-1] if history else DEFAULT_LEVEL))
    field = _RENDERERS.get(effect, _mythos_field)(phase, width, height, level, history)
    bloom = _BLOOM.get(effect)
    if bloom:
        field = _bloom(field, bloom)
    return _render_field(field, level)


# --- shared rendering -------------------------------------------------------


def _render_field(grid: list[list[float]], level: float) -> str:
    """Map a brightness field to glyphs tinted with a vertical ember glow."""
    height = len(grid)
    gain = 0.55 + 0.7 * level
    return "\n".join(
        _row_markup(row, (height - 1 - y) / max(1, height - 1), gain, level)
        for y, row in enumerate(grid)
    )


def _row_markup(values: list[float], depth: float, gain: float, level: float) -> str:
    """Run-length encode a row into ``[#hex]chars[/]`` spans, glow brightening with loudness."""
    top = len(PALETTE) - 1
    parts: list[str] = []
    run: list[str] = []
    run_color: str | None = None
    for value in values:
        bright = min(1.0, max(0.0, value * gain))
        glyph = RAMP[round(bright * (len(RAMP) - 1))]
        if glyph == " ":
            color = None
        else:
            shade = round(bright * top * 0.78 + depth * top * 0.18 + level * 1.1)
            color = PALETTE[min(top, shade)]
        if color != run_color:
            parts.append(_flush(run, run_color))
            run, run_color = [], color
        run.append(glyph)
    parts.append(_flush(run, run_color))
    return "".join(parts)


def _flush(chars: list[str], color: str | None) -> str:
    if not chars:
        return ""
    text = "".join(chars)
    return f"[{color}]{text}[/]" if color else text


def _bloom(grid: list[list[float]], strength: float) -> list[list[float]]:
    """One additive 3x3 spread so bright cells halo into their neighbours."""
    height, width = len(grid), len(grid[0])
    out = [row[:] for row in grid]
    for y in range(height):
        for x in range(width):
            seed = grid[y][x]
            if seed <= 0.0:
                continue
            spill = seed * strength
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx or dy:
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < height and 0 <= nx < width:
                            out[ny][nx] = min(1.0, out[ny][nx] + spill)
    return out


def _render_idle(width: int, height: int) -> str:
    rows = [" " * width for _ in range(height - 1)]
    rows.append("▁" * width)
    label = "awaiting signal"
    pad = max(0, (width - len(label)) // 2)
    rows[height // 2] = (" " * pad + label).ljust(width)[:width]
    return "\n".join(f"[{PALETTE[1]}]{row}[/]" for row in rows)


def _history_columns(levels: list[float], width: int) -> list[float]:
    """Recent levels as one value per column, newest on the right, padded with silence."""
    recent = levels[-width:]
    pad = [0.0] * (width - len(recent))
    return pad + [min(1.0, max(0.0, value)) for value in recent]


def _blank(width: int, height: int) -> list[list[float]]:
    return [[0.0] * width for _ in range(height)]


# --- effect fields ----------------------------------------------------------


def _bars_field(phase: float, width: int, height: int, level: float, levels: list[float]):
    """A scrolling loudness spectrum: each column is a past RMS reading, newest on the right."""
    grid = _blank(width, height)
    for x, value in enumerate(_history_columns(levels, width)):
        cells = value * height
        full = int(cells)
        for y in range(full):
            grid[height - 1 - y][x] = 1.0
        if full < height:
            grid[height - 1 - full][x] = cells - full
    return grid


def _wave_field(phase: float, width: int, height: int, level: float, levels: list[float]):
    """A symmetric oscilloscope of the loudness history; the band swells on loud passages."""
    grid = _blank(width, height)
    mid = (height - 1) / 2
    for x, value in enumerate(_history_columns(levels, width)):
        amp = value * mid
        top = max(0, round(mid - amp))
        bottom = min(height - 1, round(mid + amp))
        for y in range(top, bottom + 1):
            grid[y][x] = 1.0 if y in (top, bottom) else 0.45
    return grid


def _pulse_field(phase: float, width: int, height: int, level: float, levels: list[float]):
    """Concentric rings driven outward by the audio phase; thicker and brighter on loud beats."""
    grid = _blank(width, height)
    center_x = (width - 1) / 2
    center_y = (height - 1) / 2
    thickness = 0.4 + 1.6 * level
    for y in range(height):
        for x in range(width):
            distance = abs(x - center_x) * 0.5 + abs(y - center_y)
            ring = (distance - phase * 0.6) % 5.0
            if ring < thickness:
                grid[y][x] = 1.0 - 0.4 * ring / thickness
            elif ring < thickness + 1.0:
                grid[y][x] = 0.4 * (thickness + 1.0 - ring)
    return grid


def _scope_field(phase: float, width: int, height: int, level: float, levels: list[float]):
    """A Lissajous figure that rotates with the audio phase and swells with loudness."""
    grid = _blank(width, height)
    center_x = (width - 1) / 2
    center_y = (height - 1) / 2
    radius = 0.3 + 0.65 * level
    points = max(80, width * 3)
    for step in range(points):
        t = step / points * math.tau
        x = center_x + math.sin(3 * t + phase * 0.11) * center_x * radius
        y = center_y + math.sin(2 * t) * center_y * radius
        grid[round(y)][round(x)] = 1.0
    return grid


def _oracle_field(phase: float, width: int, height: int, level: float, levels: list[float]):
    """A mind's eye: rotating spokes crossed by thought-rings expanding from a white-hot core."""
    grid = _blank(width, height)
    center_x = (width - 1) / 2
    center_y = (height - 1) / 2
    eye = 1.2 + 1.8 * level
    for y in range(height):
        for x in range(width):
            dx = (x - center_x) * 0.5
            dy = y - center_y
            distance = math.hypot(dx, dy)
            angle = math.atan2(dy, dx)
            ring = 0.5 + 0.5 * math.cos(distance * 1.15 - phase * 0.45)
            spoke = 0.5 + 0.5 * math.cos(angle * 6 - phase * 0.12)
            bright = (ring * spoke - 0.45) * 1.6
            if distance < eye:
                bright = max(bright, 1.0 - distance / eye)
            grid[y][x] = min(1.0, max(0.0, bright))
    return grid


def _mythos_field(phase: float, width: int, height: int, level: float, levels: list[float]):
    """A constellation around a luminous mind: nodes orbit, link, and flare with the music."""
    grid = _blank(width, height)
    seed = int(phase) // 9  # reseed the backdrop ~once/sec; per-tick reseeding reads as flicker
    for y in range(height):
        for x in range(width):
            if (x * 73 + y * 151 + seed * 37) % 127 < 2:
                grid[y][x] = 0.35
    center_x = (width - 1) / 2
    center_y = (height - 1) / 2
    core = 1.4 + 2.6 * level
    for y in range(height):
        for x in range(width):
            distance = math.hypot((x - center_x) * 0.5, y - center_y)
            if distance < core:
                grid[y][x] = max(grid[y][x], 1.0 - distance / core)
    nodes = _mythos_nodes(phase, width, height)
    reach = (width + height) * (0.10 + 0.22 * level)
    for index, (x1, y1) in enumerate(nodes):
        for x2, y2 in nodes[index + 1:]:
            if abs(x1 - x2) + abs(y1 - y2) <= reach:
                _draw_filament(grid, x1, y1, x2, y2)
    for node_x, node_y in nodes:
        grid[round(node_y)][round(node_x)] = 1.0
    return grid


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


def _draw_filament(grid, x1: float, y1: float, x2: float, y2: float) -> None:
    steps = max(2, int(abs(x1 - x2) + abs(y1 - y2)))
    for step in range(1, steps):
        t = step / steps
        x = round(x1 + (x2 - x1) * t)
        y = round(y1 + (y2 - y1) * t)
        if grid[y][x] < 0.55:
            grid[y][x] = 0.55


_RENDERERS = {
    "mythos": _mythos_field,
    "oracle": _oracle_field,
    "bars": _bars_field,
    "wave": _wave_field,
    "pulse": _pulse_field,
    "scope": _scope_field,
}

# Effects whose fields are sparse curves/points glow with an additive halo;
# bars/wave stay crisp so a column height reads as an exact loudness.
_BLOOM = {"mythos": 0.5, "oracle": 0.55, "pulse": 0.4, "scope": 0.5}
