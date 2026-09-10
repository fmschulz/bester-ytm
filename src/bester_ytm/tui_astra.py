"""Astra's audio-reactive accretion disk, plasma ribbons, and starfield.

This is a procedural scene, not a frequency spectrum: mpv supplies RMS energy.
Coordinates account for terminal cells being about twice as tall as they are wide.
"""

from __future__ import annotations

import math

_RAMP = " ·∙░▒▓█"
_COLORS = (
    ("#263353", "#384e75", "#537e9c", "#7bbdc5", "#a7ece0", "#e1fff3"),
    ("#30294d", "#554178", "#875ca8", "#bd7bd1", "#efabe7", "#ffddf5"),
    ("#403049", "#765064", "#b27482", "#e4a398", "#ffd5b1", "#fff2d8"),
)


def render_astra(
    phase: float, width: int, height: int, level: float, levels: list[float]
) -> str:
    """Paint a deterministic scene; energy expands and brightens its rotating disk."""
    scale = max(1.0, min(width * 0.5, height) * 0.39)
    center_x, center_y = (width - 1) * 0.5, (height - 1) * 0.5
    recent = levels[-12:]
    baseline = sum(recent) / len(recent) if recent else level
    onset = max(0.0, level - baseline)
    rotation = phase * 0.10
    energy = 0.35 + 0.65 * level
    radius = 1.55 + 0.2 * level + onset * 0.3
    rows = []
    for y in range(height):
        dy = (y - center_y) / scale
        parts: list[str] = []
        run: list[str] = []
        run_color = ""
        for x in range(width):
            dx = (x - center_x) * 0.5 / scale
            distance = math.hypot(dx, dy)
            # A tilted disk: closely spaced spiral filaments shear around its core.
            disk_y = (dy + dx * 0.16) * 3.1
            disk_r = math.hypot(dx, disk_y)
            angle = math.atan2(disk_y, dx)
            spiral = 0.5 + 0.5 * math.sin(angle * 3.0 + disk_r * 7.0 - rotation * 3)
            envelope = math.exp(-abs(disk_r - radius) * 1.65)
            disk = envelope * (0.28 + 0.72 * spiral ** 2) * energy
            # A circular photon ring rises behind the disk and outlines the dark core.
            ring_r = 0.74 + 0.025 * math.sin(rotation)
            ring = math.exp(-abs(distance - ring_r) * 19) * (0.65 + level * 0.35)
            ring *= 0.7 + 0.3 * math.sin(math.atan2(dy, dx) + rotation)
            # Broad, drifting aurora ribbons carry movement all the way to the edges.
            ribbon_y = 0.65 * math.sin(dx * 1.35 + rotation * 0.45)
            ribbon_y += 0.25 * math.sin(dx * 3.1 - rotation * 0.7)
            ribbon = math.exp(-abs(dy - ribbon_y) * 6.0)
            ribbon *= min(0.24, abs(dx) * 0.065) * energy
            brightness = max(disk, ring, ribbon)
            family = 0 if dx + dy * 0.7 > 0 else 1
            if ring > disk or disk > 0.64:
                family = 2
            # Keep a clean silhouette, except where the near side crosses the core.
            if distance < 0.64 and disk_y < 0.12:
                brightness = 0.0
            # Stable positions and smooth twinkling avoid random per-frame flicker.
            star = (x * 73 + y * 151 + x * y * 19) % 491
            star_glyph = ""
            if star < 5 and distance > 0.9:
                twinkle = 0.20 + 0.15 * (0.5 + 0.5 * math.sin(rotation + star + x))
                if twinkle > brightness:
                    brightness, family = twinkle, 0
                    star_glyph = "+" if star == 0 else "·"
            brightness = min(1.0, brightness * (0.95 + level * 0.4))
            index = min(len(_RAMP) - 1, int(brightness * (len(_RAMP) - 1) + 0.5))
            glyph = star_glyph or _RAMP[index]
            color = _COLORS[family][max(0, index - 1)] if index else ""
            if color != run_color:
                _flush(parts, run, run_color)
                run, run_color = [], color
            run.append(glyph)
        _flush(parts, run, run_color)
        rows.append("".join(parts))
    return "\n".join(rows)


def _flush(parts: list[str], run: list[str], color: str) -> None:
    if run:
        text = "".join(run)
        parts.append(f"[{color}]{text}[/]" if color else text)
