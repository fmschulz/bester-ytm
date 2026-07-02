import subprocess
import time
from pathlib import Path

import pytest

import bester_ytm.transitions as transitions
from bester_ytm.deck import (
    KILL_ESCALATION_SECONDS,
    Deck,
    DeckReaper,
    DeckState,
    spawn_prebuffer_deck,
)
from bester_ytm.mpv_ipc import MpvIpcError
from bester_ytm.playback import PlaybackError
from bester_ytm.transitions import (
    TransitionEngine,
    TransitionSettings,
    TransitionStyle,
)


class FakeProcess:
    def __init__(self, exit_code: int | None = None) -> None:
        self.exit_code = exit_code
        self.terminated = False

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True
        self.exit_code = 0

    def kill(self) -> None:
        self.exit_code = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.exit_code if self.exit_code is not None else 0


class StubbornProcess(FakeProcess):
    """Stays alive through terminate/kill; blocking wait() is forbidden."""

    def __init__(self) -> None:
        super().__init__()
        self.kill_calls = 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.kill_calls += 1

    def wait(self, timeout: float | None = None) -> int:
        raise AssertionError("the tick path must never wait on a dying deck")


class SlowExitProcess(FakeProcess):
    """Ignores terminate; exits only when a blocking wait() reaps it."""

    def __init__(self) -> None:
        super().__init__()
        self.wait_calls = 0

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        self.exit_code = 0
        return 0


class FakeDeck:
    def __init__(self, name: str, video_id: str, ready: bool = False) -> None:
        self.name = name
        self.video_id = video_id
        self.state = DeckState.READY if ready else DeckState.LOADING
        self.process = FakeProcess()
        self.ipc_socket = Path(f"/tmp/fake-deck-{name.lower()}.sock")
        self.calls: list[tuple[str, object]] = []
        self.readiness_results: list[bool] = []
        self.fail_on: str | None = None

    def is_process_running(self) -> bool:
        return self.process.poll() is None

    def refresh_readiness(self) -> bool:
        is_ready = self.readiness_results.pop(0) if self.readiness_results else False
        if is_ready:
            self.state = DeckState.READY
        return is_ready

    def set_volume(self, volume: float, deadline_seconds: float = 2.0) -> None:
        self._record("set_volume", volume)

    def set_paused(self, paused: bool, deadline_seconds: float = 2.0) -> None:
        self._record("set_paused", paused)

    def set_muted(self, muted: bool, deadline_seconds: float = 2.0) -> None:
        self._record("set_muted", muted)

    def _record(self, operation: str, value: object) -> None:
        if self.fail_on == operation:
            raise MpvIpcError(f"{operation} failed")
        self.calls.append((operation, value))


class FakeFader:
    def __init__(self, duration_seconds, apply_gains, get_master_volume) -> None:
        self.duration_seconds = duration_seconds
        self.apply_gains = apply_gains
        self.get_master_volume = get_master_volume
        self.started = False
        self.cancelled = False
        self.failure_reason: str | None = None
        self._active = True
        self._progress = 0.0

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def progress(self) -> float:
        return self._progress

    def start(self) -> None:
        self.started = True

    def cancel(self, join_timeout_seconds: float = 1.0) -> None:
        self.cancelled = True
        self._active = False


class FakeHost:
    def __init__(self) -> None:
        self.process = FakeProcess()
        self.ipc_socket = Path("/tmp/fake-live.sock")
        self.current_video_id = "v1"
        self.queue = ["v2", "v3"]
        self.history: list[str] = []
        self.paused = False
        self.master_volume = 100.0
        self.active_deck = "A"
        self.transition = TransitionSettings(
            style=TransitionStyle.CROSSFADE, fade_seconds=6.0
        )
        self.last_transition_error: str | None = None

    def _mpv_path(self) -> str:
        return "/usr/bin/mpv"


class EngineHarness:
    def __init__(self, monkeypatch) -> None:
        self.host = FakeHost()
        self.engine = TransitionEngine(self.host)
        self.timing: tuple[float, float] | None = (100.0, 240.0)
        self.live_muted = False
        self.restored_volumes: list[float] = []
        self.spawned: list[tuple[str, str, str]] = []
        self.spawn_error: Exception | None = None
        monkeypatch.setattr(self.engine, "_read_live_timing", lambda: self.timing)
        monkeypatch.setattr(self.engine, "_read_live_muted", lambda: self.live_muted)
        monkeypatch.setattr(
            self.engine,
            "_restore_live_volume",
            lambda: self.restored_volumes.append(self.host.master_volume),
        )
        monkeypatch.setattr(transitions, "Fader", FakeFader)
        monkeypatch.setattr(transitions, "spawn_prebuffer_deck", self._spawn)

    def _spawn(self, name: str, video_id: str, mpv_path: str) -> FakeDeck:
        self.spawned.append((name, video_id, mpv_path))
        if self.spawn_error is not None:
            raise self.spawn_error
        return FakeDeck(name, video_id)


def test_transition_settings_clamped_bounds_fade() -> None:
    assert TransitionSettings(fade_seconds=0.2).clamped().fade_seconds == 1.0
    assert TransitionSettings(fade_seconds=99.0).clamped().fade_seconds == 15.0
    kept = TransitionSettings(style=TransitionStyle.CROSSFADE, fade_seconds=8.0).clamped()
    assert kept.fade_seconds == 8.0
    assert kept.style is TransitionStyle.CROSSFADE


def test_tick_spawns_prebuffer_only_inside_window(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    harness.timing = (200.0, 240.0)

    harness.engine.tick()

    assert harness.spawned == []
    assert harness.engine.idle_deck is None

    harness.timing = (223.0, 240.0)
    harness.engine.tick()

    assert harness.spawned == [("B", "v2", "/usr/bin/mpv")]
    assert harness.engine.idle_deck is not None


def test_tick_records_spawn_failure_and_keeps_playing(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    harness.spawn_error = MpvIpcError("failed to spawn mpv deck B: boom")
    harness.timing = (230.0, 240.0)

    harness.engine.tick()

    assert harness.engine.idle_deck is None
    assert harness.host.last_transition_error == "failed to spawn mpv deck B: boom"


@pytest.mark.parametrize(
    "spawn_error",
    [
        PlaybackError("mpv is not installed or not on PATH"),
        PermissionError("stale socket owned by another user"),
    ],
)
def test_tick_records_non_ipc_spawn_failures_without_crashing(
    monkeypatch, spawn_error: Exception
) -> None:
    harness = EngineHarness(monkeypatch)
    harness.spawn_error = spawn_error
    harness.timing = (230.0, 240.0)

    harness.engine.tick()

    assert harness.engine.idle_deck is None
    assert harness.host.last_transition_error == str(spawn_error)


def test_idle_deck_respawn_is_rate_limited_per_video(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    now = {"value": 1000.0}
    monkeypatch.setattr(transitions.time, "monotonic", lambda: now["value"])
    harness.timing = (230.0, 240.0)

    harness.engine.tick()
    assert [video for _, video, _ in harness.spawned] == ["v2"]

    # The freshly spawned deck dies immediately; ticks inside the backoff
    # window must not respawn the same video.
    harness.engine.idle_deck.process.exit_code = 1
    harness.engine.tick()
    harness.engine.tick()
    assert [video for _, video, _ in harness.spawned] == ["v2"]
    assert harness.engine.idle_deck is None

    # The same video is retried once the backoff window has passed.
    now["value"] += transitions.SPAWN_RETRY_SECONDS
    harness.engine.tick()
    assert [video for _, video, _ in harness.spawned] == ["v2", "v2"]

    # A different queue head spawns immediately.
    harness.engine.idle_deck.process.exit_code = 1
    harness.host.queue = ["z9", "v3"]
    harness.engine.tick()
    assert [video for _, video, _ in harness.spawned] == ["v2", "v2", "z9"]


def test_tick_discards_idle_deck_after_queue_reassignment(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    stale_deck = FakeDeck("B", "v2", ready=True)
    harness.engine.idle_deck = stale_deck
    harness.host.queue = ["z1", "z2"]
    harness.timing = (230.0, 240.0)

    harness.engine.tick()

    assert stale_deck.state is DeckState.STOPPED
    assert stale_deck.process.terminated
    assert harness.spawned == [("B", "z1", "/usr/bin/mpv")]


def test_tick_discards_idle_deck_whose_process_died(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    dead_deck = FakeDeck("B", "v2", ready=True)
    dead_deck.process.exit_code = 1
    harness.engine.idle_deck = dead_deck
    harness.timing = (230.0, 240.0)

    harness.engine.tick()

    assert dead_deck.state is DeckState.STOPPED
    assert harness.engine.idle_deck is not dead_deck


def test_tick_polls_loading_deck_readiness(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    loading_deck = FakeDeck("B", "v2")
    loading_deck.readiness_results = [False, True]
    harness.engine.idle_deck = loading_deck
    harness.timing = (230.0, 240.0)

    harness.engine.tick()
    assert loading_deck.state is DeckState.LOADING

    harness.engine.tick()
    assert loading_deck.state is DeckState.READY


def test_tick_discards_loading_deck_when_track_nearly_over(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    loading_deck = FakeDeck("B", "v2")
    harness.engine.idle_deck = loading_deck
    harness.timing = (239.7, 240.0)

    harness.engine.tick()

    assert loading_deck.state is DeckState.STOPPED
    assert harness.engine.fader is None


def test_tick_promotes_ready_deck_inside_fade_window(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    incoming = FakeDeck("B", "v2", ready=True)
    harness.engine.idle_deck = incoming
    old_process = harness.host.process
    harness.timing = (236.0, 240.0)

    harness.engine.tick()

    assert harness.host.queue == ["v3"]
    assert harness.host.history == ["v1"]
    assert harness.host.current_video_id == "v2"
    assert harness.host.process is incoming.process
    assert harness.host.ipc_socket == incoming.ipc_socket
    assert harness.host.active_deck == "B"
    assert harness.host.paused is False
    assert incoming.state is DeckState.LIVE
    assert incoming.calls == [("set_volume", 0.0), ("set_paused", False)]
    assert harness.engine.idle_deck is None
    draining = harness.engine.draining_deck
    assert draining is not None
    assert draining.process is old_process
    assert draining.state is DeckState.DRAINING
    fader = harness.engine.fader
    assert isinstance(fader, FakeFader)
    assert fader.started
    assert fader.duration_seconds == pytest.approx(4.0)
    assert harness.engine.is_mixing
    assert harness.engine.mix_progress == 0.0


def test_promotion_copies_mute_onto_incoming_deck(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    harness.live_muted = True
    incoming = FakeDeck("B", "v2", ready=True)
    harness.engine.idle_deck = incoming
    harness.timing = (236.0, 240.0)

    harness.engine.tick()

    assert incoming.calls == [
        ("set_volume", 0.0),
        ("set_muted", True),
        ("set_paused", False),
    ]


def test_short_track_clamps_effective_fade(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    incoming = FakeDeck("B", "v2", ready=True)
    harness.engine.idle_deck = incoming
    harness.timing = (7.0, 12.0)

    harness.engine.tick()
    assert harness.engine.fader is None

    harness.timing = (8.5, 12.0)
    harness.engine.tick()

    fader = harness.engine.fader
    assert fader is not None
    assert fader.duration_seconds == pytest.approx(3.5)


def test_late_ready_deck_uses_short_mix(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    incoming = FakeDeck("B", "v2", ready=True)
    harness.engine.idle_deck = incoming
    harness.timing = (239.6, 240.0)

    harness.engine.tick()

    fader = harness.engine.fader
    assert fader is not None
    assert fader.duration_seconds == pytest.approx(0.5)


def test_tick_does_not_trigger_while_paused(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    harness.host.paused = True
    incoming = FakeDeck("B", "v2", ready=True)
    harness.engine.idle_deck = incoming
    harness.timing = (236.0, 240.0)

    harness.engine.tick()

    assert harness.engine.fader is None
    assert incoming.state is DeckState.READY
    assert harness.host.queue == ["v2", "v3"]


def test_tick_never_advances_when_live_process_is_dead(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    harness.host.process.exit_code = 0
    incoming = FakeDeck("B", "v2", ready=True)
    harness.engine.idle_deck = incoming
    timing_reads: list[int] = []
    monkeypatch.setattr(
        harness.engine,
        "_read_live_timing",
        lambda: timing_reads.append(1) or (239.0, 240.0),
    )

    harness.engine.tick()

    assert harness.host.queue == ["v2", "v3"]
    assert harness.host.current_video_id == "v1"
    assert harness.engine.fader is None
    assert timing_reads == []


def test_tick_without_timing_does_nothing(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    harness.timing = None

    harness.engine.tick()

    assert harness.spawned == []
    assert harness.engine.fader is None


def test_tick_discards_idle_deck_when_queue_empty(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    idle = FakeDeck("B", "v2", ready=True)
    harness.engine.idle_deck = idle
    harness.host.queue = []

    harness.engine.tick()

    assert idle.state is DeckState.STOPPED
    assert harness.engine.idle_deck is None


def test_tick_discards_idle_deck_when_style_is_cut(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    idle = FakeDeck("B", "v2", ready=True)
    harness.engine.idle_deck = idle
    harness.host.transition = TransitionSettings(style=TransitionStyle.CUT)

    harness.engine.tick()

    assert idle.state is DeckState.STOPPED
    assert harness.engine.idle_deck is None


def test_tick_waits_while_fader_is_active(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    fader = FakeFader(4.0, lambda outgoing, incoming: None, lambda: 100.0)
    harness.engine.fader = fader

    harness.engine.tick()

    assert harness.engine.fader is fader
    assert harness.spawned == []


def test_tick_finalizes_completed_fade(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    fader = FakeFader(4.0, lambda outgoing, incoming: None, lambda: 100.0)
    fader._active = False
    harness.engine.fader = fader
    draining = FakeDeck("A", "v1")
    draining.state = DeckState.DRAINING
    harness.engine.draining_deck = draining

    harness.engine.tick()

    assert draining.state is DeckState.STOPPED
    assert draining.process.terminated
    assert harness.engine.fader is None
    assert harness.engine.draining_deck is None
    assert harness.restored_volumes == [100.0]
    assert harness.host.last_transition_error is None


def test_tick_finalize_records_fader_failure_and_still_restores_volume(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    fader = FakeFader(4.0, lambda outgoing, incoming: None, lambda: 100.0)
    fader._active = False
    fader.failure_reason = "incoming deck died"
    harness.engine.fader = fader
    harness.engine.draining_deck = FakeDeck("A", "v1")

    harness.engine.tick()

    assert harness.host.last_transition_error == "incoming deck died"
    # The live deck may be stuck at a mid-ramp volume; always restore it.
    assert harness.restored_volumes == [100.0]


def test_restore_live_volume_keeps_existing_error(monkeypatch) -> None:
    host = FakeHost()
    engine = TransitionEngine(host)

    class FailingClient:
        def __init__(self, socket_path: Path) -> None:
            self.socket_path = socket_path

        def send(self, payload: dict[str, object], deadline_seconds: float) -> None:
            raise MpvIpcError("volume restore timed out")

    monkeypatch.setattr(transitions, "MpvIpcClient", FailingClient)

    host.last_transition_error = "fader failed first"
    engine._restore_live_volume()
    assert host.last_transition_error == "fader failed first"

    host.last_transition_error = None
    engine._restore_live_volume()
    assert host.last_transition_error == "volume restore timed out"


def test_begin_crossfade_aborts_on_queue_mismatch(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    stale = FakeDeck("B", "stale", ready=True)
    harness.engine.idle_deck = stale

    assert harness.engine.begin_crossfade(4.0) is False
    assert stale.state is DeckState.STOPPED
    assert harness.engine.idle_deck is None
    assert harness.host.queue == ["v2", "v3"]
    assert harness.host.current_video_id == "v1"


def test_begin_crossfade_aborts_without_host_mutation_when_unpause_fails(
    monkeypatch,
) -> None:
    harness = EngineHarness(monkeypatch)
    incoming = FakeDeck("B", "v2", ready=True)
    incoming.fail_on = "set_paused"
    harness.engine.idle_deck = incoming

    assert harness.engine.begin_crossfade(4.0) is False
    assert harness.host.queue == ["v2", "v3"]
    assert harness.host.history == []
    assert harness.host.current_video_id == "v1"
    assert harness.host.process is not incoming.process
    assert harness.host.last_transition_error is not None
    assert incoming.state is DeckState.STOPPED
    assert harness.engine.fader is None


def test_snap_cancels_fader_and_finalizes(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    fader = FakeFader(4.0, lambda outgoing, incoming: None, lambda: 100.0)
    harness.engine.fader = fader
    draining = FakeDeck("A", "v1")
    harness.engine.draining_deck = draining

    harness.engine.snap()

    assert fader.cancelled
    assert harness.engine.fader is None
    assert draining.state is DeckState.STOPPED
    assert harness.restored_volumes == [100.0]


def test_snap_extends_join_until_fader_thread_is_done(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    fader = FakeFader(4.0, lambda outgoing, incoming: None, lambda: 100.0)
    cancel_timeouts: list[float] = []

    def lagging_cancel(join_timeout_seconds: float = 1.0) -> None:
        cancel_timeouts.append(join_timeout_seconds)
        if len(cancel_timeouts) > 1:
            fader._active = False

    fader.cancel = lagging_cancel  # type: ignore[method-assign]
    harness.engine.fader = fader

    harness.engine.snap()

    assert cancel_timeouts == [1.0, transitions.SNAP_EXTRA_JOIN_SECONDS]
    assert harness.engine.fader is None
    assert harness.restored_volumes == [100.0]


def test_snap_without_mix_is_noop(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)

    harness.engine.snap()

    assert harness.engine.fader is None
    assert harness.restored_volumes == []


def test_can_quick_mix_requires_ready_matching_deck(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    incoming = FakeDeck("B", "v2", ready=True)
    harness.engine.idle_deck = incoming

    assert harness.engine.can_quick_mix("v2") is True
    assert harness.engine.can_quick_mix("v3") is False

    incoming.state = DeckState.LOADING
    assert harness.engine.can_quick_mix("v2") is False
    incoming.state = DeckState.READY

    harness.host.transition = TransitionSettings(style=TransitionStyle.CUT)
    assert harness.engine.can_quick_mix("v2") is False
    harness.host.transition = TransitionSettings(style=TransitionStyle.CROSSFADE)

    harness.engine.fader = FakeFader(4.0, lambda outgoing, incoming: None, lambda: 100.0)
    assert harness.engine.can_quick_mix("v2") is False
    harness.engine.fader = None

    harness.host.process.exit_code = 0
    assert harness.engine.can_quick_mix("v2") is False


def test_mirror_mute_reaches_draining_deck_and_tolerates_errors(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    draining = FakeDeck("A", "v1")
    harness.engine.draining_deck = draining

    harness.engine.mirror_mute_to_draining(True)
    assert draining.calls == []

    harness.engine.fader = FakeFader(4.0, lambda outgoing, incoming: None, lambda: 100.0)
    harness.engine.mirror_mute_to_draining(True)
    assert draining.calls == [("set_muted", True)]

    draining.fail_on = "set_muted"
    harness.engine.mirror_mute_to_draining(False)
    assert draining.calls == [("set_muted", True)]


def test_shutdown_snaps_and_discards_idle_deck(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    fader = FakeFader(4.0, lambda outgoing, incoming: None, lambda: 100.0)
    harness.engine.fader = fader
    idle = FakeDeck("B", "v2", ready=True)
    harness.engine.idle_deck = idle

    harness.engine.shutdown()

    assert fader.cancelled
    assert harness.engine.fader is None
    assert idle.state is DeckState.STOPPED
    assert harness.engine.idle_deck is None
    assert harness.engine.reaper.dying == []


def test_spawn_prebuffer_deck_command_and_socket(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    deck = spawn_prebuffer_deck("B", "vid123", "/usr/bin/mpv")

    cmd, kwargs = calls[0]
    assert cmd[0] == "/usr/bin/mpv"
    assert "--pause=yes" in cmd
    assert "--volume=0" in cmd
    assert "--no-video" in cmd
    assert "--ytdl-format=bestaudio" in cmd
    assert cmd[-1] == "https://music.youtube.com/watch?v=vid123"
    assert any(
        arg.startswith("--input-ipc-server=") and "deck-b" in arg for arg in cmd
    )
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert deck.name == "B"
    assert deck.video_id == "vid123"
    assert deck.state is DeckState.LOADING


def test_spawn_prebuffer_deck_wraps_spawn_failure(monkeypatch) -> None:
    def failing_popen(cmd, **kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(subprocess, "Popen", failing_popen)

    with pytest.raises(MpvIpcError, match="failed to spawn mpv deck B"):
        spawn_prebuffer_deck("B", "vid123", "/usr/bin/mpv")


class FakeProbeClient:
    def __init__(self, values: list[float | None]) -> None:
        self.values = values

    def get_float(self, name: str, deadline_seconds: float = 2.0) -> float | None:
        value = self.values.pop(0)
        if value == -1.0:
            raise MpvIpcError("probe failed")
        return value


def test_deck_refresh_readiness_requires_socket_and_duration(tmp_path) -> None:
    socket_path = tmp_path / "deck.sock"
    deck = Deck(
        name="A", video_id="v", process=FakeProcess(), ipc_socket=socket_path
    )

    assert deck.refresh_readiness() is False

    socket_path.touch()
    deck.client = FakeProbeClient([None, -1.0, 200.0])

    assert deck.refresh_readiness() is False
    assert deck.refresh_readiness() is False
    assert deck.refresh_readiness() is True
    assert deck.state is DeckState.READY
    assert deck.refresh_readiness() is True


def test_deck_stop_terminates_running_process_and_unlinks_socket(tmp_path) -> None:
    socket_path = tmp_path / "deck.sock"
    socket_path.touch()
    process = FakeProcess()
    deck = Deck(name="A", video_id="v", process=process, ipc_socket=socket_path)

    deck.stop()

    assert process.terminated
    assert deck.state is DeckState.STOPPED
    assert not socket_path.exists()


def test_deck_stop_tolerates_dead_process(tmp_path) -> None:
    process = FakeProcess(exit_code=0)
    deck = Deck(
        name="A", video_id="v", process=process, ipc_socket=tmp_path / "deck.sock"
    )

    deck.stop()

    assert not process.terminated
    assert deck.state is DeckState.STOPPED


def make_stubborn_deck(tmp_path: Path, name: str = "A") -> Deck:
    socket_path = tmp_path / f"deck-{name.lower()}.sock"
    socket_path.touch()
    return Deck(
        name=name, video_id="v", process=StubbornProcess(), ipc_socket=socket_path
    )


def test_reaper_retire_never_waits_and_frees_socket_immediately(tmp_path) -> None:
    deck = make_stubborn_deck(tmp_path)
    reaper = DeckReaper(clock=lambda: 0.0)

    reaper.retire(deck)

    assert deck.process.terminated
    assert deck.state is DeckState.STOPPED
    assert not deck.ipc_socket.exists()
    assert len(reaper.dying) == 1


def test_reaper_retire_skips_already_dead_process(tmp_path) -> None:
    process = FakeProcess(exit_code=0)
    deck = Deck(name="A", video_id="v", process=process, ipc_socket=tmp_path / "s.sock")
    reaper = DeckReaper(clock=lambda: 0.0)

    reaper.retire(deck)

    assert not process.terminated
    assert deck.state is DeckState.STOPPED
    assert reaper.dying == []


def test_reaper_reap_drops_deck_once_process_exits(tmp_path) -> None:
    deck = make_stubborn_deck(tmp_path)
    reaper = DeckReaper(clock=lambda: 0.0)
    reaper.retire(deck)

    reaper.reap()
    assert len(reaper.dying) == 1

    deck.process.exit_code = 0
    reaper.reap()
    assert reaper.dying == []
    assert deck.process.kill_calls == 0


def test_reaper_escalates_to_kill_once_after_grace_period(tmp_path) -> None:
    deck = make_stubborn_deck(tmp_path)
    now = {"value": 100.0}
    reaper = DeckReaper(clock=lambda: now["value"])
    reaper.retire(deck)

    now["value"] += KILL_ESCALATION_SECONDS - 0.1
    reaper.reap()
    assert deck.process.kill_calls == 0

    now["value"] += 0.2
    reaper.reap()
    reaper.reap()
    assert deck.process.kill_calls == 1
    assert len(reaper.dying) == 1

    deck.process.exit_code = -9
    reaper.reap()
    assert reaper.dying == []


def test_tick_returns_quickly_while_draining_deck_is_still_dying(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    fader = FakeFader(4.0, lambda outgoing, incoming: None, lambda: 100.0)
    fader._active = False
    harness.engine.fader = fader
    draining = FakeDeck("A", "v1")
    draining.process = StubbornProcess()
    harness.engine.draining_deck = draining

    started = time.perf_counter()
    harness.engine.tick()  # finalizes the fade; StubbornProcess.wait would raise
    harness.engine.tick()  # keeps ticking while the deck is still dying
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert draining.state is DeckState.STOPPED
    assert draining.process.terminated
    assert len(harness.engine.reaper.dying) == 1
    assert harness.engine.fader is None
    assert harness.engine.draining_deck is None


def test_snap_retires_draining_deck_without_waiting(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    fader = FakeFader(4.0, lambda outgoing, incoming: None, lambda: 100.0)
    harness.engine.fader = fader
    draining = FakeDeck("A", "v1")
    draining.process = StubbornProcess()
    harness.engine.draining_deck = draining

    harness.engine.snap()

    assert draining.state is DeckState.STOPPED
    assert draining.process.terminated
    assert len(harness.engine.reaper.dying) == 1


def test_shutdown_flushes_dying_decks_with_blocking_reap(monkeypatch) -> None:
    harness = EngineHarness(monkeypatch)
    lingering = FakeDeck("A", "v1")
    lingering.process = SlowExitProcess()
    harness.engine.reaper.retire(lingering)

    harness.engine.shutdown()

    assert lingering.process.wait_calls == 1
    assert lingering.process.poll() is not None
    assert harness.engine.reaper.dying == []
