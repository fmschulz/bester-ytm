from pathlib import Path
from unittest.mock import Mock, call

import pytest

from bester_ytm.cli_play import _play_and_wait
from bester_ytm.playback import PlaybackController, PlaybackError, PlaybackStatus
from bester_ytm.transitions import TransitionSettings, TransitionStyle


@pytest.fixture
def playing(monkeypatch):
    process = Mock(pid=123)
    process.poll.return_value = None
    controller = PlaybackController(
        process=process,
        current_video_id="song",
        queue=["next", "last"],
        ipc_socket=Path("/tmp/fake-playback.sock"),
    )
    client = Mock()
    client.get_float.side_effect = lambda name: {
        "time-pos": 51.585,
        "duration": 228.861,
        "speed": 1.0,
        "volume": 100.0,
    }.get(name)
    client.get_property.return_value = False
    monkeypatch.setattr(controller, "_live_client", lambda: client)
    monkeypatch.setattr("bester_ytm.playback.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("bester_ytm.playback.terminate_process", lambda process: None)
    return controller, process, client


def test_live_failure_latches_before_transition_tick(playing):
    controller, process, _ = playing
    controller.transition = TransitionSettings(style=TransitionStyle.CROSSFADE)
    engine = Mock(is_mixing=False)
    controller._engine = engine
    process.poll.return_value = 2

    first = controller.status()
    second = controller.status()

    assert first.playback_error == second.playback_error
    assert "exit code 2" in first.playback_error
    assert controller.queue == ["next", "last"]
    engine.tick.assert_not_called()
    engine.shutdown.assert_called_once()
    assert controller.process is None


def test_recent_early_eof_is_failure(playing):
    controller, process, _ = playing
    controller.status()
    process.poll.return_value = 0

    assert "ended early" in controller.status().playback_error
    assert controller.queue == ["next", "last"]


@pytest.mark.parametrize(
    "position,duration,speed,elapsed",
    [
        (228.0, 228.861, 1.0, 0.5),
        (51.585, 228.861, 1.0, 200.0),
        (51.585, 228.861, 1.0, 15.0),
        (None, 228.861, 1.0, 0.5),
        (51.585, float("nan"), 1.0, 0.5),
        (51.585, 228.861, None, 0.5),
        (51.585, 228.861, 100.0, 2.0),
    ],
)
def test_ambiguous_or_complete_eof_is_not_failure(
    playing, monkeypatch, position, duration, speed, elapsed
):
    controller, process, client = playing
    client.get_float.side_effect = lambda name: {
        "time-pos": position,
        "duration": duration,
        "speed": speed,
    }.get(name)
    controller.status()
    monkeypatch.setattr("bester_ytm.playback.time.monotonic", lambda: 100.0 + elapsed)
    process.poll.return_value = 0

    assert controller.status().playback_error is None


@pytest.mark.parametrize("seek", ["seek_relative", "seek_absolute"])
def test_seek_disables_inference_even_when_status_still_has_old_position(
    playing, monkeypatch, seek
):
    controller, process, _ = playing
    controller.status()
    monkeypatch.setattr(controller, "_send_ipc", lambda payload: None)
    getattr(controller, seek)(220)
    controller.status()
    process.poll.return_value = 0

    assert controller.status().playback_error is None


def test_new_process_cannot_inherit_old_timing(playing):
    controller, _, _ = playing
    controller.status()
    replacement = Mock(pid=123)
    replacement.poll.return_value = 0
    controller.process = replacement

    assert controller.status().playback_error is None


@pytest.mark.parametrize("style", list(TransitionStyle))
def test_cli_failure_stops_without_advancing(playing, style, monkeypatch):
    controller, process, _ = playing
    controller.transition = TransitionSettings(style=style)
    process.poll.return_value = 2
    monkeypatch.setattr(controller, "next", lambda: pytest.fail("must not advance"))

    with pytest.raises(PlaybackError, match="Playback failed"):
        _play_and_wait(controller, None)

    assert controller.queue == ["next", "last"]
    assert controller.process is None


def test_promoted_incoming_failure_is_detected_in_same_refresh(playing):
    controller, _, _ = playing
    controller.transition = TransitionSettings(style=TransitionStyle.CROSSFADE)
    incoming = Mock(pid=456)
    incoming.poll.return_value = 2
    engine = Mock(is_mixing=False)
    controller._engine = engine
    engine.tick.side_effect = lambda: setattr(controller, "process", incoming)

    assert controller.status().playback_error is not None
    assert controller.queue == ["next", "last"]
    engine.shutdown.assert_called_once()


def test_idle_prebuffer_failure_does_not_latch_live_error(playing, monkeypatch):
    controller, _, _ = playing
    controller.transition = TransitionSettings(style=TransitionStyle.CROSSFADE)
    engine = controller._ensure_engine()
    monkeypatch.setattr(engine, "_read_live_timing", lambda: (220.0, 229.0))
    monkeypatch.setattr(controller, "_mpv_path", lambda: "mpv")
    monkeypatch.setattr(
        "bester_ytm.transitions.spawn_prebuffer_deck",
        Mock(side_effect=PlaybackError("cannot prebuffer")),
    )

    status = controller.status()

    assert status.running
    assert status.playback_error is None
    assert status.transition_error == "cannot prebuffer"
    assert controller.queue == ["next", "last"]


def test_dead_draining_deck_does_not_latch_live_error(playing, monkeypatch):
    controller, _, _ = playing
    controller.transition = TransitionSettings(style=TransitionStyle.CROSSFADE)
    engine = controller._ensure_engine()
    engine.draining_deck = Mock()
    engine.draining_deck.process.poll.return_value = 2
    engine.fader = Mock(is_active=False, failure_reason=None)
    monkeypatch.setattr(engine.reaper, "retire", Mock())
    monkeypatch.setattr(engine, "_restore_live_volume", lambda: None)

    assert controller.status().playback_error is None
    assert controller.queue == ["next", "last"]
    assert engine.draining_deck is None


def test_replay_clears_failure_and_old_timing(playing, monkeypatch):
    controller, process, client = playing
    controller.status()
    process.poll.return_value = 2
    assert controller.status().playback_error is not None
    replacement = Mock(pid=456)
    replacement.poll.return_value = None
    monkeypatch.setattr(controller, "_mpv_path", lambda: "mpv")
    monkeypatch.setattr(controller, "_require_stream_resolver", lambda: None)
    monkeypatch.setattr("bester_ytm.playback.spawn_mpv", lambda *args, **kwargs: replacement)
    monkeypatch.setattr("bester_ytm.playback.time.sleep", lambda seconds: None)
    client.get_float.return_value = None
    client.get_float.side_effect = None

    assert controller.play_video("song").playback_error is None
    replacement.poll.return_value = 0
    assert controller.status().playback_error is None


def test_replace_queue_clears_latched_error(playing):
    controller, process, _ = playing
    process.poll.return_value = 2
    assert controller.status().playback_error is not None

    controller.replace_queue(["new"])

    assert controller.status().playback_error is None
    assert controller.queue == ["new"]


@pytest.mark.parametrize("seconds", [None, 1])
def test_failure_just_after_start_keeps_queued_track(playing, monkeypatch, seconds):
    controller, _, _ = playing
    process = Mock(pid=456)
    process.poll.side_effect = [None, 2]
    monkeypatch.setattr(controller, "_mpv_path", lambda: "mpv")
    monkeypatch.setattr(controller, "_require_stream_resolver", lambda: None)
    monkeypatch.setattr("bester_ytm.playback.spawn_mpv", lambda *args, **kwargs: process)
    monkeypatch.setattr("bester_ytm.playback.time.sleep", lambda seconds: None)

    with pytest.raises(PlaybackError, match="Playback failed"):
        if seconds:
            controller.play_video("next", seconds=seconds)
        else:
            controller.play_queue()

    assert controller.queue == ["next", "last"]


def test_next_skips_previously_failed_queue_start_once(monkeypatch):
    controller = PlaybackController(queue=["bad", "next", "last"])
    start = Mock(side_effect=[PlaybackError("cannot start"), PlaybackStatus(running=True)])
    monkeypatch.setattr(controller, "play_video", start)
    with pytest.raises(PlaybackError):
        controller.play_queue()
    assert controller.queue == ["bad", "next", "last"]
    assert controller.status().playback_error is not None

    controller.next()

    assert start.call_args_list == [call("bad"), call("next")]
    assert controller.queue == ["last"]


def test_play_queue_retries_failed_head(monkeypatch):
    controller = PlaybackController(queue=["bad", "next"])
    start = Mock(side_effect=[PlaybackError("cannot start"), PlaybackStatus(running=True)])
    monkeypatch.setattr(controller, "play_video", start)
    with pytest.raises(PlaybackError):
        controller.play_queue()

    controller.play_queue()

    assert start.call_args_list == [call("bad"), call("bad")]
    assert controller.queue == ["next"]


def test_next_after_live_failure_preserves_duplicate_queue_item(playing, monkeypatch):
    controller, process, _ = playing
    controller.queue = ["song", "last"]
    process.poll.return_value = 2
    assert controller.status().playback_error is not None
    start = Mock(return_value=PlaybackStatus(running=True))
    monkeypatch.setattr(controller, "play_video", start)

    controller.next()

    start.assert_called_once_with("song")
    assert controller.queue == ["last"]


def test_next_attempts_only_one_track_after_failed_start(monkeypatch):
    controller = PlaybackController(queue=["bad", "also-bad", "last"])
    start = Mock(side_effect=PlaybackError("cannot start"))
    monkeypatch.setattr(controller, "play_video", start)
    with pytest.raises(PlaybackError):
        controller.play_queue()

    with pytest.raises(PlaybackError):
        controller.next()

    assert start.call_args_list == [call("bad"), call("also-bad")]
    assert controller.queue == ["also-bad", "last"]


def test_replacing_queue_clears_failed_head_marker(monkeypatch):
    controller = PlaybackController(queue=["song", "next"])
    start = Mock(side_effect=[PlaybackError("cannot start"), PlaybackStatus(running=True)])
    monkeypatch.setattr(controller, "play_video", start)
    with pytest.raises(PlaybackError):
        controller.play_queue()
    controller.replace_queue(["song", "last"])

    controller.next()

    assert start.call_args_list == [call("song"), call("song")]
    assert controller.queue == ["last"]
