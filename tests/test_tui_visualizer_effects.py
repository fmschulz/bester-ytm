import asyncio

import pytest
from textual.widgets import Select

from bester_ytm.playback import PlaybackStatus
from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_effects import (
    EFFECT_WIDTH,
    VISUALIZER_EFFECTS,
    effect_bars,
    effect_pulse,
    effect_scope,
    effect_wave,
    render_visualizer,
)
from bester_ytm.tui_layout import EFFECT_OPTIONS


def test_effect_registry_matches_dropdown_options() -> None:
    assert list(VISUALIZER_EFFECTS) == [value for _, value in EFFECT_OPTIONS]


@pytest.mark.parametrize("effect", [effect_wave, effect_pulse, effect_scope])
def test_effects_are_deterministic_and_animated(effect) -> None:
    assert effect(3) == effect(3)
    assert any(effect(frame) != effect(frame + 1) for frame in range(4))
    assert len(effect(0)) == EFFECT_WIDTH


def test_render_visualizer_uses_selected_effect() -> None:
    status = PlaybackStatus(running=True, position_seconds=10.0, duration_seconds=100.0)

    wave_frame = render_visualizer(status, frame=5, effect="wave")
    default_frame = render_visualizer(status, frame=5)

    assert f"EQ    {effect_wave(5)}" in wave_frame
    assert f"EQ    {effect_bars(5)}" in default_frame


def test_render_visualizer_falls_back_to_bars_for_unknown_effect() -> None:
    status = PlaybackStatus(running=True)

    assert render_visualizer(status, 2, effect="nope") == render_visualizer(status, 2)


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
            for _ in range(len(VISUALIZER_EFFECTS) + 1):
                app.action_cycle_visualizer()
                await pilot.pause()
                effects.append(app.visualizer_effect)
            assert app.query_one("#effect-select", Select).value == app.visualizer_effect

    asyncio.run(run_flow())

    assert effects[: len(VISUALIZER_EFFECTS)] == ["bars", "wave", "pulse", "scope", "mythos"]
    assert effects[-1] == "bars"
