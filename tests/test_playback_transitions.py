import subprocess

import pytest

from bester_ytm.playback import PlaybackController, PlaybackError, PlaybackStatus
from bester_ytm.transitions import (
    TransitionEngine,
    TransitionSettings,
    TransitionStyle,
)


class RunningProcess:
    def poll(self) -> None:
        return None


class FakeEngine:
    def __init__(self, can_mix: bool = False, mixing: bool = False) -> None:
        self.can_mix = can_mix
        self.mixing = mixing
        self._progress: float | None = 0.0 if mixing else None
        self.begin_calls: list[float] = []
        self.begin_result = True
        self.snap_calls = 0
        self.shutdown_calls = 0
        self.discard_calls = 0
        self.tick_calls = 0
        self.mirror_calls: list[bool] = []

    @property
    def is_mixing(self) -> bool:
        return self.mixing

    @property
    def mix_progress(self) -> float | None:
        return self._progress

    def can_quick_mix(self, video_id: str) -> bool:
        return self.can_mix

    def begin_crossfade(self, fade_seconds: float) -> bool:
        self.begin_calls.append(fade_seconds)
        if self.begin_result:
            self.mixing = True
            self._progress = 0.0
        return self.begin_result

    def snap(self) -> None:
        self.snap_calls += 1
        self.mixing = False
        self._progress = None

    def discard_idle_deck(self) -> None:
        self.discard_calls += 1

    def mirror_mute_to_draining(self, muted: bool) -> None:
        self.mirror_calls.append(muted)

    def tick(self) -> None:
        self.tick_calls += 1

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def crossfade_settings(fade_seconds: float = 6.0) -> TransitionSettings:
    return TransitionSettings(
        style=TransitionStyle.CROSSFADE, fade_seconds=fade_seconds
    )


def make_controller(**kwargs) -> tuple[PlaybackController, FakeEngine]:
    engine_kwargs = kwargs.pop("engine_kwargs", {})
    controller = PlaybackController(**kwargs)
    engine = FakeEngine(**engine_kwargs)
    controller._engine = engine
    return controller, engine


def test_next_quick_mixes_when_deck_is_ready(monkeypatch) -> None:
    controller, engine = make_controller(
        process=RunningProcess(),
        current_video_id="v1",
        queue=["v2"],
        transition=crossfade_settings(),
        engine_kwargs={"can_mix": True},
    )
    monkeypatch.setattr(
        controller,
        "play_queue",
        lambda: pytest.fail("quick mix must not restart mpv"),
    )

    status = controller.next()

    assert engine.begin_calls == [2.0]
    assert engine.snap_calls == 0
    assert status.mix_progress == 0.0


def test_next_quick_mix_uses_short_fade_when_configured(monkeypatch) -> None:
    controller, engine = make_controller(
        process=RunningProcess(),
        queue=["v2"],
        transition=crossfade_settings(fade_seconds=1.5),
        engine_kwargs={"can_mix": True},
    )
    monkeypatch.setattr(
        controller, "play_queue", lambda: pytest.fail("must quick mix")
    )

    controller.next()

    assert engine.begin_calls == [1.5]


def test_next_snaps_and_cuts_when_quick_mix_unavailable(monkeypatch) -> None:
    controller, engine = make_controller(
        process=RunningProcess(),
        queue=["v2"],
        transition=crossfade_settings(),
        engine_kwargs={"can_mix": False},
    )
    cut_calls: list[str] = []

    def fake_play_queue() -> PlaybackStatus:
        cut_calls.append(controller.queue[0])
        return PlaybackStatus(running=True, current_video_id="v2")

    monkeypatch.setattr(controller, "play_queue", fake_play_queue)

    controller.next()

    assert engine.snap_calls == 1
    assert cut_calls == ["v2"]


def test_next_falls_back_to_cut_when_begin_crossfade_fails(monkeypatch) -> None:
    controller, engine = make_controller(
        process=RunningProcess(),
        queue=["v2"],
        transition=crossfade_settings(),
        engine_kwargs={"can_mix": True},
    )
    engine.begin_result = False
    monkeypatch.setattr(
        controller,
        "play_queue",
        lambda: PlaybackStatus(running=True, current_video_id="v2"),
    )

    controller.next()

    assert engine.begin_calls == [2.0]
    assert engine.snap_calls == 1


def test_next_with_empty_queue_snaps_then_raises() -> None:
    controller, engine = make_controller(transition=crossfade_settings())

    with pytest.raises(PlaybackError, match="queue is empty"):
        controller.next()

    assert engine.snap_calls == 1


def test_previous_snaps_before_cutting_back(monkeypatch) -> None:
    controller, engine = make_controller(
        current_video_id="v1",
        history=["v0"],
        transition=crossfade_settings(),
    )

    def fake_play_video(video_id: str, seconds: int | None = None) -> PlaybackStatus:
        controller.current_video_id = video_id
        return PlaybackStatus(running=True, current_video_id=video_id)

    monkeypatch.setattr(controller, "play_video", fake_play_video)

    status = controller.previous()

    assert engine.snap_calls == 1
    assert status.current_video_id == "v0"
    assert controller.queue == ["v1"]


def test_pause_resume_snaps_active_mix() -> None:
    controller, engine = make_controller(transition=crossfade_settings())

    controller.pause_resume()

    assert engine.snap_calls == 1


def test_set_volume_during_mix_stores_master_without_ipc(monkeypatch) -> None:
    controller, engine = make_controller(
        process=RunningProcess(),
        current_video_id="v2",
        transition=crossfade_settings(),
        engine_kwargs={"mixing": True},
    )
    commands: list[dict[str, object]] = []
    monkeypatch.setattr(controller, "_send_ipc", commands.append)

    status = controller.set_volume(40.0)

    assert commands == []
    assert controller.master_volume == 40.0
    assert status.volume == 40.0


def test_set_volume_stores_master_and_sends_when_not_mixing(monkeypatch) -> None:
    controller = PlaybackController(process=RunningProcess())
    commands: list[dict[str, object]] = []
    monkeypatch.setattr(controller, "_send_ipc", commands.append)
    monkeypatch.setattr(
        controller, "status", lambda: PlaybackStatus(running=True)
    )

    controller.set_volume(150.0)

    assert controller.master_volume == 100.0
    assert commands == [{"command": ["set_property", "volume", 100.0]}]


def test_toggle_mute_mirrors_to_draining_deck_during_mix(monkeypatch) -> None:
    controller, engine = make_controller(
        process=RunningProcess(),
        transition=crossfade_settings(),
        engine_kwargs={"mixing": True},
    )
    commands: list[dict[str, object]] = []
    monkeypatch.setattr(controller, "_send_ipc", commands.append)
    monkeypatch.setattr(controller, "_get_property", lambda name: True)

    controller.toggle_mute()

    assert commands == [{"command": ["cycle", "mute"]}]
    assert engine.mirror_calls == [True]


def test_toggle_mute_skips_mirror_when_mute_read_fails(monkeypatch) -> None:
    controller, engine = make_controller(
        process=RunningProcess(),
        transition=crossfade_settings(),
        engine_kwargs={"mixing": True},
    )
    monkeypatch.setattr(controller, "_send_ipc", lambda payload: None)

    def failing_get_property(name: str) -> object:
        raise PlaybackError("mute read failed")

    monkeypatch.setattr(controller, "_get_property", failing_get_property)

    controller.toggle_mute()

    assert engine.mirror_calls == []


def test_status_keeps_transition_error_until_explicitly_consumed() -> None:
    controller, engine = make_controller(
        process=RunningProcess(),
        current_video_id="v2",
        transition=crossfade_settings(fade_seconds=8.0),
        engine_kwargs={"mixing": True},
    )
    engine._progress = 0.4
    controller.active_deck = "B"
    controller.master_volume = 70.0
    controller.last_transition_error = "boom"

    status = controller.status()

    assert status.transition_style == "crossfade"
    assert status.fade_seconds == 8.0
    assert status.mix_progress == 0.4
    assert status.active_deck == "B"
    assert status.transition_error == "boom"
    assert status.volume == 70.0
    # status() is side-effect-free for the error; only the display site
    # retires it through consume_transition_error().
    assert controller.status().transition_error == "boom"
    assert controller.consume_transition_error() == "boom"
    assert controller.consume_transition_error() is None
    assert controller.status().transition_error is None
    assert engine.tick_calls == 3


def test_status_without_engine_reports_inactive_defaults() -> None:
    controller = PlaybackController()

    status = controller.status()

    assert status.transition_style == "cut"
    assert status.fade_seconds == 6.0
    assert status.mix_progress is None
    assert status.active_deck == "A"
    assert status.transition_error is None


def test_stop_shuts_down_engine() -> None:
    controller, engine = make_controller(transition=crossfade_settings())

    controller.stop()

    assert engine.shutdown_calls == 1
    assert controller.process is None


def test_set_transition_style_to_cut_snaps_and_discards_idle_deck() -> None:
    controller, engine = make_controller(transition=crossfade_settings(8.0))

    settings = controller.set_transition_style(TransitionStyle.CUT)

    assert engine.snap_calls == 1
    assert engine.discard_calls == 1
    assert settings.style is TransitionStyle.CUT
    assert settings.fade_seconds == 8.0
    assert controller.transition is settings


def test_cycle_transition_style_round_trip() -> None:
    controller = PlaybackController()

    assert controller.cycle_transition_style().style is TransitionStyle.CROSSFADE
    assert controller.cycle_transition_style().style is TransitionStyle.CUT


def test_adjust_fade_seconds_clamps_to_bounds() -> None:
    controller = PlaybackController(transition=crossfade_settings(6.0))

    assert controller.adjust_fade_seconds(20.0).fade_seconds == 15.0
    assert controller.adjust_fade_seconds(-30.0).fade_seconds == 1.0
    assert controller.transition.style is TransitionStyle.CROSSFADE


def test_tick_with_cut_style_discards_idle_deck() -> None:
    controller, engine = make_controller()

    controller.tick()

    assert engine.discard_calls == 1
    assert engine.tick_calls == 0


def test_tick_with_crossfade_creates_and_drives_engine() -> None:
    controller = PlaybackController(transition=crossfade_settings())

    controller.tick()

    assert isinstance(controller._engine, TransitionEngine)


def test_play_video_sets_volume_flag_and_resets_active_deck(monkeypatch) -> None:
    calls = []

    class FakeProcess:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return FakeProcess()

    controller = PlaybackController(master_volume=73.0, active_deck="B")
    monkeypatch.setattr(controller, "_mpv_path", lambda: "mpv")
    monkeypatch.setattr(controller, "_require_stream_resolver", lambda: None)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("bester_ytm.playback.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        controller,
        "status",
        lambda: PlaybackStatus(running=True, current_video_id="v1"),
    )

    controller.play_video("v1")

    assert "--volume=73" in calls[0]
    assert controller.active_deck == "A"
