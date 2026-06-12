from __future__ import annotations

import asyncio
from pathlib import Path

from bester_ytm.config import get_paths
from bester_ytm.config_options import load_app_options
from bester_ytm.tui import BesterYTMApp


def _sandbox(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return get_paths().config_file


def test_ember_theme_registered_and_applied_by_default(tmp_path, monkeypatch) -> None:
    _sandbox(tmp_path, monkeypatch)
    app = BesterYTMApp()

    async def run() -> None:
        async with app.run_test(size=(110, 50)):
            assert "ember" in app.available_themes
            assert app.theme == "ember"

    asyncio.run(run())


def test_theme_change_is_persisted(tmp_path, monkeypatch) -> None:
    _sandbox(tmp_path, monkeypatch)
    app = BesterYTMApp()

    async def run() -> None:
        async with app.run_test(size=(110, 50)) as pilot:
            app.theme = "textual-light"
            await pilot.pause()

    asyncio.run(run())

    assert load_app_options().theme == "textual-light"


def test_visual_fps_zero_disables_the_animation_interval(tmp_path, monkeypatch) -> None:
    path = _sandbox(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True)
    path.write_text("[ui]\nvisual_fps = 0\n", encoding="utf-8")
    app = BesterYTMApp()

    intervals: list[float] = []
    original = app.set_interval
    monkeypatch.setattr(
        app,
        "set_interval",
        lambda interval, *a, **k: intervals.append(interval) or original(interval, *a, **k),
    )

    async def run() -> None:
        async with app.run_test(size=(110, 50)) as pilot:
            await pilot.pause()

    asyncio.run(run())

    assert 0.75 in intervals  # playback refresh still runs
    assert 0.125 not in intervals  # the 8 fps animation tick is never scheduled
