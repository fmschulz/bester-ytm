"""YouTube requests report outcomes and keep changes within the loaded view."""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fakes import FakeListView, FakePlayback

from bester_ytm.config import ConfigError
from bester_ytm.tui import BesterYTMApp
from bester_ytm.ytm_client import AuthStatus, YTMClientError


def _app(monkeypatch: pytest.MonkeyPatch) -> tuple[BesterYTMApp, list, list[str], Mock]:
    app = BesterYTMApp()
    app.playback = FakePlayback("a", ["b", "c"])
    app.playlist_video_ids = ["a", "b", "c"]
    app.active_youtube_playlist_id = "PL1"
    app.playlist_title = "Mix"
    widgets = {"#results": FakeListView(), "#queue": FakeListView()}
    statuses: list[str] = []
    workers: list = []
    client = Mock()
    client.auth_status.return_value = AuthStatus(
        authenticated=True, backend="browser", message="OK", library_playlists_seen=2
    )
    client.remove_playlist_item.return_value = 1
    monkeypatch.setattr("bester_ytm.tui.YTMClient", lambda **kwargs: client)
    monkeypatch.setattr("bester_ytm.tui_metadata.YTMClient", lambda **kwargs: client)
    monkeypatch.setattr(app, "_set_status", statuses.append)
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: workers.append((work, kwargs)))
    monkeypatch.setattr(app, "_render_queue", AsyncMock())
    monkeypatch.setattr(
        app, "_query_optional", lambda selector, widget_type=None: widgets.get(selector)
    )

    def call_from_thread(callback: Callable, *args: object) -> None:
        workers.append((partial(callback, *args), {}))

    monkeypatch.setattr(app, "call_from_thread", call_from_thread)
    return app, workers, statuses, client


def _drain(workers: list) -> None:
    while workers:
        work, _ = workers.pop(0)
        result = work() if callable(work) else work
        if inspect.isawaitable(result):
            asyncio.run(result)


def test_auth_check_returns_before_request_and_reports_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, workers, statuses, client = _app(monkeypatch)
    asyncio.run(app.action_auth_status())
    client.auth_status.assert_not_called()
    assert statuses == ["Checking YouTube login..."]
    assert workers[0][1]["thread"] is True
    _drain(workers)
    assert statuses[-1] == "Auth True via browser; library playlists seen 2."


@pytest.mark.parametrize("error", [ConfigError("no login"), YTMClientError("offline")])
def test_auth_worker_reports_errors(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    app, workers, statuses, client = _app(monkeypatch)
    client.auth_status.side_effect = error
    asyncio.run(app.action_auth_status())
    _drain(workers)
    assert statuses[-1] == str(error)


def test_new_auth_check_supersedes_old_result(monkeypatch: pytest.MonkeyPatch) -> None:
    app, workers, statuses, client = _app(monkeypatch)
    asyncio.run(app.action_auth_status())
    work, _ = workers.pop(0)
    work()
    asyncio.run(app.action_auth_status())
    client.auth_status.return_value = AuthStatus(
        authenticated=False, backend="browser", message="Expired"
    )
    _drain(workers)
    assert statuses == [
        "Checking YouTube login...",
        "Checking YouTube login...",
        "Auth False via browser; library playlists seen 0.",
    ]


@pytest.mark.parametrize("stale", [False, True])
def test_youtube_removal_returns_before_request_and_checks_queue(
    monkeypatch: pytest.MonkeyPatch, stale: bool
) -> None:
    app, workers, statuses, client = _app(monkeypatch)
    asyncio.run(app._remove_from_youtube_playlist("PL1", "b"))
    client.remove_playlist_item.assert_not_called()
    assert statuses == ["Removing track from YouTube playlist 'Mix'..."]
    assert workers[0][1]["thread"] is True
    if stale:
        app.active_youtube_playlist_id = None
        app.playlist_video_ids = ["b", "new"]
        app.playback.queue = ["b", "new"]
    _drain(workers)
    client.remove_playlist_item.assert_called_once_with("PL1", "b")
    assert app.playlist_video_ids == (["b", "new"] if stale else ["a", "c"])
    assert app.playback.queue == (["b", "new"] if stale else ["c"])
    assert statuses[-1] == "Removed track from YouTube playlist 'Mix'."


@pytest.mark.parametrize("stale", [False, True])
def test_youtube_delete_keeps_confirmation_and_ignores_new_listing(
    monkeypatch: pytest.MonkeyPatch, stale: bool
) -> None:
    app, workers, statuses, client = _app(monkeypatch)
    item = SimpleNamespace(playlist_id="PL1", playlist_title="Mix", remove=AsyncMock())
    app._query_optional("#results").items.append(item)
    asyncio.run(app._delete_youtube_playlist(item, "PL1"))
    assert "Press d again" in statuses[-1]
    assert workers == []
    asyncio.run(app._delete_youtube_playlist(item, "PL1"))
    client.delete_playlist.assert_not_called()
    assert statuses[-1] == "Deleting YouTube playlist 'Mix'..."
    assert workers[0][1]["thread"] is True
    if stale:
        app._results_load_id += 1
        app._query_optional("#results").items.clear()
    _drain(workers)
    client.delete_playlist.assert_called_once_with("PL1")
    assert item.remove.await_count == (0 if stale else 1)
    assert app._pending_playlist_delete is None
    assert statuses[-1] == "Deleted YouTube playlist 'Mix'."


@pytest.mark.parametrize("action", ["auth", "remove", "delete"])
def test_youtube_calls_run_on_a_real_worker_thread(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    app, workers, _, client = _app(monkeypatch)
    ui_thread = threading.get_ident()
    calls: list[int] = []

    def make_client(*, authenticated: bool) -> Mock:
        assert authenticated
        calls.append(threading.get_ident())
        assert calls[-1] != ui_thread
        return client

    monkeypatch.setattr("bester_ytm.tui.YTMClient", make_client)
    monkeypatch.setattr("bester_ytm.tui_metadata.YTMClient", make_client)
    if action == "auth":
        asyncio.run(app.action_auth_status())
    elif action == "remove":
        asyncio.run(app._remove_from_youtube_playlist("PL1", "b"))
    else:
        item = SimpleNamespace(playlist_id="PL1", playlist_title="Mix", remove=AsyncMock())
        app._query_optional("#results").items.append(item)
        asyncio.run(app._delete_youtube_playlist(item, "PL1"))
        asyncio.run(app._delete_youtube_playlist(item, "PL1"))
    work, options = workers.pop(0)
    assert options["thread"] is True
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(work).result()
    _drain(workers)
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["load", "upcoming", "order"])
def test_removal_updates_same_playlist_after_queue_changes(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    app, workers, statuses, client = _app(monkeypatch)
    asyncio.run(app._remove_from_youtube_playlist("PL1", "b"))
    if change == "load":
        app._supersede_queue_load()
    elif change == "order":
        app.playlist_video_ids = ["b", "a", "c"]
    else:
        app.playback.current_video_id = "b"
        app.playback.queue = ["c"]
    _drain(workers)
    assert app.playlist_video_ids == ["a", "c"]
    assert app.playback.queue == ["c"]
    assert statuses[-1] == "Removed track from YouTube playlist 'Mix'."


@pytest.mark.parametrize("playlist_id", [None, "PL2"])
def test_removal_reports_success_without_changing_another_playlist(
    monkeypatch: pytest.MonkeyPatch, playlist_id: str | None
) -> None:
    app, workers, statuses, _ = _app(monkeypatch)
    asyncio.run(app._remove_from_youtube_playlist("PL1", "b"))
    app.active_youtube_playlist_id = playlist_id

    _drain(workers)

    assert app.playlist_video_ids == ["a", "b", "c"]
    assert app.playback.queue == ["b", "c"]
    app._render_queue.assert_not_awaited()
    assert statuses[-1] == "Removed track from YouTube playlist 'Mix'."


@pytest.mark.parametrize("removed", [0, ConfigError("no login"), YTMClientError("offline")])
@pytest.mark.parametrize("change", ["none", "upcoming", "playlist"])
def test_removal_worker_reports_failure_without_changing_queue(
    monkeypatch: pytest.MonkeyPatch, removed: int | Exception, change: str
) -> None:
    app, workers, statuses, client = _app(monkeypatch)
    if isinstance(removed, Exception):
        client.remove_playlist_item.side_effect = removed
    else:
        client.remove_playlist_item.return_value = removed
    asyncio.run(app._remove_from_youtube_playlist("PL1", "b"))
    if change == "upcoming":
        app.playback.current_video_id = "b"
        app.playback.queue = ["c"]
    elif change == "playlist":
        app.active_youtube_playlist_id = "PL2"
    _drain(workers)
    assert app.playlist_video_ids == ["a", "b", "c"]
    assert app.playback.queue == (["c"] if change == "upcoming" else ["b", "c"])
    expected = (
        str(removed)
        if isinstance(removed, Exception)
        else "Track is not in YouTube playlist 'Mix'."
    )
    assert statuses[-1] == expected


def test_removal_reports_success_after_a_load_during_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, workers, statuses, _ = _app(monkeypatch)

    async def new_load() -> None:
        app._supersede_queue_load()
        statuses.append("Loading a new queue...")

    monkeypatch.setattr(app, "_render_queue", new_load)
    asyncio.run(app._remove_from_youtube_playlist("PL1", "b"))
    _drain(workers)
    assert statuses == [
        "Removing track from YouTube playlist 'Mix'...",
        "Loading a new queue...",
        "Removed track from YouTube playlist 'Mix'.",
    ]


def test_delete_reports_success_after_a_new_listing_during_remove(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, workers, statuses, _ = _app(monkeypatch)

    async def new_listing() -> None:
        app._results_load_id += 1
        statuses.append("Loading playlists...")

    item = SimpleNamespace(playlist_id="PL1", playlist_title="Mix", remove=new_listing)
    app._query_optional("#results").items.append(item)
    asyncio.run(app._delete_youtube_playlist(item, "PL1"))
    asyncio.run(app._delete_youtube_playlist(item, "PL1"))
    _drain(workers)
    assert statuses == [
        "Press d again to permanently delete 'Mix' from your YouTube account.",
        "Deleting YouTube playlist 'Mix'...",
        "Loading playlists...",
        "Deleted YouTube playlist 'Mix'.",
    ]


@pytest.mark.parametrize("error", [None, ConfigError("no login"), YTMClientError("offline")])
@pytest.mark.parametrize("change", ["load", "row", "view"])
def test_delete_reports_outcome_without_touching_old_listing(
    monkeypatch: pytest.MonkeyPatch, error: Exception | None, change: str
) -> None:
    app, workers, statuses, client = _app(monkeypatch)
    client.delete_playlist.side_effect = error
    item = SimpleNamespace(playlist_id="PL1", playlist_title="Mix", remove=AsyncMock())
    results = app._query_optional("#results")
    results.items.append(item)
    asyncio.run(app._delete_youtube_playlist(item, "PL1"))
    asyncio.run(app._delete_youtube_playlist(item, "PL1"))
    if change == "load":
        app._results_load_id += 1
    elif change == "row":
        results.items.clear()
    else:
        monkeypatch.setattr(app, "_query_optional", lambda *args: None)

    _drain(workers)

    item.remove.assert_not_awaited()
    assert statuses[-1] == (str(error) if error else "Deleted YouTube playlist 'Mix'.")
