"""Observable guide, resize, shortcut, notification, and radio behavior."""

from __future__ import annotations

import asyncio
from threading import Event
from unittest.mock import AsyncMock, Mock

import pytest
from fakes import FakePlayback
from textual.binding import Binding
from textual.content import Content
from textual.pilot import Pilot
from textual.widgets import Button, Collapsible, Input, TextArea

from bester_ytm.config import ConfigError
from bester_ytm.playback import PlaybackError, PlaybackStatus
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_help import ACTION_DESCRIPTIONS, help_sections, key_display
from bester_ytm.tui_rows import queue_heading
from bester_ytm.tui_visuals import EFFECT_LABELS


async def _wait_for_layout(app: BesterYTMApp, pilot: Pilot[None]) -> None:
    """Wait for pane resize messages and the border refresh they schedule."""
    await pilot._wait_for_screen()
    # Pilot's short idle window can end before Textual's resize debounce fires.
    app._check_resize()
    await pilot._wait_for_screen()
    refreshed = asyncio.Event()
    app.call_after_refresh(refreshed.set)
    await asyncio.wait_for(refreshed.wait(), timeout=2.0)


def test_guide_has_one_sentence_per_action_and_groups_aliases() -> None:
    bindings = [b if isinstance(b, Binding) else Binding(*b) for b in BesterYTMApp.BINDINGS]
    rows = [row for _, section in help_sections(bindings) for row in section]
    assert len(rows) == len({binding.action for binding in bindings})
    keys = {key for key, _ in rows}
    assert {"p / b", "= / +", "F1 / ?"} <= keys
    for binding in bindings:
        assert binding.action in ACTION_DESCRIPTIONS
        assert ACTION_DESCRIPTIONS[binding.action].endswith(".")
    for label in EFFECT_LABELS.values():
        assert label in ACTION_DESCRIPTIONS["cycle_visualizer"]


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("ctrl+p", "Ctrl+P"),
        ("shift+tab", "Shift+Tab"),
        ("f1", "F1"),
        ("space", "Space"),
        ("enter", "Enter"),
        ("escape", "Esc"),
        ("left", "Left"),
        ("right", "Right"),
        ("a", "a"),
        ("A", "A"),
    ],
)
def test_guide_uses_readable_key_names(key: str, expected: str) -> None:
    assert key_display(Binding(key, "action", "Action")) == expected


def test_queue_heading_keeps_summary_and_shortens_only_name() -> None:
    heading = queue_heading("Late Night Electronica", 14, 3840, width=39)
    assert heading.cell_length <= 39
    assert str(heading).endswith("14 tracks, 1 h 04 min")
    assert "…" in str(heading)
    assert str(queue_heading("夜" * 20, 14, 3840, width=39)).endswith("14 tracks, 1 h 04 min")


def test_pane_titles_and_hints_recompute_on_resize() -> None:
    async def flow() -> None:
        app = BesterYTMApp()
        app.playback = FakePlayback()
        app.playlist_title = "Late Night Electronica"
        ids = [f"v{i}" for i in range(14)]
        app.playlist_video_ids = ids
        app.candidates_by_video_id = {
            video_id: SongCandidate(video_id=video_id, title=video_id, duration_seconds=274)
            for video_id in ids
        }
        async with app.run_test(size=(140, 44)) as pilot:
            await app._render_queue()
            await _wait_for_layout(app, pilot)
            wide_hint = Content.from_markup(app.query_one("#left").border_subtitle)
            await pilot.resize_terminal(80, 24)
            await _wait_for_layout(app, pilot)
            pane = app.query_one("#center")
            title = Content.from_markup(pane.border_title)
            assert title.cell_length <= pane.region.width - 4
            assert str(title).endswith("14 tracks, 1 h 04 min")
            assert "…" in str(title)
            hint = Content.from_markup(app.query_one("#left").border_subtitle)
            assert str(wide_hint).startswith(str(hint))
            assert str(hint).endswith(("play", "add", "mark", "favorite"))
            assert hint.cell_length <= app.query_one("#left").region.width - 4
            await pilot.resize_terminal(180, 44)
            await _wait_for_layout(app, pilot)
            assert "Late Night Electronica" in app.query_one("#center").border_title

    asyncio.run(flow())


@pytest.mark.parametrize(
    ("key", "action"),
    [
        ("r", "show_radio"),
        ("N", "new_playlist"),
        ("l", "add_to_local_playlist"),
        ("D", "remove_from_playlist"),
    ],
)
def test_workspace_keys_run_actions_but_allow_typing(
    monkeypatch: pytest.MonkeyPatch, key: str, action: str
) -> None:
    async def flow() -> None:
        app = BesterYTMApp()
        callback = AsyncMock()
        monkeypatch.setattr(app, f"action_{action}", callback)
        async with app.run_test(size=(140, 44)) as pilot:
            app.set_focus(None)
            await pilot.press(key)
            callback.assert_awaited_once()
            for selector in ("#search", "#playlist-name"):
                field = app.query_one(selector, Input)
                field.value = ""
                field.focus()
                await pilot.press(key)
                assert field.value == key
            builder = app.query_one("#builder", TextArea)
            builder.focus()
            await pilot.press(key)
            assert builder.text == key
            callback.assert_awaited_once()

    asyncio.run(flow())


def test_startup_login_hint_fits_status_at_80_columns() -> None:
    message = BesterYTMApp()._startup_status()
    assert "bester-ytm auth login" in message
    assert len(message) <= 78


def test_error_updates_status_and_survives_later_status(monkeypatch: pytest.MonkeyPatch) -> None:
    app = BesterYTMApp()
    statuses = Mock()
    notify = Mock()
    monkeypatch.setattr(app, "_set_status", statuses)
    monkeypatch.setattr(app, "notify", notify)
    app._report_error("Search failed; retry.")
    app._set_status("Playing.")
    assert statuses.call_args_list[0].args == ("Search failed; retry.",)
    notify.assert_called_once_with("Search failed; retry.", severity="error")


def test_navigation_does_not_cancel_a_build(monkeypatch: pytest.MonkeyPatch) -> None:
    async def flow() -> None:
        app = BesterYTMApp()
        monkeypatch.setattr(app, "run_worker", Mock())
        monkeypatch.setattr(app, "_search", AsyncMock())
        async with app.run_test(size=(140, 44)):
            app.query_one("#builder", TextArea).text = "songs like Air"
            await app.action_build_playlist()
            await app.action_focus_search()
            await app.action_show_radio()
            app.action_toggle_tools()
            assert app.build_in_progress
            assert not app._build_cancel.is_set()
            app.action_cancel_build()

    asyncio.run(flow())


def test_playback_failure_notifies_once_until_playback_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = BesterYTMApp()
    notify = Mock()
    monkeypatch.setattr(app, "notify", notify)
    monkeypatch.setattr(app, "_set_status", Mock())
    failed = PlaybackStatus(running=False, playback_error="Stream failed; retry.")
    app._handle_auto_advance(failed)
    app._handle_auto_advance(failed)
    notify.assert_called_once_with("Stream failed; retry.", severity="error")
    app._handle_auto_advance(PlaybackStatus(running=True))
    app._handle_auto_advance(failed)
    assert notify.call_count == 2


def test_playback_poll_errors_notify_once(monkeypatch: pytest.MonkeyPatch) -> None:
    app = BesterYTMApp()
    app.playback = Mock()
    app.playback.status.side_effect = PlaybackError("Player unavailable; retry.")
    notify = Mock()
    monkeypatch.setattr(app, "notify", notify)
    monkeypatch.setattr(app, "_set_status", Mock())
    app._refresh_playback()
    app._refresh_playback()
    notify.assert_called_once_with("Player unavailable; retry.", severity="error")


@pytest.mark.parametrize("operation", ["add", "remove", "save"])
def test_local_playlist_errors_notify(monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    app = BesterYTMApp()
    song = SongCandidate(video_id="song", title="Song")
    store = Mock()
    for method in (store.add_track, store.remove_track, store.save):
        method.side_effect = ConfigError("Playlist is corrupt; move it aside.")
    monkeypatch.setattr("bester_ytm.tui_metadata.LocalPlaylistStore", lambda: store)
    monkeypatch.setattr("bester_ytm.tui_queue.LocalPlaylistStore", lambda: store)
    monkeypatch.setattr(app, "_current_candidate", lambda: song)
    monkeypatch.setattr(app, "_queue_candidates", lambda: [song])
    monkeypatch.setattr(app, "_set_status", Mock())
    notify = Mock()
    monkeypatch.setattr(app, "notify", notify)
    if operation == "add":
        app.action_add_to_local_playlist()
    elif operation == "remove":
        asyncio.run(app._remove_from_local_playlist("mix", "song"))
    else:
        app.action_save_queue_playlist()
    notify.assert_called_once_with("Playlist is corrupt; move it aside.", severity="error")


@pytest.mark.parametrize("theme", ["astra", "ember"])
def test_workspace_buttons_fit_30_cells_and_keep_their_place_on_focus(theme: str) -> None:
    async def flow() -> None:
        app = BesterYTMApp()
        async with app.run_test(size=(140, 44)) as pilot:
            app.theme = theme
            pane = app.query_one("#right")
            pane.styles.width = 30
            app.query_one("#mix-tools", Collapsible).collapsed = False
            cancel = app.query_one("#cancel-build-button", Button)
            cancel.display = True
            await pilot.pause()
            before = cancel.region
            cancel.focus()
            await pilot.pause()
            assert cancel.region == before
            assert pane.region.width == 30
            for button in pane.query(Button):
                assert button.region.height == 1
                assert pane.content_region.contains_region(button.region)
                assert button.label.cell_length + 2 <= button.size.width
            assert cancel.region.x - app.query_one("#build-button").region.right == 1

    asyncio.run(flow())


@pytest.mark.parametrize("source", ["search", "playlist", "build", "auth", "radio", "settings"])
def test_failure_paths_keep_status_and_notify(monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    async def flow() -> None:
        app = BesterYTMApp()
        async with app.run_test():
            notify = Mock()
            monkeypatch.setattr(app, "notify", notify)
            if source == "search":
                app._show_search_failure("Failed; retry.")
            elif source == "playlist":
                app._finish_playlist_load_error("Failed; retry.", app._queue_load_id)
            elif source == "build":
                app._build_cancel = Event()
                app.build_in_progress = True
                app._report_build_failure("Failed; retry.", app._build_cancel)
            elif source == "auth":
                app._finish_auth_status("Failed; retry.", app._auth_status_request_id, error=True)
            elif source == "radio":
                app._radio_poll_video_id = "radio:bytefm"
                app._finish_radio_poll("radio:bytefm", None, "Failed; retry.")
            else:
                monkeypatch.setattr(
                    "bester_ytm.tui_playback.save_transition_settings",
                    Mock(side_effect=ConfigError("Failed; retry.")),
                )
                app.action_cycle_transition()
            assert "Failed; retry." in str(app.query_one("#status").content)
            assert notify.call_args.kwargs == {"severity": "error"}

    asyncio.run(flow())


@pytest.mark.parametrize("operation", ["single", "marked", "album", "similar"])
def test_queued_songs_during_radio_end_with_station_hint(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    async def flow() -> None:
        app = BesterYTMApp()
        app.playback = FakePlayback(current="radio:bytefm")
        app.playlist_video_ids = ["radio:bytefm"]
        song = SongCandidate(video_id="song", title="Song")
        statuses: list[str] = []
        monkeypatch.setattr(app, "_set_status", statuses.append)
        monkeypatch.setattr(app, "_render_queue", AsyncMock())
        monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: work.close())
        if operation == "single":
            await app._queue_or_play_candidate(song)
        elif operation == "marked":
            monkeypatch.setattr(app, "_selected_candidates_in_display_order", lambda: [song])
            monkeypatch.setattr(app, "_clear_selection_markers", Mock())
            await app._queue_selected_results()
        elif operation == "album":
            monkeypatch.setattr(app, "_reset_album_tree_markers", Mock())
            monkeypatch.setattr(app, "_clear_selection_markers", Mock())
            await app._add_candidates_to_queue([song])
        else:
            app._finish_add_similar([song], "codex")
        assert statuses[-1].endswith("Press n to leave the station.")
        assert app.playback.current_video_id == "radio:bytefm"
        assert app.playback.queue == ["song"]

    asyncio.run(flow())
