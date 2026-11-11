"""List rebuilds mount one batch and discard superseded results."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

import pytest
from fakes import FakeInput, FakeListView, FakePlayback
from textual.widgets import ListItem

from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.search_query import parse_search_query, search_item_from_song
from bester_ytm.stores import FavoritesStore, LocalPlaylistStore
from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_rows import QueueRow, ResultRow
from bester_ytm.ytm_client import PlaylistSnapshot


class RecordingListView(FakeListView[ListItem]):
    """Record the rows exposed by each mount, including single-row mounts."""

    def __init__(self) -> None:
        super().__init__()
        self.mounts: list[list[ListItem]] = []

    async def append(self, item: ListItem) -> None:
        self.mounts.append([item])
        await super().append(item)

    async def extend(self, items: Iterable[ListItem]) -> None:
        rows = list(items)
        self.mounts.append(rows)
        await super().extend(rows)


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> BesterYTMApp:
    app = BesterYTMApp()
    widgets = {
        "#results": RecordingListView(),
        "#queue": RecordingListView(),
        "#search": FakeInput(),
    }
    monkeypatch.setattr(app, "playback", FakePlayback("v1", ["v2", "v3"]))
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(
        app, "_query_optional", lambda selector, widget_type=None: widgets.get(selector)
    )
    monkeypatch.setattr(app, "_set_status", lambda message: None)
    return app


def _tracks() -> list[SongCandidate]:
    return [SongCandidate(video_id=f"v{i}", title=f"Song {i}") for i in range(1, 4)]


def test_queue_mounts_rows_together_with_markers_and_cursor(app: BesterYTMApp) -> None:
    app.playlist_video_ids = [track.video_id for track in _tracks()]
    app.selected_queue_index = app.playlist_video_ids.index("v3")
    FavoritesStore().toggle(_tracks()[1])

    asyncio.run(app._render_queue())

    queue = app.query_one("#queue")
    assert len(queue.mounts) == 1
    assert [row.video_id for row in queue.items] == ["v1", "v2", "v3"]
    assert all(isinstance(row, QueueRow) for row in queue.items)
    assert [row.is_playing for row in queue.items] == [True, False, False]
    assert [row.is_favorite for row in queue.items] == [False, True, False]
    assert queue.highlighted_child.video_id == "v3"


def test_search_mounts_rows_together_in_order_and_focuses_results(app: BesterYTMApp) -> None:
    items = [search_item_from_song(track) for track in _tracks()]
    FavoritesStore().toggle(_tracks()[1])

    asyncio.run(app._show_search_results(parse_search_query("songs"), items, app._results_load_id))

    results = app.query_one("#results")
    assert len(results.mounts) == 1
    assert [row.candidate.video_id for row in results.items] == ["v1", "v2", "v3"]
    assert [row.favorite for row in results.items] == [False, True, False]
    assert app.candidates_by_video_id == {track.video_id: track for track in _tracks()}
    assert results.index == 0
    assert results.focus_calls == 1


def test_local_library_mounts_rows_together_and_keeps_named_cursor(app: BesterYTMApp) -> None:
    for name in ("First", "Second", "Third"):
        LocalPlaylistStore().add_track(name, _tracks()[0])

    asyncio.run(app._refresh_local_playlist_library("second"))

    results = app.query_one("#results")
    assert len(results.mounts) == 1
    assert [row.search_item.title for row in results.items] == ["First", "Second", "Third"]
    assert results.highlighted_child.search_item.playlist_id == "second"
    assert results.focus_calls == 0


def test_favorites_mount_marks_together_and_keep_cursor(app: BesterYTMApp) -> None:
    tracks = _tracks()
    for track in tracks:
        FavoritesStore().toggle(track)
    results = app.query_one("#results")
    results.items = [ResultRow(search_item_from_song(track)) for track in tracks]
    results.index = 1
    app._favorites_query = ""
    app.selected_result_video_ids = {"v1", "v3", "removed"}
    app.result_selection_anchor_video_id = "removed"

    asyncio.run(app._refresh_favorites_view(app._results_load_id))

    assert len(results.mounts) == 1
    assert [row.candidate.video_id for row in results.items] == ["v1", "v2", "v3"]
    assert [row.marked for row in results.mounts[0]] == [True, False, True]
    assert all(row.favorite for row in results.items)
    assert results.highlighted_child.candidate.video_id == "v2"
    assert app.selected_result_video_ids == {"v1", "v3"}
    assert app.result_selection_anchor_video_id == "v1"
    assert results.focus_calls == 0


def test_playlist_listing_mounts_local_then_remote_batches(
    app: BesterYTMApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("First", "Second", "Third"):
        LocalPlaylistStore().add_track(name, _tracks()[0])
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: None)
    asyncio.run(app.action_show_playlists())
    local_items = LocalPlaylistStore().search_items()
    remote = [
        PlaylistSnapshot(playlist_id=f"PL{i}", title=f"Remote {i}", track_count=i) for i in range(3)
    ]

    asyncio.run(app._append_youtube_playlists(local_items, remote, app._results_load_id))

    results = app.query_one("#results")
    assert [len(batch) for batch in results.mounts] == [3, 3]
    assert [row.playlist_id for row in results.items] == [
        "first",
        "second",
        "third",
        "PL0",
        "PL1",
        "PL2",
    ]
    assert results.focus_calls == 1


@pytest.mark.parametrize("kind", ["search", "playlists", "favorites"])
def test_superseded_results_never_mount(app: BesterYTMApp, kind: str) -> None:
    old_load_id = app._results_load_id
    app._results_load_id += 1
    app._favorites_query = ""
    if kind == "search":
        work = app._show_search_results(
            parse_search_query("songs"), [search_item_from_song(_tracks()[0])], old_load_id
        )
    elif kind == "playlists":
        work = app._append_youtube_playlists(
            [], [PlaylistSnapshot(playlist_id="old", title="Old")], old_load_id
        )
    else:
        FavoritesStore().toggle(_tracks()[0])
        work = app._refresh_favorites_view(old_load_id)

    asyncio.run(work)

    results = app.query_one("#results")
    assert results.items == []
    assert results.mounts == []
    assert results.focus_calls == 0


def test_favorites_superseded_during_clear_never_mount(
    app: BesterYTMApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = app.query_one("#results")
    app._favorites_query = ""
    FavoritesStore().toggle(_tracks()[0])

    async def supersede() -> None:
        app._results_load_id += 1
        await FakeListView.clear(results)

    monkeypatch.setattr(results, "clear", supersede)

    asyncio.run(app._refresh_favorites_view(app._results_load_id))

    assert results.items == []
    assert results.mounts == []
