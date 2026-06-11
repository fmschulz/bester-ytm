from __future__ import annotations

import signal
from pathlib import Path

import pytest

from bester_ytm import playback as playback_module
from bester_ytm.mpv_ipc import MpvIpcError
from bester_ytm.playback import PlaybackController, PlaybackError


class RunningProcess:
    def __init__(self) -> None:
        self.signals: list[int] = []
        self.terminated = False

    def poll(self) -> None:
        return None

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0


class DeadProcess:
    returncode = 3

    def poll(self) -> int:
        return 3


class MixingEngine:
    is_mixing = True
    mix_progress = 0.5

    def __init__(self) -> None:
        self.discard_calls = 0
        self.shutdown_calls = 0

    def discard_idle_deck(self) -> None:
        self.discard_calls += 1

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def test_mpv_path_errors_when_binary_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(playback_module.shutil, "which", lambda name: None)

    with pytest.raises(PlaybackError, match="mpv is not installed"):
        PlaybackController()._mpv_path()


def test_require_stream_resolver_errors_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(playback_module.shutil, "which", lambda name: "/usr/bin/mpv")
    assert PlaybackController()._mpv_path() == "/usr/bin/mpv"

    monkeypatch.setattr(playback_module.shutil, "which", lambda name: None)
    with pytest.raises(PlaybackError, match="yt-dlp is not installed"):
        PlaybackController()._require_stream_resolver()


def test_play_video_cleans_up_when_mpv_exits_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[Path] = []
    controller = PlaybackController()
    monkeypatch.setattr(controller, "_mpv_path", lambda: "mpv")
    monkeypatch.setattr(controller, "_require_stream_resolver", lambda: None)
    monkeypatch.setattr(playback_module, "spawn_mpv", lambda *args, **kwargs: DeadProcess())
    monkeypatch.setattr(playback_module, "remove_socket_file", removed.append)
    monkeypatch.setattr("bester_ytm.playback.time.sleep", lambda seconds: None)

    with pytest.raises(PlaybackError, match="exit code 3"):
        controller.play_video("v1")

    assert controller.process is None
    assert controller.current_video_id is None
    assert len(removed) == 2


def test_play_video_with_seconds_stops_after_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = RunningProcess()
    sleeps: list[float] = []
    controller = PlaybackController()
    monkeypatch.setattr(controller, "_mpv_path", lambda: "mpv")
    monkeypatch.setattr(controller, "_require_stream_resolver", lambda: None)
    monkeypatch.setattr(playback_module, "spawn_mpv", lambda *args, **kwargs: process)
    monkeypatch.setattr("bester_ytm.playback.time.sleep", sleeps.append)

    status = controller.play_video("v1", seconds=2)

    assert 2 in sleeps
    assert process.terminated is True
    assert controller.process is None
    assert status.running is False


def test_enqueue_and_replace_queue_manage_state() -> None:
    controller = PlaybackController(
        current_video_id="old", queue=["a"], history=["h"], paused=True
    )

    controller.enqueue(["b", "c"])
    assert controller.queue == ["a", "b", "c"]

    controller.replace_queue(["x"])
    assert controller.queue == ["x"]
    assert controller.current_video_id is None
    assert controller.history == []
    assert controller.paused is False


def test_previous_without_history_reports_current_status() -> None:
    controller = PlaybackController(queue=["v2"])

    status = controller.previous()

    assert status.running is False
    assert controller.queue == ["v2"]


def test_pause_resume_cycles_pause_over_ipc(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = PlaybackController(process=RunningProcess())  # type: ignore[arg-type]
    commands: list[dict[str, object]] = []
    monkeypatch.setattr(controller, "_send_ipc", commands.append)

    status = controller.pause_resume()

    assert commands == [{"command": ["cycle", "pause"]}]
    assert status.paused is True


def test_pause_resume_falls_back_to_process_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = RunningProcess()
    controller = PlaybackController(process=process)  # type: ignore[arg-type]

    def fail_ipc(payload: dict[str, object]) -> None:
        raise PlaybackError("no socket")

    monkeypatch.setattr(controller, "_send_ipc", fail_ipc)

    controller.pause_resume()
    controller.pause_resume()

    assert process.signals == [signal.SIGSTOP, signal.SIGCONT]
    assert controller.paused is False


def test_transport_controls_noop_without_process(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = PlaybackController()
    monkeypatch.setattr(
        controller, "_send_ipc", lambda payload: pytest.fail("must not send IPC")
    )

    assert controller.seek_relative(10).running is False
    assert controller.seek_absolute(5).running is False
    assert controller.toggle_mute().running is False
    assert controller.set_volume(40).running is False
    assert controller.master_volume == 40.0


def test_set_volume_defers_to_fader_while_mixing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = PlaybackController(process=RunningProcess())  # type: ignore[arg-type]
    controller._engine = MixingEngine()  # type: ignore[assignment]
    monkeypatch.setattr(
        controller, "_send_ipc", lambda payload: pytest.fail("fader owns deck volume")
    )

    status = controller.set_volume(40)

    assert controller.master_volume == 40.0
    assert status.volume == 40.0
    assert status.mix_progress == 0.5


def test_mirror_mute_returns_without_engine() -> None:
    controller = PlaybackController()

    controller._mirror_mute_to_draining_deck()


def test_ipc_helpers_require_configured_socket() -> None:
    controller = PlaybackController()

    with pytest.raises(PlaybackError, match="socket is not configured"):
        controller._send_ipc({"command": ["stop"]})


def test_ipc_helpers_translate_mpv_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeClient:
        def __init__(self, socket_path: Path) -> None:
            self.socket_path = socket_path

        def request(
            self, payload: dict[str, object], deadline_seconds: float = 2.0
        ) -> dict[str, object]:
            if payload == {"command": ["get_property", "mute"]}:
                return {"error": "success", "data": True}
            raise MpvIpcError("boom")

    monkeypatch.setattr(
        playback_module,
        "MpvIpcClient",
        lambda socket_path: FakeClient(socket_path),
    )
    controller = PlaybackController(ipc_socket=tmp_path / "mpv.sock")

    assert controller._get_property("mute") is True
    with pytest.raises(PlaybackError, match="boom"):
        controller._send_ipc({"command": ["stop"]})


def test_stop_terminates_process_and_removes_socket(tmp_path: Path) -> None:
    process = RunningProcess()
    ipc_socket = tmp_path / "mpv.sock"
    ipc_socket.write_text("", encoding="utf-8")
    controller = PlaybackController(
        process=process,  # type: ignore[arg-type]
        ipc_socket=ipc_socket,
        paused=True,
    )
    engine = MixingEngine()
    controller._engine = engine  # type: ignore[assignment]

    controller.stop()

    assert process.terminated is True
    assert controller.process is None
    assert not ipc_socket.exists()
    assert controller.paused is False
    assert engine.shutdown_calls == 1


def test_status_reads_live_properties_over_ipc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeLiveClient:
        def get_float(self, name: str, deadline_seconds: float = 2.0) -> float:
            return {"time-pos": 12.0, "duration": 60.0, "volume": 80.0}[name]

        def get_property(self, name: str, deadline_seconds: float = 2.0) -> bool:
            return {"mute": False, "pause": True}[name]

    controller = PlaybackController(
        process=RunningProcess(),  # type: ignore[arg-type]
        current_video_id="v1",
        ipc_socket=tmp_path / "mpv.sock",
    )
    monkeypatch.setattr(controller, "_live_client", FakeLiveClient)

    status = controller.status()

    assert status.position_seconds == 12.0
    assert status.duration_seconds == 60.0
    assert status.volume == 80.0
    assert status.paused is True
    assert controller.paused is True


def test_status_tolerates_ipc_failure_mid_teardown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FailingClient:
        def get_float(self, name: str, deadline_seconds: float = 2.0) -> float:
            raise MpvIpcError("deck mid-teardown")

        def get_property(self, name: str, deadline_seconds: float = 2.0) -> bool:
            raise MpvIpcError("deck mid-teardown")

    controller = PlaybackController(
        process=RunningProcess(),  # type: ignore[arg-type]
        current_video_id="v1",
        ipc_socket=tmp_path / "mpv.sock",
    )
    monkeypatch.setattr(controller, "_live_client", FailingClient)

    status = controller.status()

    assert status.running is True
    assert status.position_seconds is None
    assert status.current_video_id == "v1"
