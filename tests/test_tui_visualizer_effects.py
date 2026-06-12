import asyncio

from textual.widgets import Select

from bester_ytm.playback import PlaybackStatus
from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_effects import render_deck_status
from bester_ytm.tui_layout import EFFECT_OPTIONS
from bester_ytm.tui_visuals import EFFECT_ORDER


def test_effect_registry_matches_dropdown_options() -> None:
    assert [value for _, value in EFFECT_OPTIONS] == list(EFFECT_ORDER)


def test_deck_status_reports_deck_and_transition() -> None:
    status = PlaybackStatus(
        running=True, active_deck="A", transition_style="crossfade", fade_seconds=4
    )
    line = render_deck_status(status)
    assert "DECK A" in line and "xfade 4s" in line and "playing" in line


def test_deck_status_shows_mix_progress_during_a_crossfade() -> None:
    status = PlaybackStatus(running=True, active_deck="B", mix_progress=0.5)
    line = render_deck_status(status)
    assert line.startswith("MIX") and "A" in line and "B" in line


def test_deck_status_marks_idle_and_paused() -> None:
    assert "idle" in render_deck_status(PlaybackStatus(running=False))
    assert "paused" in render_deck_status(PlaybackStatus(running=True, paused=True))


def test_dropdown_changes_visualizer_effect(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = BesterYTMApp()

    async def run_flow() -> None:
        async with app.run_test(size=(110, 50)) as pilot:
            app.query_one("#effect-select", Select).value = "pulse"
            await pilot.pause()

    asyncio.run(run_flow())

    assert app.visualizer_effect == "pulse"


def test_cycle_visualizer_action_advances_and_syncs_dropdown(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = BesterYTMApp()
    effects: list[str] = []

    async def run_flow() -> None:
        async with app.run_test(size=(110, 50)) as pilot:
            for _ in range(len(EFFECT_ORDER) + 1):
                app.action_cycle_visualizer()
                await pilot.pause()
                effects.append(app.visualizer_effect)
            assert app.query_one("#effect-select", Select).value == app.visualizer_effect

    asyncio.run(run_flow())

    assert effects[: len(EFFECT_ORDER)] == ["oracle", "bars", "wave", "pulse", "scope", "mythos"]
    assert effects[-1] == "oracle"
