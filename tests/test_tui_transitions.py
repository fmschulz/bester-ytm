import asyncio
from dataclasses import replace
from pathlib import Path

from textual.binding import Binding

from bester_ytm import tui, tui_playback
from bester_ytm.config import ConfigError
from bester_ytm.playback import PlaybackStatus
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.transitions import DEFAULT_APP_SETTINGS, TransitionSettings, TransitionStyle


class FakeWidget:
    def __init__(self) -> None:
        self.value = ""
        self.classes = set()

    def update(self, value: str) -> None:
        self.value = value

    def add_class(self, class_name: str) -> None:
        self.classes.add(class_name)

    def remove_class(self, class_name: str) -> None:
        self.classes.discard(class_name)


class FakeProgress:
    def update(self, *, total, progress) -> None:
        pass


class FakeTransitionPlayback:
    def __init__(
        self,
        style: TransitionStyle = TransitionStyle.CUT,
        fade_seconds: float = 6.0,
    ) -> None:
        self.queue: list[str] = []
        self.transition = TransitionSettings(style=style, fade_seconds=fade_seconds)
        self.current = PlaybackStatus(running=False)
        self.stopped = False

    def status(self) -> PlaybackStatus:
        return self.current

    def consume_transition_error(self) -> str | None:
        error = self.current.transition_error
        self.current = replace(self.current, transition_error=None)
        return error

    def stop(self) -> None:
        self.stopped = True

    def cycle_transition_style(self) -> TransitionSettings:
        next_style = (
            TransitionStyle.CROSSFADE
            if self.transition.style is TransitionStyle.CUT
            else TransitionStyle.CUT
        )
        self.transition = TransitionSettings(
            style=next_style, fade_seconds=self.transition.fade_seconds
        )
        return self.transition

    def adjust_fade_seconds(self, delta: float) -> TransitionSettings:
        self.transition = TransitionSettings(
            style=self.transition.style,
            fade_seconds=self.transition.fade_seconds + delta,
        ).clamped()
        return self.transition


def _make_app(monkeypatch, tmp_path, playback) -> tuple[tui.BesterYTMApp, list[str]]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    app = tui.BesterYTMApp()
    app.playback = playback  # type: ignore[assignment]
    if hasattr(playback, "transition"):
        app.transition_settings = playback.transition
    statuses: list[str] = []
    monkeypatch.setattr(app, "_set_status", statuses.append)
    return app, statuses


def test_transition_keys_are_bound() -> None:
    assert ("t", "cycle_transition", "Mix") in tui.BesterYTMApp.BINDINGS
    bracket_bindings = {
        binding.key: binding
        for binding in tui.BesterYTMApp.BINDINGS
        if isinstance(binding, Binding)
    }
    fade_shorter = bracket_bindings["left_square_bracket"]
    assert fade_shorter.action == "fade_shorter"
    assert fade_shorter.show is False
    fade_longer = bracket_bindings["right_square_bracket"]
    assert fade_longer.action == "fade_longer"
    assert fade_longer.show is False


def test_cycle_transition_reports_style_and_persists(monkeypatch, tmp_path) -> None:
    saved: list[TransitionSettings] = []
    monkeypatch.setattr(
        tui_playback,
        "save_transition_settings",
        lambda settings: saved.append(settings) or Path("unused"),
    )
    app, statuses = _make_app(monkeypatch, tmp_path, FakeTransitionPlayback())

    app.action_cycle_transition()
    assert statuses[-1] == "Transition: crossfade 6s ([ / ] adjust fade)."

    app.action_cycle_transition()
    assert statuses[-1] == "Transition: cut."
    assert [settings.style for settings in saved] == [
        TransitionStyle.CROSSFADE,
        TransitionStyle.CUT,
    ]


def test_cycle_transition_reports_persist_failure(monkeypatch, tmp_path) -> None:
    def fail_save(settings: TransitionSettings) -> Path:
        raise ConfigError("disk full")

    monkeypatch.setattr(tui_playback, "save_transition_settings", fail_save)
    app, statuses = _make_app(monkeypatch, tmp_path, FakeTransitionPlayback())

    app.action_cycle_transition()

    assert statuses[-1] == "Transition: crossfade 6s ([ / ] adjust fade). Not saved: disk full"


def test_action_quit_stops_playback_before_exit(monkeypatch, tmp_path) -> None:
    playback = FakeTransitionPlayback()
    app, _ = _make_app(monkeypatch, tmp_path, playback)
    exits: list[bool] = []
    monkeypatch.setattr(app, "exit", lambda *args, **kwargs: exits.append(True))

    asyncio.run(app.action_quit())

    assert playback.stopped is True
    assert exits == [True]


def test_fade_adjustments_report_length_clamps_and_cut_hint(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        tui_playback, "save_transition_settings", lambda settings: Path("unused")
    )
    playback = FakeTransitionPlayback(style=TransitionStyle.CROSSFADE, fade_seconds=6.0)
    app, statuses = _make_app(monkeypatch, tmp_path, playback)

    app.action_fade_longer()
    assert statuses[-1] == "Fade length 7s."

    playback.transition = TransitionSettings(
        style=TransitionStyle.CROSSFADE, fade_seconds=15.0
    )
    app.transition_settings = playback.transition
    app.action_fade_longer()
    assert statuses[-1] == "Fade length at maximum (15s)."

    playback.transition = TransitionSettings(
        style=TransitionStyle.CROSSFADE, fade_seconds=1.0
    )
    app.transition_settings = playback.transition
    app.action_fade_shorter()
    assert statuses[-1] == "Fade length at minimum (1s)."

    playback.transition = TransitionSettings(style=TransitionStyle.CUT, fade_seconds=6.0)
    app.transition_settings = playback.transition
    app.action_fade_shorter()
    assert statuses[-1] == "Fade length 5s (transition is cut; press t to mix)."


def _status_widgets() -> dict[str, object]:
    return {
        "#visualizer": FakeWidget(),
        "#right": FakeWidget(),
        "#progress-time": FakeWidget(),
        "#volume-status": FakeWidget(),
        "#track": FakeWidget(),
        "#progress": FakeProgress(),
        "#play-button": FakeWidget(),
        "#mute-button": FakeWidget(),
    }


def test_visualizer_renders_mix_meter_and_announces_mix_once(monkeypatch, tmp_path) -> None:
    widgets = _status_widgets()
    playback = FakeTransitionPlayback(style=TransitionStyle.CROSSFADE)
    app, statuses = _make_app(monkeypatch, tmp_path, playback)
    app.candidates_by_video_id = {
        "v2": SongCandidate(video_id="v2", title="Two", artists=["Band"]),
    }
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: work.close())

    playback.current = PlaybackStatus(
        running=True,
        current_video_id="v2",
        position_seconds=10,
        duration_seconds=60,
        volume=80,
        transition_style="crossfade",
        fade_seconds=6.0,
        mix_progress=0.5,
        active_deck="B",
    )
    app._refresh_playback()

    assert widgets["#visualizer"].value == "MIX  A [######------] B  xfade 6s"
    assert statuses == ["Mixing into Band - Two."]

    playback.current = replace(playback.current, mix_progress=0.75)
    app._refresh_playback()
    assert statuses == ["Mixing into Band - Two."]

    playback.current = replace(playback.current, mix_progress=None, fade_seconds=8.0)
    app._refresh_playback()
    assert widgets["#visualizer"].value == "DECK B  xfade 8s  (playing)"


def test_visualizer_renders_deck_line_when_idle(monkeypatch, tmp_path) -> None:
    widgets = _status_widgets()
    playback = FakeTransitionPlayback()
    app, statuses = _make_app(monkeypatch, tmp_path, playback)
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    app._refresh_playback()

    assert widgets["#visualizer"].value == "DECK A  cut  (idle)"


def test_refresh_reports_transition_error_once(monkeypatch, tmp_path) -> None:
    widgets = _status_widgets()
    playback = FakeTransitionPlayback(style=TransitionStyle.CROSSFADE)
    app, statuses = _make_app(monkeypatch, tmp_path, playback)
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: work.close())

    playback.current = PlaybackStatus(
        running=True,
        current_video_id="v3",
        transition_error="deck B died",
    )
    app._refresh_playback()
    assert statuses[-1] == "Mix failed; using cut: deck B died"

    playback.current = replace(playback.current, transition_error=None)
    app._refresh_playback()
    assert statuses == ["Mix failed; using cut: deck B died"]


def test_tui_startup_loads_transition_settings(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config_dir = tmp_path / "config" / "bester-ytm"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        '[playback]\ntransition = "cut"\nfade_seconds = 3.0\n', encoding="utf-8"
    )

    app = tui.BesterYTMApp()

    expected = TransitionSettings(style=TransitionStyle.CUT, fade_seconds=3.0)
    assert app.transition_settings == expected
    assert app.playback.transition == expected
    assert app._config_error is None


def test_tui_startup_survives_invalid_transition_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config_dir = tmp_path / "config" / "bester-ytm"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        '[playback]\ntransition = "wave"\n', encoding="utf-8"
    )

    app = tui.BesterYTMApp()

    assert app.transition_settings == DEFAULT_APP_SETTINGS
    assert app._config_error is not None
    assert "playback.transition" in app._config_error


def test_mix_and_fade_buttons_drive_transition_actions(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(
        tui_playback, "save_transition_settings", lambda settings: Path("unused")
    )

    async def run_flow() -> None:
        app = tui.BesterYTMApp()
        playback = FakeTransitionPlayback(style=TransitionStyle.CROSSFADE, fade_seconds=6.0)
        app.playback = playback  # type: ignore[assignment]
        app.transition_settings = playback.transition
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.click("#fade-up-button")
            await pilot.pause()
            assert playback.transition.fade_seconds == 7.0

            await pilot.click("#fade-down-button")
            await pilot.pause()
            assert playback.transition.fade_seconds == 6.0

            await pilot.click("#transition-button")
            await pilot.pause()
            assert playback.transition.style is TransitionStyle.CUT

    asyncio.run(run_flow())
