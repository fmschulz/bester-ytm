"""The stage in a running app: idle still, theme recolouring, click to go full screen."""

from __future__ import annotations

import asyncio

import pytest

from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_stage import Stage


def _lines(stage: Stage) -> list[str]:
    return [stage.render_line(y).text for y in range(stage.size.height)]


def _styles(stage: Stage) -> set[str]:
    return {
        str(segment.style)
        for y in range(stage.size.height)
        for segment in stage.render_line(y)
        if segment.text.strip()
    }


def test_stage_shows_a_dim_idle_scene_on_start() -> None:
    async def run() -> None:
        app = BesterYTMApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            stage = app.query_one(Stage)

            assert stage.has_class("idle-effect")
            assert any(line.strip() for line in _lines(stage))
            assert all(len(line) == stage.size.width for line in _lines(stage))

    asyncio.run(run())


def test_theme_change_recolours_the_stage() -> None:
    async def run() -> None:
        app = BesterYTMApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            stage = app.query_one(Stage)
            astra = _styles(stage)

            app.theme = "ember"
            await pilot.pause()

            assert _styles(stage) != astra
            assert any(line.strip() for line in _lines(stage))

    asyncio.run(run())


def test_clicking_the_stage_toggles_full_screen() -> None:
    async def run() -> None:
        app = BesterYTMApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.click("#big-visual")
            assert app.screen.has_class("immersive")

            await pilot.click("#big-visual")
            assert not app.screen.has_class("immersive")

    asyncio.run(run())


def test_stage_renders_when_colour_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")

    async def run() -> None:
        app = BesterYTMApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()

            assert any(line.strip() for line in _lines(app.query_one(Stage)))

    asyncio.run(run())


def test_switching_scene_while_idle_leaves_no_trace_of_the_old_one() -> None:
    async def run() -> None:
        app = BesterYTMApp()
        async with app.run_test(size=(120, 40)) as pilot:
            app._apply_visualizer_effect("bars")
            app._apply_visualizer_effect("scope")
            await pilot.pause()
            switched = _lines(app.query_one(Stage))

        fresh = BesterYTMApp()
        async with fresh.run_test(size=(120, 40)) as pilot:
            fresh._apply_visualizer_effect("scope")
            await pilot.pause()

            assert _lines(fresh.query_one(Stage)) == switched

    asyncio.run(run())
