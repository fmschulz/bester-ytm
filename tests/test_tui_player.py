"""The player deck: loudness envelope, seek bar, crossfader, volume wedge, track text."""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult

from bester_ytm.playback import PlaybackStatus
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.tui_player import (
    SeekBar,
    TrackEnvelope,
    VolumeMeter,
    crossfader_text,
    loudness,
    track_text,
    volume_text,
)


def test_envelope_records_loudness_where_it_was_heard() -> None:
    envelope = TrackEnvelope(buckets=4)

    envelope.record("v1", 0.6, 0.8)

    assert envelope.video_id == "v1"
    assert envelope.levels == [None, None, 0.8, None]


def test_envelope_keeps_the_louder_reading_when_a_stretch_replays() -> None:
    envelope = TrackEnvelope(buckets=4)

    envelope.record("v1", 0.1, 0.9)
    envelope.record("v1", 0.1, 0.2)
    envelope.record("v1", 1.0, 0.4)

    assert envelope.levels == [0.9, None, None, 0.4]


def test_envelope_starts_afresh_for_a_new_track() -> None:
    envelope = TrackEnvelope(buckets=4)
    envelope.record("v1", 0.1, 0.9)

    envelope.record("v2", 0.9, 0.5)

    assert envelope.video_id == "v2"
    assert envelope.levels == [None, None, None, 0.5]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (PlaybackStatus(running=False, transition_style="crossfade"), "A ●━━━━━━━━━━ B  6s"),
        (
            PlaybackStatus(running=True, active_deck="B", transition_style="crossfade"),
            "A ━━━━━━━━━━● B  6s",
        ),
        (
            PlaybackStatus(
                running=True, active_deck="B", mix_progress=0.3, transition_style="crossfade"
            ),
            "A ━━━●━━━━━━━ B  6s",
        ),
        (
            PlaybackStatus(
                running=True, active_deck="A", mix_progress=0.3, transition_style="crossfade"
            ),
            "A ━━━━━━━●━━━ B  6s",
        ),
        (PlaybackStatus(running=True), "A ●┄┄┄┄┄┄┄┄┄┄ B  cut"),
    ],
)
def test_crossfader_knob_follows_the_live_deck_and_the_blend(
    status: PlaybackStatus, expected: str
) -> None:
    assert crossfader_text(status) == expected


@pytest.mark.parametrize(
    ("volume", "muted", "expected"),
    [
        (80, False, "▁▂▃▄▅▆▇█  80%"),
        (100, False, "▁▂▃▄▅▆▇█ 100%"),
        (80, True, "▁▂▃▄▅▆▇█ mute"),
    ],
)
def test_volume_wedge_labels_the_level(volume: float, muted: bool, expected: str) -> None:
    assert volume_text(volume, muted=muted) == expected


def test_volume_wedge_lights_bars_up_to_the_level() -> None:
    lit = volume_text(80, muted=False).spans[0]

    assert (lit.start, lit.end) == (0, 6)


def test_track_text_orders_title_artist_album() -> None:
    song = SongCandidate(
        video_id="v", title="Myth", artists=["Beach House"], album="Bloom", year="2012"
    )
    bare = SongCandidate(video_id="w", title="Untitled")

    assert track_text(song) == "Myth  Beach House  Bloom 2012"
    assert track_text(bare) == "Untitled"


class DeckApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.seeks: list[float] = []
        self.actions: list[str] = []

    def compose(self) -> ComposeResult:
        yield SeekBar(id="progress")
        yield VolumeMeter(volume_text(50, muted=False), id="volume")

    def on_seek_bar_seek(self, message: SeekBar.Seek) -> None:
        self.seeks.append(message.fraction)

    def action_mute(self) -> None:
        self.actions.append("mute")

    def action_volume_up(self) -> None:
        self.actions.append("up")


def test_seek_bar_draws_heard_loudness_up_to_the_playhead() -> None:
    async def run() -> None:
        app = DeckApp()
        async with app.run_test(size=(10, 3)) as pilot:
            bar = app.query_one(SeekBar)
            bar.show(0.5, [1.0, 0.0, None, 0.5, 1.0, 1.0, 0.5, None, None, 0.5])
            await pilot.pause()

            line = bar.render_line(0)

            assert line.text == "█▁▁▅██▅▁▁▅"
            assert [segment.text for segment in line] == ["█▁▁▅█", "█", "▅▁▁▅"]

    asyncio.run(run())


def test_idle_seek_bar_is_a_plain_baseline() -> None:
    async def run() -> None:
        app = DeckApp()
        async with app.run_test(size=(10, 3)) as pilot:
            bar = app.query_one(SeekBar)
            bar.show(None, ())
            await pilot.pause()

            assert bar.render_line(0).text == "▁" * 10

    asyncio.run(run())


def test_clicking_the_seek_bar_asks_to_seek_there() -> None:
    async def run() -> None:
        app = DeckApp()
        async with app.run_test(size=(11, 3)) as pilot:
            await pilot.click(SeekBar, offset=(5, 0))
            await pilot.pause()

            assert app.seeks == [0.5]

    asyncio.run(run())


def test_volume_wedge_mutes_on_click_and_turns_with_the_wheel() -> None:
    async def run() -> None:
        app = DeckApp()
        async with app.run_test(size=(20, 3)) as pilot:
            await pilot.click(VolumeMeter)
            await pilot.pause()
            wedge = app.query_one(VolumeMeter)
            await wedge.on_mouse_scroll_up(None)  # type: ignore[arg-type]  # event unused

            assert app.actions == ["mute", "up"]

    asyncio.run(run())


@pytest.mark.parametrize(
    ("rms_db", "expected"), [(-60.0, 0.0), (-42.0, 0.0), (-27.0, 0.5), (-12.0, 1.0), (-3.0, 1.0)]
)
def test_loudness_uses_a_fixed_scale(rms_db: float, expected: float) -> None:
    assert loudness(rms_db) == pytest.approx(expected)


def test_envelope_start_forgets_the_previous_play() -> None:
    envelope = TrackEnvelope(buckets=4)
    envelope.record("v1", 0.9, 0.8)

    envelope.start("v1")

    assert envelope.video_id == "v1"
    assert envelope.levels == [None, None, None, None]
