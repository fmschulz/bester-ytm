"""Audio-reactive stage scenes and the loudness signal that drives them.

mpv measures RMS loudness as it plays (``deck.spawn_mpv``). ``AudioSignal`` turns
those readings into a smoothed level, a history, an onset strength and a motion
clock (``phase``) that runs faster when the music is loud, so every scene moves
with the music rather than at a constant rate. Scenes paint light intensities onto
a ``PixelCanvas``; the stage colours them with the active theme.
"""

from __future__ import annotations

import math
import random
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache

from .tui_astra import draw_astra
from .tui_canvas import PixelCanvas

DEFAULT_LEVEL = 0.6
# The level an idle stage is drawn at: shapes visible, barely lit.
IDLE_LEVEL = 0.12
# mpv's astats filter measures audio as it is filtered, which runs ahead of the
# speakers by the output buffer (--audio-buffer 0.2s plus the device buffer).
# Readings are held back this long so the visuals move with what is heard.
MPV_AUDIO_LEAD_SECONDS = 0.25
HISTORY_SAMPLES = 512
# One pulsar ridge per this many samples: about 0.3 s at the default 20 fps.
RIDGE_SAMPLES = 6

EFFECT_ORDER = ("astra", "pulsar", "bars", "scope")
EFFECT_LABELS = {"astra": "Astra", "pulsar": "Pulsar", "bars": "Bars", "scope": "Scope"}
EFFECT_OPTIONS = [(EFFECT_LABELS[key], key) for key in EFFECT_ORDER]


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """Everything a scene may react to on one frame.

    Attributes:
        level: Smoothed loudness of the newest sample, 0..1.
        onset: How far that level jumps above the recent average, 0..1.
        phase: Motion clock; it runs faster when the music is loud.
        history: Recent levels, newest last.
        samples: Samples taken since start; ties pulsar ridges to moments in time.
    """

    level: float
    onset: float
    phase: float
    history: tuple[float, ...]
    samples: int


STILL_FRAME = AudioFrame(level=IDLE_LEVEL, onset=0.0, phase=0.0, history=(), samples=0)

Scene = Callable[[PixelCanvas, AudioFrame], None]


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
        if rms_db is None:
            return self.level
        self._pending.append(rms_db)
        if len(self._pending) <= self._delay_samples:
            return self.level
        return self._absorb(self._pending.popleft())

    def _absorb(self, rms_db: float) -> float:
        # astats reports -inf for digital silence. Release after the audio delay,
        # without pulling the adaptive range down to an unusable noise floor.
        if rms_db < -90.0:
            self.level *= 0.004**self.sample_interval
            return self.level
        # Relax the floor/ceiling toward the current reading (~1s window), so the
        # meter follows the melody and beat instead of locking onto the song's
        # lifetime min/max and going flat on loudness-normalized tracks.
        adapt = 0.27**self.sample_interval
        self.floor_db = min(rms_db, self.floor_db * adapt + rms_db * (1 - adapt))
        self.ceiling_db = max(rms_db, self.ceiling_db * adapt + rms_db * (1 - adapt))
        span = max(8.0, self.ceiling_db - self.floor_db)
        instant = min(1.0, max(0.0, (rms_db - self.floor_db) / span))
        if instant >= self.level:
            self.level = instant
        else:
            release = 0.004**self.sample_interval
            self.level = self.level * release + instant * (1 - release)
        return self.level


class AudioSignal:
    """Samples live loudness into the frames the scenes draw."""

    def __init__(self, sample_interval: float) -> None:
        self.meter = AudioLevelMeter(sample_interval)
        self.history: deque[float] = deque(maxlen=HISTORY_SAMPLES)
        self.phase = 0.0
        self.samples = 0

    def sample(self, rms_db: float | None) -> None:
        """Take one loudness reading (None keeps the last level) and advance the clock."""
        level = self.meter.update(rms_db)
        previous = self.history[-1] if self.history else level
        self.history.append(level)
        self.samples += 1
        # Near-still in lulls, flowing when loud, with an extra kick on each onset so
        # the motion locks to the beat. Drift is per second, so the speed is the same
        # at any fps; the onset kick is per beat and stays unscaled.
        drift = (1.6 + 11.2 * level) * self.meter.sample_interval
        self.phase += drift + 3.0 * max(0.0, level - previous)

    def frame(self) -> AudioFrame:
        """The live frame; the onset is measured against the last dozen samples."""
        history = tuple(self.history)
        level = history[-1] if history else self.meter.level
        recent = history[-12:] or (level,)
        onset = max(0.0, level - sum(recent) / len(recent))
        return AudioFrame(level, onset, self.phase, history, self.samples)

    def still(self) -> AudioFrame:
        """A calm frame for an idle stage: the last shapes, barely lit."""
        return replace(self.frame(), level=IDLE_LEVEL, onset=0.0)


def draw_scene(name: str, canvas: PixelCanvas, frame: AudioFrame) -> None:
    """Draw scene ``name`` (Astra when the name is unknown, e.g. a retired scene)."""
    SCENES.get(name, draw_astra)(canvas, frame)


def draw_pulsar(canvas: PixelCanvas, frame: AudioFrame) -> None:
    """Joy Division's pulsar plot from the loudness history, newest ridge in front.

    Each ridge shows the loudest moment of its slice of time and keeps its shape as
    it recedes. The front ridge follows the live level, and all ridges glide up
    continuously, so the plot scrolls smoothly instead of jumping a row at a time.
    """
    canvas.clear()
    count = max(6, canvas.height // 3)
    spacing = canvas.height / (count + 6)
    clock = frame.samples / RIDGE_SAMPLES
    newest = int(clock)
    for age in range(count, -1, -1):
        ridge = newest - age
        slot = count - (clock - ridge)
        level = frame.level if age == 0 else _ridge_level(frame, ridge)
        _draw_ridge(
            canvas,
            base=spacing * (slot + 5.5),
            lift=spacing * 5.0 * (0.1 + 0.9 * level),
            profile=_ridge_profile(ridge, canvas.width),
            glow=0.45 + 0.55 * max(0.0, slot) / count,
        )


def draw_bars(canvas: PixelCanvas, frame: AudioFrame) -> None:
    """A loudness skyline over a faint baseline: one column per recent sample."""
    canvas.clear()
    width, height, pixels = canvas.width, canvas.height, canvas.pixels
    baseline = (height - 1) * width
    pixels[baseline : baseline + width] = [0.25] * width
    recent = frame.history[-width:]
    for column, level in enumerate(recent, start=width - len(recent)):
        filled = min(1.0, level) * height
        full = int(filled)
        for rise in range(full):
            pixels[(height - 1 - rise) * width + column] = 0.3 + 0.7 * rise / height
        if full < height:
            pixels[(height - 1 - full) * width + column] = (filled - full) * (
                0.3 + 0.7 * full / height
            )


def draw_scope(canvas: PixelCanvas, frame: AudioFrame) -> None:
    """An oscilloscope in XY mode: a Lissajous knot that swells with loudness.

    The screen keeps a fading copy of earlier frames, like a phosphor tube, so the
    knot leaves trails as it turns.
    """
    canvas.fade(0.6)
    center_x, center_y = (canvas.width - 1) / 2, (canvas.height - 1) / 2
    radius_y = center_y * (0.45 + 0.5 * frame.level)
    radius_x = min(center_x, 1.8 * radius_y)
    turn = frame.phase * 0.11
    brightness = min(1.0, 0.7 + 0.3 * frame.level + frame.onset)
    points = max(240, round(24 * (radius_x + radius_y)))
    for step in range(points):
        angle = step / points * math.tau
        x = round(center_x + math.sin(3 * angle + turn) * radius_x)
        y = round(center_y + math.sin(2 * angle) * radius_y)
        canvas.plot(x, y, brightness)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            canvas.plot(x + dx, y + dy, 0.3 * brightness)


SCENES: dict[str, Scene] = {
    "astra": draw_astra,
    "pulsar": draw_pulsar,
    "bars": draw_bars,
    "scope": draw_scope,
}


def _ridge_level(frame: AudioFrame, ridge: int) -> float:
    """The loudest sample in one ridge's slice of time; 0 once it left the history."""
    first = frame.samples - len(frame.history)
    start = max(0, ridge * RIDGE_SAMPLES - first)
    stop = max(0, (ridge + 1) * RIDGE_SAMPLES - first)
    return max(frame.history[start:stop], default=0.0)


def _draw_ridge(
    canvas: PixelCanvas, *, base: float, lift: float, profile: Sequence[float], glow: float
) -> None:
    """Hide everything behind one ridge, then trace its line at ``glow``."""
    width, height, pixels = canvas.width, canvas.height, canvas.pixels
    floor = min(height - 1, int(base) + 1)
    previous: int | None = None
    for column, shape in enumerate(profile):
        y = max(0, min(height - 1, int(base - lift * shape)))
        for row in range(y + 1, floor + 1):
            pixels[row * width + column] = 0.0
        top = y if previous is None else min(y, previous)
        bottom = y if previous is None else max(y, previous)
        for row in range(top, bottom + 1):
            pixels[row * width + column] = glow
        previous = y


@lru_cache(maxsize=128)
def _ridge_profile(ridge: int, width: int) -> tuple[float, ...]:
    """A stable ridge shape peaking at 1: a few sharp peaks mid-canvas over low noise."""
    rng = random.Random(ridge)
    peaks = [
        (0.5 + rng.uniform(-0.14, 0.14), rng.uniform(0.012, 0.042), rng.uniform(0.3, 1.0))
        for _ in range(rng.randint(3, 5))
    ]
    knots = [rng.random() for _ in range(34)]
    shape = [_ridge_height(column / max(1, width - 1), peaks, knots) for column in range(width)]
    top = max(shape)
    return tuple(value / top for value in shape)


def _ridge_height(
    position: float, peaks: Sequence[tuple[float, float, float]], knots: Sequence[float]
) -> float:
    """Ridge height at ``position`` (0..1 across the canvas) before normalising."""
    window = math.exp(-(((position - 0.5) / 0.2) ** 2))
    wobble = _smooth_noise(knots, position)
    spike = sum(
        height * math.exp(-(((position - center) / spread) ** 2))
        for center, spread, height in peaks
    )
    return window * (0.25 * wobble + spike) + 0.03 * wobble


def _smooth_noise(knots: Sequence[float], position: float) -> float:
    """Value noise: smoothstep between evenly spaced random knots."""
    scaled = position * (len(knots) - 1)
    index = min(int(scaled), len(knots) - 2)
    t = scaled - index
    t = t * t * (3 - 2 * t)
    return knots[index] * (1 - t) + knots[index + 1] * t
