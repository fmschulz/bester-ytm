from pathlib import Path

from typer.testing import CliRunner

from bester_ytm import cli_play
from bester_ytm.cli import app
from bester_ytm.cli_play import _effective_transition_settings, _play_and_wait
from bester_ytm.transitions import (
    DEFAULT_APP_SETTINGS,
    TransitionSettings,
    TransitionStyle,
)


class FakeProcess:
    def __init__(self, controller: "FakeController") -> None:
        self.controller = controller

    def wait(self) -> None:
        self.controller.waits += 1


class FakeController:
    transition = TransitionSettings()

    def __init__(self) -> None:
        self.queue = ["second", "third"]
        self.process = FakeProcess(self)
        self.waits = 0
        self.next_calls = 0
        self.stop_calls = 0

    def next(self) -> None:
        self.next_calls += 1
        self.queue.pop(0)
        self.process = FakeProcess(self)

    def stop(self) -> None:
        self.stop_calls += 1
        self.process = None


def test_play_and_wait_advances_playlist_queue_and_stops_controller() -> None:
    controller = FakeController()

    _play_and_wait(controller, seconds=None)  # type: ignore[arg-type]

    assert controller.waits == 3
    assert controller.next_calls == 2
    assert controller.queue == []
    assert controller.stop_calls == 1


class PollingProcess:
    def __init__(self, polls: list[int | None]) -> None:
        self.polls = polls

    def poll(self) -> int | None:
        return self.polls.pop(0) if self.polls else 0


class CrossfadeController:
    transition = TransitionSettings(style=TransitionStyle.CROSSFADE, fade_seconds=6.0)

    def __init__(self) -> None:
        self.queue = ["second"]
        self.process: PollingProcess | None = PollingProcess([None, None, 0])
        self.tick_calls = 0
        self.next_calls = 0
        self.stop_calls = 0
        self.transition_errors: list[str | None] = []

    def tick(self) -> None:
        self.tick_calls += 1

    def consume_transition_error(self) -> str | None:
        return self.transition_errors.pop(0) if self.transition_errors else None

    def next(self) -> None:
        self.next_calls += 1
        self.queue.pop(0)
        self.process = PollingProcess([0])

    def stop(self) -> None:
        self.stop_calls += 1
        self.process = None


def test_play_and_wait_ticks_crossfade_and_falls_back_to_cut(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(cli_play.time, "sleep", lambda seconds: sleeps.append(seconds))
    controller = CrossfadeController()

    _play_and_wait(controller, seconds=None)  # type: ignore[arg-type]

    assert controller.tick_calls == 4
    assert controller.next_calls == 1
    assert controller.queue == []
    assert sleeps == [0.5, 0.5, 0.5]
    assert controller.stop_calls == 1


def test_play_and_wait_reports_transition_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_play.time, "sleep", lambda seconds: None)
    controller = CrossfadeController()
    controller.transition_errors = ["deck B died"]

    _play_and_wait(controller, seconds=None)  # type: ignore[arg-type]

    assert "Mix failed; using cut: deck B died" in capsys.readouterr().out


def test_effective_transition_settings_flags_override_config(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert _effective_transition_settings(None, None) == DEFAULT_APP_SETTINGS
    assert _effective_transition_settings(TransitionStyle.CUT, 9.0) == TransitionSettings(
        style=TransitionStyle.CUT, fade_seconds=9.0
    )
    assert _effective_transition_settings(None, 8.0) == TransitionSettings(
        style=TransitionStyle.CROSSFADE, fade_seconds=8.0
    )


def test_play_playlist_constructs_controller_with_transition_flags(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    class Snapshot:
        video_ids = ["v1", "v2"]

    class FakeClient:
        def __init__(self, authenticated: bool = True) -> None:
            self.authenticated = authenticated

        def get_playlist(self, playlist_id: str) -> Snapshot:
            return Snapshot()

    created: list[object] = []

    class FakePlaybackController:
        def __init__(self, transition: TransitionSettings | None = None) -> None:
            self.transition = transition
            self.process = None
            self.queue: list[str] = []
            created.append(self)

        def enqueue(self, video_ids: list[str]) -> None:
            self.queue.extend(video_ids)

        def play_queue(self) -> None:
            self.queue.pop(0)

        def stop(self) -> None:
            self.process = None

    monkeypatch.setattr(cli_play, "YTMClient", FakeClient)
    monkeypatch.setattr(cli_play, "PlaybackController", FakePlaybackController)

    result = CliRunner().invoke(
        app, ["play", "playlist", "PL1", "--transition", "cut", "--fade", "8"]
    )

    assert result.exit_code == 0
    assert created[0].transition == TransitionSettings(
        style=TransitionStyle.CUT, fade_seconds=8.0
    )
