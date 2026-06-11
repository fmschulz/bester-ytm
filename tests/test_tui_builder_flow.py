"""End-to-end builder triggering through the real widget tree."""

from __future__ import annotations

import asyncio
from functools import partial

import pytest
from textual.widgets import Label, TextArea

from bester_ytm.intelligence.llm import IntelligenceSettings
from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_builder import _normalize_build_inputs

BRIEF = "create a playlist with 10 songs of bands similar to blind guardian"


def test_prose_in_seed_box_is_treated_as_a_brief() -> None:
    assert _normalize_build_inputs(BRIEF, "") == ("", BRIEF)
    assert _normalize_build_inputs(BRIEF, "no live versions") == (
        "",
        f"{BRIEF}; no live versions",
    )
    assert _normalize_build_inputs("Beach House - Myth", "dreamy") == (
        "Beach House - Myth",
        "dreamy",
    )
    assert _normalize_build_inputs("", "just a brief") == ("", "just a brief")


def _start_build_capture(app: BesterYTMApp, monkeypatch: pytest.MonkeyPatch) -> list:
    started: list = []
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: started.append(work))
    app.intelligence_settings = IntelligenceSettings(provider="codex")
    return started


def test_typing_prose_in_big_box_and_clicking_build_starts_a_build(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = BesterYTMApp()
    started = _start_build_capture(app, monkeypatch)

    async def flow() -> None:
        async with app.run_test(size=(120, 50)) as pilot:
            app.query_one("#builder", TextArea).text = BRIEF
            app.query_one("#build-button").scroll_visible(animate=False)
            await pilot.pause()
            await pilot.click("#build-button")
            await pilot.pause()
            title = app.query_one("#queue-title", Label)
            assert "Building playlist" in str(title.render())

    asyncio.run(flow())

    assert app.build_in_progress is True
    assert len(started) == 1
    builder_text, brief = started[0].args  # the worker partial's normalized inputs
    assert isinstance(started[0], partial)
    assert builder_text == ""
    assert brief == BRIEF


def test_enter_on_prose_in_seed_box_starts_a_build_via_real_bubbling(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = BesterYTMApp()
    started = _start_build_capture(app, monkeypatch)

    async def flow() -> None:
        async with app.run_test(size=(120, 50)) as pilot:
            builder = app.query_one("#builder", TextArea)
            builder.text = BRIEF
            builder.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(flow())

    assert app.build_in_progress is True
    assert len(started) == 1


def test_enter_on_seed_lines_in_seed_box_adds_a_newline(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = BesterYTMApp()
    started = _start_build_capture(app, monkeypatch)

    async def flow() -> None:
        async with app.run_test(size=(120, 50)) as pilot:
            builder = app.query_one("#builder", TextArea)
            builder.text = "Beach House - Myth"
            builder.move_cursor(builder.document.end)
            builder.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert builder.text == "Beach House - Myth\n"

    asyncio.run(flow())

    assert app.build_in_progress is False
    assert started == []


def test_build_with_nothing_to_build_explains_what_to_do(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bester_ytm import tui_builder
    from bester_ytm.config import ConfigError

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(
        tui_builder,
        "resolve_existing_input",
        lambda path: (_ for _ in ()).throw(ConfigError("no favorites")),
    )
    app = BesterYTMApp()
    started = _start_build_capture(app, monkeypatch)
    statuses: list[str] = []

    async def flow() -> None:
        async with app.run_test(size=(120, 50)) as pilot:
            monkeypatch.setattr(app, "_set_status", statuses.append)
            app.query_one("#build-button").scroll_visible(animate=False)
            await pilot.pause()
            await pilot.click("#build-button")
            await pilot.pause()

    asyncio.run(flow())

    assert app.build_in_progress is False
    assert started == []
    assert "Describe the playlist you want" in statuses[-1]
