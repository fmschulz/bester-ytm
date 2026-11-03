"""End-to-end builder triggering through the real widget tree."""

from __future__ import annotations

import asyncio
import json
from functools import partial
from unittest.mock import Mock

import pytest
from textual.widgets import TextArea

from bester_ytm import playlist_builder as builder_module
from bester_ytm.intelligence import llm
from bester_ytm.intelligence.llm import IntelligenceSettings
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.stores import FavoritesStore, PlanStore
from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_builder import _normalize_build_inputs

BRIEF = "create a playlist with 10 songs of bands similar to blind guardian"


@pytest.fixture
def saved_favorites() -> list[SongCandidate]:
    """Save four tracks through the same store used by the Favorites view."""
    favorites = [
        SongCandidate(video_id="fav-1", artists=["Beach House"], title="Myth"),
        SongCandidate(video_id="fav-2", artists=["Slowdive"], title="Alison"),
        SongCandidate(video_id="fav-3", artists=["Cocteau Twins"], title="Heaven or Las Vegas"),
        SongCandidate(video_id="fav-4", artists=["Mazzy Star"], title="Fade Into You"),
    ]
    store = FavoritesStore()
    for favorite in favorites:
        store.toggle(favorite)
    return favorites


@pytest.mark.parametrize(
    ("brief", "uses_favorites"),
    [
        ("generate a 30 song palylsit basedo nthe 4 songs I have in favorites", True),
        ("Generate 30 songs based on my FAVOURITES", True),
        ("Generate 30 songs similar to Beach House", False),
    ],
)
def test_brief_build_resolves_30_songs_with_requested_favorite_context(
    monkeypatch: pytest.MonkeyPatch,
    saved_favorites: list[SongCandidate],
    brief: str,
    uses_favorites: bool,
) -> None:
    suggestions = [
        SongCandidate(video_id=f"song-{index}", artists=["Suggested Artist"], title=f"Song {index}")
        for index in range(30)
    ]
    songs_by_query = {f"Suggested Artist {song.title}": song for song in suggestions}
    client = Mock(spec=builder_module.YTMClient)
    client.search_songs.side_effect = lambda query, limit: [songs_by_query[query]]
    monkeypatch.setattr(builder_module, "YTMClient", Mock(return_value=client))
    monkeypatch.setattr(
        builder_module, "load_intelligence_settings", lambda: IntelligenceSettings(provider="codex")
    )
    ai = Mock(
        return_value=json.dumps(
            {
                "name": "Favorite Neighbors",
                "tracks": [
                    {"artist": "Suggested Artist", "title": song.title} for song in suggestions
                ],
            }
        )
    )
    monkeypatch.setattr(llm, "_codex_text", ai)

    plan, message = BesterYTMApp()._run_playlist_build(*_normalize_build_inputs(brief, ""))

    prompt = ai.call_args.args[1]
    assert "exactly 30 songs" in prompt
    assert ("- Beach House - Myth" in prompt) is uses_favorites
    assert ("- Slowdive - Alison" in prompt) is uses_favorites
    assert ("- Cocteau Twins - Heaven or Las Vegas" in prompt) is uses_favorites
    assert ("- Mazzy Star - Fade Into You" in prompt) is uses_favorites
    assert plan.target_count == plan.resolved_count == 30
    assert len(set(plan.selected_video_ids)) == 30
    assert PlanStore().load(plan.id).selected_video_ids == plan.selected_video_ids
    assert FavoritesStore().list() == saved_favorites
    assert "30/30 resolved" in message


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
            assert "Building playlist" in app.query_one("#center").border_title

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
