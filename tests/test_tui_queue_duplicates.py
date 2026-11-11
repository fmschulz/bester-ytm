"""Queue rows keep their positions when video IDs repeat."""

from __future__ import annotations

import asyncio
import warnings

import pytest
from fakes import FakeListView, FakePlayback, FakeStatic

from bester_ytm.playback import PlaybackStatus
from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_rows import QueueRow


def _app(
    monkeypatch: pytest.MonkeyPatch, current: str | None, upcoming: list[str]
) -> tuple[BesterYTMApp, FakeListView[QueueRow], list[str]]:
    app = BesterYTMApp()
    app.playback = FakePlayback(current, upcoming)
    app.playlist_video_ids = ["a", "b", "a", "c"]
    queue: FakeListView[QueueRow] = FakeListView()
    widgets = {"#queue": queue, "#track": FakeStatic()}
    statuses: list[str] = []
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(
        app, "_query_optional", lambda selector, widget_type=None: widgets.get(selector)
    )
    monkeypatch.setattr(app, "_set_status", statuses.append)
    monkeypatch.setattr(app, "_refresh_playback", lambda status=None: None)
    monkeypatch.setattr(app, "_focus_context", lambda: "queue")
    return app, queue, statuses


def test_only_current_occurrence_has_play_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    app, queue, _ = _app(monkeypatch, "a", ["c"])
    asyncio.run(app._render_queue())

    assert [row.has_class("playing") for row in queue.items] == [False, False, True, False]
    assert [row.has_class("played") for row in queue.items] == [True, True, False, False]
    assert [str(row.label).startswith("▶") for row in queue.items] == [False, False, True, False]


@pytest.mark.parametrize("index", [0, 2])
def test_remove_only_highlighted_copy(monkeypatch: pytest.MonkeyPatch, index: int) -> None:
    app, queue, _ = _app(monkeypatch, "b", ["a", "c"])
    app.selected_queue_index = index

    asyncio.run(app.action_remove_from_queue())

    assert app.playlist_video_ids == (["b", "a", "c"] if index == 0 else ["a", "b", "c"])
    assert app.playback.queue == (["a", "c"] if index == 0 else ["c"])
    assert queue.index == index


def test_playing_copy_cannot_be_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _, statuses = _app(monkeypatch, "a", ["c"])
    app.selected_queue_index = 2
    asyncio.run(app.action_remove_from_queue())
    assert app.playlist_video_ids == ["a", "b", "a", "c"]
    assert "Cannot remove the playing track" in statuses[-1]


@pytest.mark.parametrize("delta", [-1, 1])
def test_move_highlighted_copy_and_cursor(monkeypatch: pytest.MonkeyPatch, delta: int) -> None:
    app, queue, _ = _app(monkeypatch, "a", ["b", "a", "c"])
    app.selected_queue_index = 2

    asyncio.run(app._move_queue_track(delta))

    expected = ["a", "a", "b", "c"] if delta == -1 else ["a", "b", "c", "a"]
    assert app.playlist_video_ids == expected
    assert app.playback.queue == expected[1:]
    assert queue.index == app.selected_queue_index == 2 + delta


@pytest.mark.parametrize("index", [0, 2])
def test_play_from_selected_copy(monkeypatch: pytest.MonkeyPatch, index: int) -> None:
    app, queue, _ = _app(monkeypatch, "b", ["a", "c"])
    asyncio.run(app._render_queue())

    asyncio.run(app._play_queue_item(queue.items[index]))

    assert app.playback.current_video_id == "a"
    assert app.playback.queue == (["b", "a", "c"] if index == 0 else ["c"])
    assert queue.items[index].has_class("playing")


def test_enter_can_play_later_copy_of_current_song(monkeypatch: pytest.MonkeyPatch) -> None:
    app, queue, statuses = _app(monkeypatch, "a", ["b", "a", "c"])
    asyncio.run(app._render_queue())
    asyncio.run(app._play_queue_item(queue.items[2]))
    assert app.playback.queue == ["c"]
    assert statuses[-1] == "Playing."


def test_cursor_keeps_second_copy_across_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    app, queue, _ = _app(monkeypatch, "b", ["a", "c"])
    asyncio.run(app._render_queue())
    queue.index = 2
    asyncio.run(app._render_queue())
    assert queue.index == 2


def test_shuffle_keeps_played_and_current_copies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("random.shuffle", lambda items: items.reverse())
    app, _, _ = _app(monkeypatch, "a", ["c", "d"])
    app.playlist_video_ids.append("d")
    asyncio.run(app.action_shuffle_queue())
    assert app.playlist_video_ids == ["a", "b", "a", "d", "c"]
    assert app.playback.queue == ["d", "c"]


def test_consecutive_copies_refresh_the_play_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    app, queue, _ = _app(monkeypatch, "a", ["a", "c"])
    app.playlist_video_ids = ["a", "a", "c"]
    asyncio.run(app._render_queue())
    app.playback.queue = ["c"]
    scheduled = []
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: scheduled.append(work))

    app._refresh_now_playing_marker("a")

    assert len(scheduled) == 1
    asyncio.run(scheduled[0]())
    assert [row.has_class("playing") for row in queue.items] == [False, True, False]


def test_cancelled_queue_render_does_not_leave_an_unawaited_coroutine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, _ = _app(monkeypatch, "a", ["b", "a", "c"])
    scheduled: list = []
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: scheduled.append(work))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        app._refresh_now_playing_marker("a")
        scheduled.clear()

    assert not [warning for warning in caught if "was never awaited" in str(warning.message)]


def test_marker_falls_back_to_id_when_queues_are_out_of_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, queue, _ = _app(monkeypatch, "b", ["unrelated"])
    asyncio.run(app._render_queue())
    assert [row.has_class("playing") for row in queue.items] == [False, True, False, False]


@pytest.mark.parametrize(
    ("index", "delta", "expected", "upcoming"),
    [
        (2, -1, ["a", "a", "b", "c"], ["b", "c"]),
        (2, 1, ["a", "b", "c", "a"], []),
        (1, 1, ["a", "a", "b", "c"], ["b", "c"]),
        (3, -1, ["a", "b", "c", "a"], []),
    ],
)
def test_moves_across_playing_row_keep_queues_in_step(
    monkeypatch: pytest.MonkeyPatch,
    index: int,
    delta: int,
    expected: list[str],
    upcoming: list[str],
) -> None:
    app, queue, _ = _app(monkeypatch, "a", ["c"])
    app.selected_queue_index = index
    asyncio.run(app._move_queue_track(delta))
    assert app.playlist_video_ids == expected
    assert app.playback.queue == upcoming
    assert queue.index == index + delta


def test_focused_queue_position_wins_over_remembered_row(monkeypatch: pytest.MonkeyPatch) -> None:
    app, queue, _ = _app(monkeypatch, "b", ["a", "c"])
    asyncio.run(app._render_queue())
    app.selected_queue_index = 0
    queue.index = 2
    monkeypatch.setattr(BesterYTMApp, "focused", queue)
    queue.id = "queue"
    asyncio.run(app.action_remove_from_queue())
    assert app.playlist_video_ids == ["a", "b", "c"]
    assert app.playback.queue == ["c"]


@pytest.mark.parametrize("current", [None, "c"])
@pytest.mark.parametrize(("index", "expected"), [(0, ["b", "c"]), (1, ["a", "c"]), (2, ["a", "b"])])
def test_remove_from_finished_playlist_keeps_queue_empty(
    monkeypatch: pytest.MonkeyPatch, current: str | None, index: int, expected: list[str]
) -> None:
    app, _, _ = _app(monkeypatch, current, [])
    app.playback.running = False
    app.playlist_video_ids = ["a", "b", "c"]
    app.selected_queue_index = index

    asyncio.run(app.action_remove_from_queue())

    assert app.playlist_video_ids == expected
    assert app.playback.queue == []


@pytest.mark.parametrize("current", [None, "b"])
@pytest.mark.parametrize(("delta", "expected"), [(-1, ["b", "a", "c"]), (1, ["a", "c", "b"])])
def test_move_in_finished_playlist_keeps_queue_empty(
    monkeypatch: pytest.MonkeyPatch, current: str | None, delta: int, expected: list[str]
) -> None:
    app, _, _ = _app(monkeypatch, current, [])
    app.playback.running = False
    app.playlist_video_ids = ["a", "b", "c"]
    app.selected_queue_index = 1

    asyncio.run(app._move_queue_track(delta))

    assert app.playlist_video_ids == expected
    assert app.playback.queue == []


@pytest.mark.parametrize("current", [None, "b"])
@pytest.mark.parametrize(
    ("index", "expected", "upcoming"),
    [
        (0, ["b", "c", "d"], ["c", "d"]),
        (1, ["a", "c", "d"], ["c", "d"]),
        (3, ["a", "b", "c"], ["c"]),
    ],
)
def test_remove_from_stopped_playlist_keeps_upcoming_suffix(
    monkeypatch: pytest.MonkeyPatch,
    current: str | None,
    index: int,
    expected: list[str],
    upcoming: list[str],
) -> None:
    app, _, _ = _app(monkeypatch, current, ["c", "d"])
    app.playback.running = False
    app.playlist_video_ids = ["a", "b", "c", "d"]
    app.selected_queue_index = index

    asyncio.run(app.action_remove_from_queue())

    assert app.playlist_video_ids == expected
    assert app.playback.queue == upcoming


@pytest.mark.parametrize("current", [None, "b"])
@pytest.mark.parametrize(
    ("index", "delta", "expected", "upcoming"),
    [
        (0, 1, ["b", "a", "c", "d"], ["c", "d"]),
        (1, 1, ["a", "c", "b", "d"], ["b", "d"]),
        (2, -1, ["a", "c", "b", "d"], ["b", "d"]),
        (2, 1, ["a", "b", "d", "c"], ["d", "c"]),
    ],
)
def test_move_in_stopped_playlist_keeps_boundary(
    monkeypatch: pytest.MonkeyPatch,
    current: str | None,
    index: int,
    delta: int,
    expected: list[str],
    upcoming: list[str],
) -> None:
    app, _, _ = _app(monkeypatch, current, ["c", "d"])
    app.playback.running = False
    app.playlist_video_ids = ["a", "b", "c", "d"]
    app.selected_queue_index = index

    asyncio.run(app._move_queue_track(delta))

    assert app.playlist_video_ids == expected
    assert app.playback.queue == upcoming


@pytest.mark.parametrize("current", [None, "b"])
def test_remove_out_of_step_edits_one_copy_by_id(
    monkeypatch: pytest.MonkeyPatch, current: str | None
) -> None:
    app, _, _ = _app(monkeypatch, current, ["unrelated", "a", "a"])
    app.selected_queue_index = 2

    asyncio.run(app.action_remove_from_queue())

    assert app.playlist_video_ids == ["a", "b", "c"]
    assert app.playback.queue == ["unrelated", "a"]


@pytest.mark.parametrize("current", [None, "b"])
def test_remove_out_of_step_leaves_unmatched_queue_alone(
    monkeypatch: pytest.MonkeyPatch, current: str | None
) -> None:
    app, _, _ = _app(monkeypatch, current, ["unrelated"])
    app.selected_queue_index = 3

    asyncio.run(app.action_remove_from_queue())

    assert app.playlist_video_ids == ["a", "b", "a"]
    assert app.playback.queue == ["unrelated"]


@pytest.mark.parametrize("current", [None, "b"])
@pytest.mark.parametrize(
    ("upcoming", "expected"),
    [
        (["a", "unrelated", "c", "a"], ["c", "unrelated", "a", "a"]),
        (["unrelated", "a", "a"], ["unrelated", "a", "a"]),
    ],
)
def test_move_out_of_step_swaps_one_copy_of_each_id(
    monkeypatch: pytest.MonkeyPatch,
    current: str | None,
    upcoming: list[str],
    expected: list[str],
) -> None:
    app, _, _ = _app(monkeypatch, current, upcoming)
    app.selected_queue_index = 2

    asyncio.run(app.action_move_queue_track_down())

    assert app.playlist_video_ids == ["a", "b", "c", "a"]
    assert app.playback.queue == expected


def test_move_uses_boundary_after_playback_status_advances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, _ = _app(monkeypatch, "a", ["b", "a", "c"])
    app.selected_queue_index = 2
    status = app.playback.status

    def advance() -> PlaybackStatus:
        app.playback.current_video_id = "b"
        app.playback.queue = ["a", "c"]
        monkeypatch.setattr(app.playback, "status", status)
        return status()

    monkeypatch.setattr(app.playback, "status", advance)

    asyncio.run(app.action_move_queue_track_down())

    assert app.playlist_video_ids == ["a", "b", "c", "a"]
    assert app.playback.queue == ["c", "a"]
