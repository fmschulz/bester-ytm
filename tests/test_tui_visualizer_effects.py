import asyncio

from textual.widgets import Select

from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_layout import EFFECT_OPTIONS
from bester_ytm.tui_visuals import EFFECT_ORDER


def test_effect_registry_matches_dropdown_options() -> None:
    assert [value for _, value in EFFECT_OPTIONS] == list(EFFECT_ORDER)


def test_dropdown_changes_visualizer_effect(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = BesterYTMApp()

    async def run_flow() -> None:
        async with app.run_test(size=(110, 50)) as pilot:
            app.query_one("#effect-select", Select).value = "pulsar"
            await pilot.pause()

    asyncio.run(run_flow())

    assert app.visualizer_effect == "pulsar"


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

    assert effects[: len(EFFECT_ORDER)] == list(EFFECT_ORDER[1:]) + [EFFECT_ORDER[0]]
    assert effects[-1] == EFFECT_ORDER[1]


def test_quick_scene_changes_settle_on_the_last_one(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = BesterYTMApp()
    applied: list[str] = []

    async def run_flow() -> None:
        async with app.run_test(size=(110, 50)) as pilot:
            original = app._apply_visualizer_effect

            def spy(effect: str) -> None:
                applied.append(effect)
                original(effect)

            monkeypatch.setattr(app, "_apply_visualizer_effect", spy)
            app.action_cycle_visualizer()
            app.action_cycle_visualizer()
            await pilot.pause()
            await pilot.pause()

    asyncio.run(run_flow())

    assert applied == [EFFECT_ORDER[1], EFFECT_ORDER[2]]
    assert app.visualizer_effect == EFFECT_ORDER[2]
