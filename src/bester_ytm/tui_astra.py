"""Astra: a black hole whose accretion disk heats up and spins with the music.

A procedural scene, not a spectrum: mpv supplies only RMS loudness. The disk is a
thin ring seen nearly edge-on. Its near half crosses in front of the shadow; its
far half hides behind it and reappears bent over the top (and faintly under the
bottom) as a lensed halo. The side turning towards the viewer is brighter
(Doppler beaming). Geometry that depends only on the canvas size is computed once
per size, so a frame costs about one sine per lit pixel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from .tui_canvas import PixelCanvas
    from .tui_visuals import AudioFrame

# Distances are in shadow radii. The disk is tilted ~79 degrees from face-on.
TILT_COSINE = 0.19
DISK_INNER_EDGE = 1.05
HALO_OUTER_EDGE = 2.3
STARS_PER_THOUSAND = 7

DiskPoint: TypeAlias = tuple[int, float, float, float, float]
HaloPoint: TypeAlias = tuple[int, float, float, float]
RingPoint: TypeAlias = tuple[int, float, float]
StarPoint: TypeAlias = tuple[int, float, int]


@dataclass(frozen=True, slots=True)
class AstraLayout:
    """Every lit pixel of the scene with its static geometry, for one canvas size.

    Disk points hold (pixel, weight, angle, log radius, angular speed); halo points
    (pixel, weight, angle, log radius); ring points (pixel, weight, angle); stars
    (pixel, brightness, seed).
    """

    disk: tuple[DiskPoint, ...]
    halo: tuple[HaloPoint, ...]
    ring: tuple[RingPoint, ...]
    stars: tuple[StarPoint, ...]


def draw_astra(canvas: PixelCanvas, frame: AudioFrame) -> None:
    """Paint one frame: loudness heats and spins the disk, onsets flare the ring."""
    canvas.clear()
    pixels = canvas.pixels
    layout = astra_layout(canvas.width, canvas.height)
    heat = 0.55 + 0.5 * frame.level
    spin = frame.phase * 0.9
    sin = math.sin
    for index, weight, angle, log_radius, speed in layout.disk:
        pixels[index] = (
            weight * heat * (0.62 + 0.38 * sin(11.0 * log_radius + 2.0 * angle - speed * spin))
        )
    for index, weight, angle, log_radius in layout.halo:
        value = weight * heat * (0.6 + 0.4 * sin(9.0 * log_radius - 2.0 * angle - 0.6 * spin))
        if value > pixels[index]:
            pixels[index] = value
    flare = 0.45 + 0.25 * frame.level + 0.7 * frame.onset
    for index, weight, angle in layout.ring:
        value = weight * flare * (0.8 + 0.2 * sin(2.0 * angle + 0.3 * spin))
        if value > pixels[index]:
            pixels[index] = value
    for index, brightness, seed in layout.stars:
        value = brightness * (0.7 + 0.3 * sin(0.2 * frame.phase + seed))
        if value > pixels[index]:
            pixels[index] = value


@lru_cache(maxsize=4)
def astra_layout(width: int, height: int) -> AstraLayout:
    """Classify every pixel of a ``width`` x ``height`` canvas once."""
    scale = min(width / 10.0, height / 5.2)  # pixels per shadow radius; the halo fits
    pixel = 1.0 / scale
    outer_edge = max(3.4, min(7.0, width * pixel * 0.47))  # wide stages get a long disk
    center_x, center_y = (width - 1) / 2, (height - 1) / 2
    disk: list[DiskPoint] = []
    halo: list[HaloPoint] = []
    ring: list[RingPoint] = []
    stars: list[StarPoint] = []
    for row in range(height):
        y = (row - center_y) * pixel
        for column in range(width):
            x = (column - center_x) * pixel
            index = row * width + column
            radius = math.hypot(x, y)
            if point := _disk_point(x, y, radius, outer_edge):
                disk.append((index, *point))
            # The ring straddles the shadow's edge so it never breaks between pixels.
            if (weight := _ring_weight(radius, pixel)) > 0.05:
                ring.append((index, weight, math.atan2(y, x)))
            if radius < 1.0:
                continue  # the shadow, except where the near side of the disk crosses it
            if lensed := _halo_point(x, y, radius, pixel):
                halo.append((index, *lensed))
            elif star := _star(column, row, y, radius):
                stars.append((index, *star))
    return AstraLayout(tuple(disk), tuple(halo), tuple(ring), tuple(stars))


def _disk_point(
    x: float, y: float, radius: float, outer_edge: float
) -> tuple[float, float, float, float] | None:
    """Weight, angle, log radius and angular speed where the disk covers a pixel."""
    disk_y = y / TILT_COSINE
    disk_radius = math.hypot(x, disk_y)
    if disk_y < 0 and radius < 1.0:
        return None  # far half, behind the shadow
    if not DISK_INNER_EDGE < disk_radius < outer_edge:
        return None
    inner_rim = min(1.0, (disk_radius - DISK_INNER_EDGE) / 0.35)
    outer_rim = min(1.0, (outer_edge - disk_radius) / (0.35 * outer_edge))
    falloff = (1.3 / disk_radius) ** 1.5
    angle = math.atan2(disk_y, x)
    doppler = 1.0 - 0.55 * math.cos(angle)  # the approaching (left) side is brighter
    weight = inner_rim * outer_rim * falloff * doppler
    return weight, angle, math.log(disk_radius), disk_radius**-1.5  # Keplerian speed


def _ring_weight(radius: float, pixel: float) -> float:
    """The photon ring: under a pixel wide, hugging the shadow."""
    return math.exp(-(((radius - 1.0) / (0.8 * pixel)) ** 2))


def _halo_point(
    x: float, y: float, radius: float, pixel: float
) -> tuple[float, float, float] | None:
    """Weight, angle and log radius of the lensed far side around the shadow."""
    if radius >= HALO_OUTER_EDGE:
        return None
    lift = 1.0 if y < 0 else 0.38  # the arch over the top is the bright one
    fade_in = min(1.0, (radius - 1.0) / (2.5 * pixel))
    weight = lift * fade_in * math.exp(-(radius - 1.02) / 0.28)
    if weight <= 0.03:
        return None
    return weight, math.atan2(y, x), math.log(radius)


def _star(column: int, row: int, y: float, radius: float) -> tuple[float, int] | None:
    """Brightness and twinkle seed of a star at this pixel, if one shines there."""
    seed = _pixel_hash(column, row)
    near_disk = abs(y / TILT_COSINE) < 0.5
    if seed % 1000 >= STARS_PER_THOUSAND or near_disk or radius < 1.6:
        return None
    return 0.2 + (seed % 97) / 180, seed


def _pixel_hash(column: int, row: int) -> int:
    """A well-mixed 32-bit hash, so stars scatter instead of lining up."""
    value = (column * 374761393 + row * 668265263) & 0xFFFFFFFF
    value = ((value ^ (value >> 13)) * 1274126177) & 0xFFFFFFFF
    return value ^ (value >> 16)
