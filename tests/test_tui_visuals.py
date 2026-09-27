"""Stage scenes and the audio signal: scenes react to loudness; the app freezes stills."""

from __future__ import annotations

import math
import time
from dataclasses import replace

import pytest

from bester_ytm.playback import PlaybackStatus
from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_canvas import PixelCanvas
from bester_ytm.tui_visuals import (
    EFFECT_ORDER,
    IDLE_LEVEL,
    RIDGE_SAMPLES,
    STILL_FRAME,
    AudioFrame,
    AudioLevelMeter,
    AudioSignal,
    draw_scene,
)


def _history(count: int = 64) -> tuple[float, ...]:
    """A varied loudness history so every scene draws something."""
    return tuple(0.2 + 0.6 * (0.5 + 0.5 * math.sin(index * 0.4)) for index in range(count))


def _frame(level: float = 0.7, *, phase: float = 7.0, samples: int = 64) -> AudioFrame:
    history = _history(samples)[:-1] + (level,)
    return AudioFrame(level=level, onset=0.0, phase=phase, history=history, samples=samples)


def _drawn(scene: str, frame: AudioFrame, size: tuple[int, int] = (40, 9)) -> PixelCanvas:
    canvas = PixelCanvas(*size)
    draw_scene(scene, canvas, frame)
    return canvas


@pytest.mark.parametrize("scene", EFFECT_ORDER)
def test_scenes_light_the_canvas_within_range(scene: str) -> None:
    canvas = _drawn(scene, _frame())

    assert max(canvas.pixels) > 0.3
    assert min(canvas.pixels) >= 0.0


@pytest.mark.parametrize("scene", EFFECT_ORDER)
def test_scenes_are_repeatable_for_the_same_frame(scene: str) -> None:
    assert _drawn(scene, _frame()).pixels == _drawn(scene, _frame()).pixels


@pytest.mark.parametrize("scene", EFFECT_ORDER)
def test_scenes_move_with_the_audio(scene: str) -> None:
    first = _drawn(scene, _frame(0.4, phase=1.0, samples=60))
    later = _drawn(scene, _frame(0.95, phase=3.4, samples=61))

    assert first.pixels != later.pixels


def test_scenes_differ_from_each_other() -> None:
    frames = {tuple(_drawn(scene, _frame()).pixels) for scene in EFFECT_ORDER}

    assert len(frames) == len(EFFECT_ORDER)


def test_retired_scene_names_fall_back_to_astra() -> None:
    assert _drawn("mythos", _frame()).pixels == _drawn("astra", _frame()).pixels


@pytest.mark.parametrize("scene", ["astra", "bars", "scope"])
def test_louder_music_lights_more_of_the_scene(scene: str) -> None:
    quiet = _drawn(scene, AudioFrame(0.05, 0.0, 9.0, (0.05,) * 40, 40))
    loud = _drawn(scene, AudioFrame(1.0, 0.0, 9.0, (1.0,) * 40, 40))

    assert sum(loud.pixels) > sum(quiet.pixels)


def test_bars_track_recent_loudness_per_column() -> None:
    """Rhythm proof: the right-most columns grow when the most recent audio is loud."""
    width = 30
    quiet = _drawn("bars", AudioFrame(0.05, 0.0, 0.0, (0.05,) * width, width), (width, 9))
    loud = _drawn(
        "bars", AudioFrame(0.95, 0.0, 0.0, (0.05,) * (width - 5) + (0.95,) * 5, width), (width, 9)
    )

    def lit(canvas: PixelCanvas, column: int) -> int:
        return sum(1 for row in range(canvas.height) if canvas.pixels[row * width + column] > 0)

    assert all(lit(loud, column) > lit(quiet, column) for column in range(width - 5, width))


def _front_ridge_top(canvas: PixelCanvas) -> int:
    """Highest row of the front ridge: its line is the lowest lit pixel of each column."""
    width = canvas.width
    return min(
        max(row for row in range(canvas.height) if canvas.pixels[row * width + column])
        for column in range(width)
    )


def test_pulsar_front_ridge_rises_with_the_live_level() -> None:
    history = (0.1,) * 60
    quiet = _drawn("pulsar", AudioFrame(0.1, 0.0, 0.0, history, 60), (60, 20))
    loud = _drawn("pulsar", AudioFrame(1.0, 0.0, 0.0, history, 60), (60, 20))

    assert _front_ridge_top(loud) < _front_ridge_top(quiet)


def test_pulsar_scrolls_a_ridge_back_every_few_samples() -> None:
    start = _frame(samples=60)
    later = AudioFrame(start.level, 0.0, start.phase, start.history, start.samples + RIDGE_SAMPLES)

    assert _drawn("pulsar", start).pixels != _drawn("pulsar", later).pixels


def test_scope_leaves_fading_trails() -> None:
    canvas = PixelCanvas(40, 9)
    draw_scene("scope", canvas, _frame(phase=1.0))
    first_frame = [index for index, value in enumerate(canvas.pixels) if value >= 0.7]

    draw_scene("scope", canvas, _frame(phase=30.0))

    assert any(0.0 < canvas.pixels[index] < 0.7 for index in first_frame)


def test_audio_level_meter_tracks_loudness() -> None:
    meter = AudioLevelMeter()
    start = meter.level

    for _ in range(12):
        quiet = meter.update(-45.0)
    for _ in range(12):
        loud = meter.update(-12.0)

    assert quiet < start
    assert loud > quiet
    assert 0.0 <= quiet <= 1.0 and 0.0 <= loud <= 1.0
    assert meter.update(None) == loud  # silence in the pipe keeps the last level


def test_audio_level_meter_delays_readings_to_match_the_speakers() -> None:
    """mpv filters audio ~0.25s before it is audible; the meter must not react early."""
    meter = AudioLevelMeter(sample_interval=0.05)
    start = meter.level

    early = [meter.update(-10.0) for _ in range(5)]
    heard = meter.update(-10.0)

    assert all(value == start for value in early)  # still in the delay line
    assert heard != start  # the sixth tick is when the loud audio reaches the ears


@pytest.mark.parametrize("silence", [-100.0, -math.inf])
def test_audio_silence_releases_after_the_speaker_delay(silence: float) -> None:
    meter = AudioLevelMeter(sample_interval=0.05)
    meter.level = 1.0
    early = [meter.update(silence) for _ in range(5)]
    assert early == [1.0] * 5
    assert meter.update(silence) < 1.0
    for _ in range(40):
        meter.update(silence)
    assert meter.level < 0.001
    for _ in range(6):
        meter.update(-10.0)
    assert meter.level > 0.9
    assert math.isfinite(meter.floor_db) and math.isfinite(meter.ceiling_db)


@pytest.mark.parametrize("interval", [0.025, 0.05, 0.125])
def test_silence_decay_is_independent_of_sample_rate(interval: float) -> None:
    meter = AudioLevelMeter(sample_interval=interval)
    meter.level = 1.0
    for _ in range(round(1.25 / interval)):
        meter.update(-math.inf)
    # The first quarter second is buffered; one second of audible silence follows.
    assert meter.level == pytest.approx(0.004)


def test_audio_level_meter_reacts_to_narrow_band_dynamics() -> None:
    """Loudness-normalized music varies only a few dB; the meter must still visibly swing."""
    meter = AudioLevelMeter(sample_interval=0.05)
    levels = []
    for index in range(80):
        # 4 dB peak-to-peak around -12, alternating every 5 samples (~a 2 Hz beat at 20 fps)
        rms = -12.0 + (2.0 if (index // 5) % 2 == 0 else -2.0)
        levels.append(meter.update(rms))

    tail = levels[-20:]
    assert max(tail) - min(tail) > 0.15  # the visual genuinely moves with the beat


def test_signal_phase_surges_with_loudness_and_onsets() -> None:
    """Loud audio advances the phase faster than quiet, and a sudden onset adds a kick."""
    signal = AudioSignal(0.05)

    signal.meter.level = 0.05
    signal.sample(None)
    quiet_step = signal.phase

    signal.meter.level = 0.9  # a jump: the steady state would advance less
    before = signal.phase
    signal.sample(None)
    onset_step = signal.phase - before

    before = signal.phase  # second loud sample: no onset, pure loudness speed
    signal.sample(None)
    loud_step = signal.phase - before

    assert loud_step > 3 * quiet_step
    assert onset_step > loud_step


def test_signal_frame_measures_onset_against_recent_samples() -> None:
    signal = AudioSignal(0.05)
    for _ in range(12):
        signal.meter.level = 0.2
        signal.sample(None)
    signal.meter.level = 0.9
    signal.sample(None)

    frame = signal.frame()

    assert frame.level == 0.9
    assert frame.onset > 0.5
    assert frame.samples == 13
    assert len(frame.history) == 13


def test_still_frame_keeps_the_shapes_but_dims_them() -> None:
    signal = AudioSignal(0.05)
    signal.sample(-12.0)

    still = signal.still()

    assert still.level == IDLE_LEVEL
    assert still.onset == 0.0
    assert still.history == signal.frame().history


class FakeStage:
    def __init__(self) -> None:
        self.frames: list[tuple[str, AudioFrame]] = []
        self.classes: set[str] = set()

    def show(self, scene: str, frame: AudioFrame) -> None:
        self.frames.append((scene, frame))

    def set_class(self, enabled: bool, name: str) -> None:
        if enabled:
            self.classes.add(name)
        else:
            self.classes.discard(name)


def _make_app(monkeypatch, tmp_path, stage: FakeStage) -> BesterYTMApp:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = BesterYTMApp()
    monkeypatch.setattr(
        app,
        "_query_optional",
        lambda selector, widget_type=None: stage if selector == "#big-visual" else None,
    )
    return app


def test_animation_samples_audio_and_draws_every_live_frame(monkeypatch, tmp_path) -> None:
    stage = FakeStage()
    app = _make_app(monkeypatch, tmp_path, stage)
    app.last_playback_status = PlaybackStatus(running=True, current_video_id="v1")
    feed = iter([-40.0] * 6 + [-10.0] * 6)  # quiet intro, then a loud passage
    monkeypatch.setattr(app.playback, "read_audio_level_db", lambda: next(feed))

    for _ in range(12):
        app._animate_visual_panel()

    assert app.signal.samples == 12
    assert app.signal.phase > 0.0
    assert len(stage.frames) == 12
    assert stage.frames[0][1] != stage.frames[-1][1]
    assert not stage.classes


def test_animation_freezes_when_paused_and_dims_when_stopped(monkeypatch, tmp_path) -> None:
    stage = FakeStage()
    app = _make_app(monkeypatch, tmp_path, stage)
    app.last_playback_status = PlaybackStatus(running=True, paused=True)

    app._animate_visual_panel()
    app._animate_visual_panel()

    assert app.signal.samples == 0  # paused: nothing is sampled
    assert len(stage.frames) == 1  # drawn once on entering the state, then frozen
    assert "paused-effect" in stage.classes

    app.last_playback_status = PlaybackStatus(running=False)
    app._animate_visual_panel()

    assert len(stage.frames) == 2
    assert stage.frames[-1][1].level == IDLE_LEVEL
    assert stage.classes == {"idle-effect"}


def test_live_frames_record_loudness_at_the_playhead(monkeypatch, tmp_path) -> None:
    app = _make_app(monkeypatch, tmp_path, FakeStage())
    app.last_playback_status = PlaybackStatus(
        running=True, current_video_id="v1", position_seconds=50, duration_seconds=100
    )
    app._status_clock = time.monotonic()
    monkeypatch.setattr(app.playback, "read_audio_level_db", lambda: -10.0)

    for _ in range(8):
        app._animate_visual_panel()

    assert app.envelope.video_id == "v1"
    assert app.envelope.levels[len(app.envelope.levels) // 2] is not None
    assert sum(level is not None for level in app.envelope.levels) == 1


@pytest.mark.parametrize("scene", EFFECT_ORDER)
def test_every_scene_shows_something_before_any_music(scene: str) -> None:
    canvas = PixelCanvas(40, 9)

    draw_scene(scene, canvas, STILL_FRAME)

    assert max(canvas.pixels) > 0.0


def _heard(app: BesterYTMApp) -> int:
    return sum(level is not None for level in app.envelope.levels)


def _playing(video_id: str, process_id: int = 100) -> PlaybackStatus:
    return PlaybackStatus(
        running=True,
        current_video_id=video_id,
        position_seconds=80,
        duration_seconds=100,
        process_id=process_id,
    )


def _discard_worker(work: object, **kwargs: object) -> None:
    """Drop a worker unrun; a coroutine must be closed or Python warns."""
    close = getattr(work, "close", None)
    if close is not None:
        close()


def _app_hearing_v1(monkeypatch, tmp_path) -> BesterYTMApp:
    """An app whose seek bar has heard 80% into v1, played by process 100."""
    app = _make_app(monkeypatch, tmp_path, FakeStage())
    monkeypatch.setattr(app, "run_worker", _discard_worker)
    app._refresh_playback(_playing("v1"))
    app.envelope.record("v1", 0.8, 0.9)
    return app


def test_seek_bar_picture_starts_afresh_after_a_detour_to_radio(monkeypatch, tmp_path) -> None:
    app = _app_hearing_v1(monkeypatch, tmp_path)

    app._refresh_playback(_playing("radio:bytefm", process_id=101))
    app._refresh_playback(_playing("v1", process_id=102))

    assert app.envelope.video_id == "v1"
    assert _heard(app) == 0


def test_a_restart_of_the_same_song_starts_a_fresh_picture(monkeypatch, tmp_path) -> None:
    """A cut or a crossfade into the same song runs a new mpv process."""
    app = _app_hearing_v1(monkeypatch, tmp_path)

    app._refresh_playback(_playing("v1", process_id=101))

    assert _heard(app) == 0


def test_polls_pause_and_resync_keep_the_picture(monkeypatch, tmp_path) -> None:
    """Starting a new playlist re-syncs the playing track; its picture must survive."""
    app = _app_hearing_v1(monkeypatch, tmp_path)

    app._refresh_playback(_playing("v1"))
    app._sync_current_track("v1")
    app._refresh_playback(replace(_playing("v1"), paused=True))

    assert _heard(app) == 1


def test_bars_keep_their_baseline_through_silence() -> None:
    canvas = PixelCanvas(40, 9)

    draw_scene("bars", canvas, AudioFrame(0.0, 0.0, 0.0, (0.0,) * 100, 100))

    bottom = canvas.pixels[(canvas.height - 1) * canvas.width :]
    assert min(bottom) > 0.0
