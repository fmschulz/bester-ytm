"""Build progress and cancellation without threads, network, or clock waits."""

from __future__ import annotations

import asyncio
from functools import partial
from threading import Event
from unittest.mock import Mock

import pytest
from textual.widgets import Input, TextArea

from bester_ytm import tui_builder
from bester_ytm.playlist_plan import PlaylistPlan, SongCandidate
from bester_ytm.tui import BesterYTMApp


@pytest.mark.parametrize("brief", ["15 songs like Air", "Add 5 songs like Air"])
@pytest.mark.parametrize("cancel_with", ["escape", "button"])
def test_cancel_restores_title_ignores_late_results_and_allows_another_build(
    monkeypatch: pytest.MonkeyPatch, cancel_with: str, brief: str
) -> None:
    async def flow() -> None:
        app = BesterYTMApp()
        started: list[partial] = []
        clock = Mock(return_value=10.0)
        monkeypatch.setattr(tui_builder, "monotonic", clock)
        monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: started.append(work))
        async with app.run_test(size=(140, 44)) as pilot:
            cancel_button = app.query_one("#cancel-build-button")
            assert not cancel_button.display
            app.query_one("#builder", TextArea).text = brief
            await app.action_build_playlist()
            first = app._build_cancel
            assert isinstance(first, Event)
            assert cancel_button.display
            assert "0:00" in app.query_one("#center").border_title
            clock.return_value = 52.0
            app._update_build_progress()
            assert app.query_one("#center").border_title == "Building playlist… 0:42"
            await app._render_queue()
            assert "0:42" in app.query_one("#center").border_title
            if cancel_with == "escape":
                app.query_one("#search", Input).focus()
                await pilot.press("escape")
            else:
                await pilot.pause()
                await pilot.click("#cancel-build-button")
                await pilot.pause()
            assert first.is_set()
            assert not app.build_in_progress
            assert not cancel_button.display
            assert "Building" not in app.query_one("#center").border_title
            assert "cancelled" in str(app.query_one("#status").content)
            await app.action_build_playlist()
            assert app.build_in_progress
            assert app._build_cancel is not first
            app._complete_playlist_build(
                PlaylistPlan(id="old", name="Old", target_count=1), "Old", first
            )
            app._report_build_failure("Old failure", first)
            app._complete_add_tracks_brief(
                [SongCandidate(video_id="old", title="Old")], "codex", first
            )
            assert app.build_in_progress
            assert "Old" not in str(app.query_one("#status").content)
            assert app.playlist_title == "Queue"
            assert len(started) == 2
            app.action_cancel_build()

    asyncio.run(flow())


def test_build_passes_cancel_event_to_provider_and_does_not_save_cancelled_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel = Event()
    builder = Mock()

    def cancelled_build(*args: object, **kwargs: object) -> PlaylistPlan:
        assert kwargs["cancel"] is cancel
        cancel.set()
        return PlaylistPlan(id="cancelled", name="Cancelled", target_count=1)

    builder.build_from_brief.side_effect = cancelled_build
    monkeypatch.setattr(tui_builder, "PlaylistBuilder", lambda: builder)
    store = Mock()
    monkeypatch.setattr(tui_builder, "PlanStore", lambda: store)
    with pytest.raises(tui_builder.IntelligenceError, match="cancelled"):
        BesterYTMApp()._run_playlist_build("", "songs like Air", cancel)
    store.save.assert_not_called()


def test_escape_still_cancels_pending_similar_count(monkeypatch: pytest.MonkeyPatch) -> None:
    async def flow() -> None:
        app = BesterYTMApp()
        launches = Mock()
        monkeypatch.setattr(app, "_launch_similar", launches)
        async with app.run_test() as pilot:
            app.set_focus(None)
            app._similar_digits = "7"
            app._similar_timer = Mock()
            await pilot.press("escape")
            assert app._similar_digits is None
            assert "Add similar cancelled." == str(app.query_one("#status").content)
            app._flush_similar_count()
            launches.assert_not_called()

    asyncio.run(flow())
