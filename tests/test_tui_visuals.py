from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from bester_ytm.playback import PlaybackStatus
from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_visuals import AudioLevelMeter, _mythos_nodes, render_visual_panel

EFFECTS = ("mythos", "bars", "wave", "pulse", "scope")


def _plain_rows(panel: str) -> list[str]:
    """Strip the per-row gradient markup: '[#hex]chars[/]' -> 'chars'."""
    rows = []
    for line in panel.splitlines():
        assert line.startswith("[#") and line.endswith("[/]")
        rows.append(line.split("]", 1)[1][:-3])
    return rows


def _levels(count: int = 64) -> list[float]:
    """A varied loudness history so every effect (bars/wave included) draws something."""
    return [0.2 + 0.6 * (0.5 + 0.5 * math.sin(index * 0.4)) for index in range(count)]


@pytest.mark.parametrize("effect", EFFECTS)
def test_panels_fill_the_requested_dimensions(effect: str) -> None:
    levels = _levels(60)
    panel = render_visual_panel(effect, 7.0, width=40, height=9, running=True, levels=levels)

    rows = _plain_rows(panel)
    assert len(rows) == 9
    assert all(len(row) == 40 for row in rows)
    assert panel == render_visual_panel(
        effect, 7.0, width=40, height=9, running=True, levels=levels
    )


@pytest.mark.parametrize("effect", EFFECTS)
def test_panels_animate_with_audio(effect: str) -> None:
    levels = _levels(60)
    first = render_visual_panel(effect, 1.0, width=40, height=9, running=True, levels=levels)
    # The next tick: a fresh loud sample scrolls in and the audio phase advances.
    second = render_visual_panel(
        effect, 3.4, width=40, height=9, running=True, levels=levels + [0.95]
    )

    assert first != second
    assert "".join(_plain_rows(first)).strip()  # actually draws something


def test_effects_render_distinct_panels() -> None:
    levels = _levels(60)
    frames = {
        effect: render_visual_panel(
            effect, 5.0, width=40, height=9, running=True, levels=levels
        )
        for effect in EFFECTS
    }
    assert len(set(frames.values())) == len(EFFECTS)


def test_louder_music_drives_bigger_bars() -> None:
    quiet = render_visual_panel("bars", 9.0, width=40, height=9, running=True, levels=[0.1] * 40)
    loud = render_visual_panel("bars", 9.0, width=40, height=9, running=True, levels=[1.0] * 40)

    assert "".join(_plain_rows(loud)).count("█") > "".join(_plain_rows(quiet)).count("█")


def test_bars_track_recent_loudness_per_column() -> None:
    """Rhythm proof: the right-most columns grow when the most recent audio is loud."""
    width, height = 30, 9
    quiet = _plain_rows(
        render_visual_panel(
            "bars", 0.0, width=width, height=height, running=True, levels=[0.05] * width
        )
    )
    loud_now = _plain_rows(
        render_visual_panel(
            "bars", 0.0, width=width, height=height, running=True,
            levels=[0.05] * (width - 5) + [0.95] * 5,
        )
    )

    def filled(rows: list[str], column: int) -> int:
        return sum(1 for row in rows if row[column] != " ")

    assert all(filled(loud_now, x) > filled(quiet, x) for x in range(width - 5, width))


def test_level_shifts_the_gradient_brighter() -> None:
    quiet = render_visual_panel("pulse", 4.0, width=40, height=9, running=True, levels=[0.0])
    loud = render_visual_panel("pulse", 4.0, width=40, height=9, running=True, levels=[1.0])

    assert quiet != loud


def test_idle_panel_awaits_signal() -> None:
    panel = render_visual_panel("mythos", 3.0, width=40, height=9, running=False)

    rows = _plain_rows(panel)
    assert any("awaiting signal" in row for row in rows)
    assert rows[-1] == "▁" * 40


def test_tiny_areas_render_nothing() -> None:
    assert render_visual_panel("bars", 1, width=4, height=9, running=True) == ""
    assert render_visual_panel("bars", 1, width=40, height=2, running=True) == ""


def test_audio_level_meter_tracks_loudness() -> None:
    meter = AudioLevelMeter()
    start = meter.level

    for _ in range(6):
        quiet = meter.update(-45.0)
    for _ in range(6):
        loud = meter.update(-12.0)

    assert quiet < start
    assert loud > quiet
    assert 0.0 <= quiet <= 1.0 and 0.0 <= loud <= 1.0
    assert meter.update(None) == loud  # silence in the pipe keeps the last level


def test_mythos_nodes_glide_rather_than_teleport() -> None:
    """One loud tick advances phase ~2.4; nodes must move a little, not jump across the panel."""
    width, height = 40, 9
    before = _mythos_nodes(50.0, width, height)
    after = _mythos_nodes(52.4, width, height)

    for (x1, y1), (x2, y2) in zip(before, after, strict=True):
        assert abs(x1 - x2) <= width * 0.15
        assert abs(y1 - y2) <= height * 0.2


def test_audio_level_meter_reacts_to_narrow_band_dynamics() -> None:
    """Loudness-normalized music varies only a few dB; the meter must still visibly swing."""
    meter = AudioLevelMeter()
    levels = []
    for index in range(40):
        rms = -12.0 + (2.0 if index % 2 == 0 else -2.0)  # 4 dB peak-to-peak around -12
        levels.append(meter.update(rms))

    tail = levels[-10:]
    assert max(tail) - min(tail) > 0.15  # the visual genuinely moves with the beat


class FakeVisualWidget:
    def __init__(self, width: int = 40, height: int = 9) -> None:
        self.size = SimpleNamespace(width=width, height=height)
        self.value = ""
        self.classes: set[str] = set()

    def update(self, value: str) -> None:
        self.value = value

    def add_class(self, name: str) -> None:
        self.classes.add(name)

    def remove_class(self, name: str) -> None:
        self.classes.discard(name)


def _make_app(monkeypatch, tmp_path, widget) -> BesterYTMApp:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = BesterYTMApp()
    monkeypatch.setattr(
        app, "_query_optional", lambda selector, widget_type=None: widget
    )
    return app


def test_animation_advances_and_reads_audio_level(monkeypatch, tmp_path) -> None:
    widget = FakeVisualWidget()
    app = _make_app(monkeypatch, tmp_path, widget)
    app.last_playback_status = PlaybackStatus(running=True, current_video_id="v1")
    readings: list[int] = []
    monkeypatch.setattr(
        app.playback, "read_audio_level_db", lambda: readings.append(1) or -14.0
    )

    app._animate_visual_panel()
    first = widget.value
    app._animate_visual_panel()

    assert app.visual_phase > 0.0  # phase advances with the audio
    assert len(app.audio_levels) == 2  # each running tick pushes one loudness sample
    assert len(readings) == 2
    assert widget.value != first
    assert "idle-effect" not in widget.classes


def test_visual_phase_surges_with_loudness_and_onsets(monkeypatch, tmp_path) -> None:
    """Loud audio advances the phase faster than quiet, and a sudden onset adds a kick."""
    app = _make_app(monkeypatch, tmp_path, FakeVisualWidget())
    app.last_playback_status = PlaybackStatus(running=True, current_video_id="v1")
    monkeypatch.setattr(app.playback, "read_audio_level_db", lambda: None)

    app.audio_meter.level = 0.05
    app._animate_visual_panel()
    quiet_step = app.visual_phase

    app.audio_meter.level = 0.9  # jump: same-level steady state would advance less
    before = app.visual_phase
    app._animate_visual_panel()
    onset_step = app.visual_phase - before

    before = app.visual_phase  # second loud tick: no onset, pure loudness speed
    app._animate_visual_panel()
    loud_step = app.visual_phase - before

    assert loud_step > 3 * quiet_step
    assert onset_step > loud_step


def test_animation_freezes_when_paused_and_idles_when_stopped(
    monkeypatch, tmp_path
) -> None:
    widget = FakeVisualWidget()
    app = _make_app(monkeypatch, tmp_path, widget)
    app.last_playback_status = PlaybackStatus(running=True, paused=True)

    app._animate_visual_panel()
    frozen = widget.value
    app._animate_visual_panel()

    assert app.visual_phase == 0.0  # paused: the audio phase does not advance
    assert widget.value == frozen
    assert "paused-effect" in widget.classes

    app.last_playback_status = PlaybackStatus(running=False)
    app._animate_visual_panel()

    assert "awaiting signal" in widget.value
    assert "idle-effect" in widget.classes
