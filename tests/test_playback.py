import subprocess

import pytest

from bester_ytm.playback import PlaybackController, PlaybackError, PlaybackStatus


def test_play_queue_removes_track_only_after_success(monkeypatch) -> None:
    controller = PlaybackController(current_video_id="old", queue=["v1", "v2"])

    def fake_play_video(video_id: str, seconds: int | None = None) -> PlaybackStatus:
        controller.current_video_id = video_id
        return PlaybackStatus(running=True, current_video_id=video_id, queue_size=2)

    monkeypatch.setattr(controller, "play_video", fake_play_video)

    status = controller.play_queue()

    assert status.current_video_id == "v1"
    assert controller.queue == ["v2"]
    assert controller.history == ["old"]


def test_play_queue_keeps_queue_when_start_fails(monkeypatch) -> None:
    controller = PlaybackController(current_video_id="old", queue=["v1", "v2"])

    def fake_play_video(video_id: str, seconds: int | None = None) -> PlaybackStatus:
        raise PlaybackError("mpv failed")

    monkeypatch.setattr(controller, "play_video", fake_play_video)

    with pytest.raises(PlaybackError):
        controller.play_queue()

    assert controller.queue == ["v1", "v2"]
    assert controller.history == []


def test_previous_mutates_history_and_queue_only_after_success(monkeypatch) -> None:
    controller = PlaybackController(
        current_video_id="current",
        queue=["queued"],
        history=["previous"],
    )

    def fake_play_video(video_id: str, seconds: int | None = None) -> PlaybackStatus:
        controller.current_video_id = video_id
        return PlaybackStatus(running=True, current_video_id=video_id, queue_size=1)

    monkeypatch.setattr(controller, "play_video", fake_play_video)

    status = controller.previous()

    assert status.current_video_id == "previous"
    assert controller.current_video_id == "previous"
    assert controller.history == []
    assert controller.queue == ["current", "queued"]


def test_previous_keeps_history_and_queue_when_start_fails(monkeypatch) -> None:
    controller = PlaybackController(
        current_video_id="current",
        queue=["queued"],
        history=["previous"],
    )

    def fake_play_video(video_id: str, seconds: int | None = None) -> PlaybackStatus:
        raise PlaybackError("mpv failed")

    monkeypatch.setattr(controller, "play_video", fake_play_video)

    with pytest.raises(PlaybackError):
        controller.previous()

    assert controller.current_video_id == "current"
    assert controller.history == ["previous"]
    assert controller.queue == ["queued"]


def test_stop_clears_paused_state() -> None:
    controller = PlaybackController(paused=True)

    controller.stop()

    assert controller.paused is False


def test_play_video_silences_mpv_terminal(monkeypatch) -> None:
    calls = []

    class FakeProcess:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return FakeProcess()

    controller = PlaybackController()
    monkeypatch.setattr(controller, "_mpv_path", lambda: "mpv")
    monkeypatch.setattr(controller, "_require_stream_resolver", lambda: None)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("bester_ytm.playback.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        controller,
        "status",
        lambda: PlaybackStatus(running=True, current_video_id=controller.current_video_id),
    )

    status = controller.play_video("v1")

    cmd, kwargs = calls[0]
    assert status.current_video_id == "v1"
    assert "--no-terminal" in cmd
    assert "--input-terminal=no" in cmd
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL


class RunningProcess:
    def poll(self) -> None:
        return None


def test_seek_controls_send_mpv_ipc(monkeypatch) -> None:
    controller = PlaybackController(process=RunningProcess())  # type: ignore[arg-type]
    commands: list[dict[str, object]] = []

    monkeypatch.setattr(controller, "_send_ipc", commands.append)
    monkeypatch.setattr(
        controller,
        "status",
        lambda: PlaybackStatus(running=True, current_video_id="v1"),
    )

    controller.seek_relative(10)
    controller.seek_absolute(-5)

    assert commands == [
        {"command": ["seek", 10, "relative"]},
        {"command": ["seek", 0.0, "absolute"]},
    ]


def test_volume_controls_clamp_and_toggle_mute(monkeypatch) -> None:
    controller = PlaybackController(process=RunningProcess())  # type: ignore[arg-type]
    commands: list[dict[str, object]] = []
    statuses = [
        PlaybackStatus(running=True, current_video_id="v1", volume=98),
        PlaybackStatus(running=True, current_video_id="v1", volume=100),
        PlaybackStatus(running=True, current_video_id="v1", volume=0),
        PlaybackStatus(running=True, current_video_id="v1", muted=True),
    ]

    monkeypatch.setattr(controller, "_send_ipc", commands.append)
    monkeypatch.setattr(controller, "status", lambda: statuses.pop(0))

    controller.change_volume(10)
    controller.set_volume(-20)
    controller.toggle_mute()

    assert commands == [
        {"command": ["set_property", "volume", 100.0]},
        {"command": ["set_property", "volume", 0.0]},
        {"command": ["cycle", "mute"]},
    ]
