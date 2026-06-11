"""Now-playing queue highlight: cursor follows playback, no per-tick re-render."""

from __future__ import annotations

import asyncio

from bester_ytm import tui
from bester_ytm.playback import PlaybackStatus
from bester_ytm.playlist_plan import SongCandidate


def _item_label(item) -> str:
    children = item.children if len(item.children) else item._pending_children
    return str(children[0].render())


class FakeListView:
    """Queue stub that honors `.index`, like Textual's ListView cursor."""

    def __init__(self) -> None:
        self.items: list = []
        self.index = 0

    @property
    def highlighted_child(self):
        if not self.items or self.index is None:
            return None
        return self.items[self.index]

    async def clear(self) -> None:
        self.items.clear()
        self.index = 0

    async def append(self, item) -> None:
        self.items.append(item)


class YieldingFakeListView(FakeListView):
    """clear/append yield to the event loop so concurrent renders genuinely interleave."""

    async def clear(self) -> None:
        await asyncio.sleep(0)
        await super().clear()

    async def append(self, item) -> None:
        await asyncio.sleep(0)
        await super().append(item)


class FakeStatic:
    def __init__(self) -> None:
        self.value = ""

    def update(self, value: str) -> None:
        self.value = value


class FakePlayback:
    def __init__(self, current: str | None, queue: list[str]) -> None:
        self.current_video_id = current
        self.queue = list(queue)

    def status(self) -> PlaybackStatus:
        return PlaybackStatus(
            running=self.current_video_id is not None,
            current_video_id=self.current_video_id,
            queue_size=len(self.queue),
        )


def _make_app(monkeypatch, playback, queue) -> tuple[tui.BesterYTMApp, list]:
    widgets = {"#queue": queue, "#track": FakeStatic(), "#queue-title": FakeStatic()}
    workers: list = []
    app = tui.BesterYTMApp()
    app.playback = playback  # type: ignore[assignment]
    app.candidates_by_video_id = {
        "v1": SongCandidate(video_id="v1", title="One", artists=["A"]),
        "v2": SongCandidate(video_id="v2", title="Two", artists=["B"]),
        "v3": SongCandidate(video_id="v3", title="Three", artists=["C"]),
    }
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(
        app, "_query_optional", lambda selector, widget_type=None: widgets.get(selector)
    )
    monkeypatch.setattr(app, "_set_status", lambda message: None)
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: workers.append(work))
    return app, workers


def test_render_queue_marks_playing_track_without_moving_cursor(monkeypatch) -> None:
    """Q1: the playing track gets the NOW/.playing marker; the cursor is not yanked onto it."""
    queue = FakeListView()
    app, _ = _make_app(monkeypatch, FakePlayback("v2", ["v3"]), queue)
    app.playlist_video_ids = ["v1", "v2", "v3"]

    asyncio.run(app._render_queue())

    labels = [_item_label(item) for item in queue.items]
    assert labels[1].startswith("NOW")
    assert queue.items[1].has_class("playing")
    assert queue.index == 0  # nothing selected -> cursor stays at the default row, not the NOW row
    assert app._rendered_now_playing_id == "v2"


def test_cursor_stays_put_when_playback_advances(monkeypatch) -> None:
    """Only the .playing marker follows playback; the user's selection cursor does not jump."""
    queue = FakeListView()
    playback = FakePlayback("v1", ["v2", "v3"])
    app, workers = _make_app(monkeypatch, playback, queue)
    app.playlist_video_ids = ["v1", "v2", "v3"]
    app.playback_was_active = True

    asyncio.run(app._render_queue())
    queue.index = 2  # user navigates to the last track

    playback.current_video_id = "v2"  # playback advances to track 2
    app._refresh_playback()
    asyncio.run(workers[0])

    labels = [_item_label(item) for item in queue.items]
    assert labels[1].startswith("NOW")  # marker moved to the new playing track
    assert queue.items[1].has_class("playing")
    assert queue.index == 2  # cursor did NOT jump to the playing track
    assert queue.items[queue.index].video_id == "v3"


def test_refresh_playback_reschedules_render_when_track_changes(monkeypatch) -> None:
    """Q2: current_video_id changes between ticks -> exactly one re-render scheduled."""
    queue = FakeListView()
    playback = FakePlayback("v1", ["v2", "v3"])
    app, workers = _make_app(monkeypatch, playback, queue)
    app.playlist_video_ids = ["v1", "v2", "v3"]
    app.playback_was_active = True

    asyncio.run(app._render_queue())
    assert app._rendered_now_playing_id == "v1"

    playback.current_video_id = "v2"
    app._refresh_playback()

    assert len(workers) == 1
    asyncio.run(workers[0])

    labels = [_item_label(item) for item in queue.items]
    assert labels[1].startswith("NOW")
    assert app._rendered_now_playing_id == "v2"


def test_refresh_playback_does_not_reschedule_when_track_unchanged(monkeypatch) -> None:
    """Q3: two ticks with the same current track schedule zero re-renders."""
    queue = FakeListView()
    playback = FakePlayback("v1", ["v2", "v3"])
    app, workers = _make_app(monkeypatch, playback, queue)
    app.playlist_video_ids = ["v1", "v2", "v3"]
    app.playback_was_active = True

    asyncio.run(app._render_queue())

    app._refresh_playback()
    app._refresh_playback()

    assert workers == []


def test_concurrent_renders_do_not_duplicate_rows(monkeypatch) -> None:
    """Pressing n renders directly while the tick schedules another; rows must not double up."""
    queue = YieldingFakeListView()
    playback = FakePlayback("v1", ["v2", "v3"])
    app, _ = _make_app(monkeypatch, playback, queue)
    app.playlist_video_ids = ["v1", "v2", "v3"]

    async def drive() -> None:
        await asyncio.gather(app._render_queue(), app._render_queue())

    asyncio.run(drive())

    assert [item.video_id for item in queue.items] == ["v1", "v2", "v3"]


def test_move_queue_track_keeps_cursor_on_moved_track(monkeypatch) -> None:
    """Q4a: after a move, the cursor stays on the moved track, not the playing one."""
    queue = FakeListView()
    playback = FakePlayback("v1", ["v2", "v3"])
    app, _ = _make_app(monkeypatch, playback, queue)
    app.playlist_video_ids = ["v1", "v2", "v3"]
    app.selected_queue_video_id = "v3"

    asyncio.run(app.action_move_queue_track_up())

    assert app.playlist_video_ids == ["v1", "v3", "v2"]
    assert queue.items[queue.index].video_id == "v3"


def test_remove_from_queue_keeps_cursor_at_edited_position(monkeypatch) -> None:
    """Q4b: after a remove, the cursor stays at the edited slot, not the playing track."""
    queue = FakeListView()
    playback = FakePlayback("v1", ["v2", "v3"])
    app, _ = _make_app(monkeypatch, playback, queue)
    app.playlist_video_ids = ["v1", "v2", "v3"]
    app.selected_queue_video_id = "v2"

    asyncio.run(app.action_remove_from_queue())

    assert app.playlist_video_ids == ["v1", "v3"]
    # v3 now occupies the removed slot; the cursor follows it, not the playing v1.
    assert queue.items[queue.index].video_id == "v3"
