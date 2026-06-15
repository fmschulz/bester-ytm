from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bester_ytm import tui
from bester_ytm.playback import PlaybackError, PlaybackStatus
from bester_ytm.playlist_plan import SongCandidate


class FakeListView:
    def __init__(self) -> None:
        self.items: list[object] = []
        self.highlighted_child: object | None = None

    async def clear(self) -> None:
        self.items.clear()

    async def append(self, item) -> None:
        self.items.append(item)


class FakeTransport:
    """Configurable playback fake; set error to make transport calls fail."""

    def __init__(self, running: bool = False, current: str | None = None) -> None:
        self.queue: list[str] = []
        self.current_video_id = current
        self.running = running
        self.paused = False
        self.error: PlaybackError | None = None
        self.enqueued: list[str] = []
        self.seeks: list[float] = []

    def status(self) -> PlaybackStatus:
        return PlaybackStatus(
            running=self.running,
            current_video_id=self.current_video_id if self.running else None,
            queue_size=len(self.queue),
            paused=self.paused,
        )

    def _maybe_fail(self) -> None:
        if self.error is not None:
            raise self.error

    def enqueue(self, video_ids: list[str]) -> None:
        self.enqueued.extend(video_ids)

    def replace_queue(self, video_ids: list[str]) -> None:
        self.queue = list(video_ids)
        self.current_video_id = None
        self.running = False

    def play_queue(self) -> PlaybackStatus:
        self._maybe_fail()
        self.current_video_id = self.queue.pop(0)
        self.running = True
        return self.status()

    def next(self) -> PlaybackStatus:
        return self.play_queue()

    def previous(self) -> PlaybackStatus:
        self._maybe_fail()
        self.current_video_id = "prev"
        self.running = True
        return self.status()

    def pause_resume(self) -> PlaybackStatus:
        self._maybe_fail()
        self.paused = not self.paused
        return self.status()

    def seek_relative(self, seconds: float) -> PlaybackStatus:
        self._maybe_fail()
        self.seeks.append(seconds)
        return self.status()

    def seek_absolute(self, seconds: float) -> PlaybackStatus:
        self._maybe_fail()
        self.seeks.append(seconds)
        return self.status()

    def change_volume(self, delta: float) -> PlaybackStatus:
        self._maybe_fail()
        return self.status()

    def toggle_mute(self) -> PlaybackStatus:
        self._maybe_fail()
        return self.status()


def _make_app(monkeypatch, tmp_path, playback) -> tuple[tui.BesterYTMApp, dict, list[str]]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    app = tui.BesterYTMApp()
    app.playback = playback  # type: ignore[assignment]
    widgets = {"#results": FakeListView(), "#queue": FakeListView()}
    statuses: list[str] = []
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(app, "_set_status", statuses.append)
    monkeypatch.setattr(app, "_refresh_playback", lambda status=None: None)
    return app, widgets, statuses


def test_play_selected_enqueues_when_already_playing(monkeypatch, tmp_path) -> None:
    playback = FakeTransport(running=True, current="v1")
    app, widgets, statuses = _make_app(monkeypatch, tmp_path, playback)
    candidate = SongCandidate(video_id="v2", title="Two", artists=["B"])
    widgets["#results"].highlighted_child = SimpleNamespace(candidate=candidate)

    asyncio.run(app.action_play_selected())

    assert playback.enqueued == ["v2"]
    assert app.playlist_video_ids == ["v2"]
    assert statuses[-1] == "Queued B - Two."


def test_play_selected_ignores_items_without_candidate(monkeypatch, tmp_path) -> None:
    app, widgets, statuses = _make_app(monkeypatch, tmp_path, FakeTransport())
    widgets["#results"].highlighted_child = SimpleNamespace()

    asyncio.run(app.action_play_selected())

    assert statuses == []


def test_play_selected_reports_playback_error(monkeypatch, tmp_path) -> None:
    playback = FakeTransport()
    playback.queue = ["v1"]
    playback.error = PlaybackError("mpv failed")
    app, widgets, statuses = _make_app(monkeypatch, tmp_path, playback)
    candidate = SongCandidate(video_id="v1", title="One", artists=["A"])
    widgets["#results"].highlighted_child = SimpleNamespace(candidate=candidate)

    asyncio.run(app.action_play_selected())

    assert statuses[-1] == "mpv failed"


def test_play_selected_routes_to_focused_queue_item(monkeypatch, tmp_path) -> None:
    playback = FakeTransport(running=True, current="v1")
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)
    focused = SimpleNamespace(
        id="queue", highlighted_child=SimpleNamespace(video_id="v1")
    )
    monkeypatch.setattr(tui.BesterYTMApp, "focused", focused, raising=False)

    asyncio.run(app.action_play_selected())

    assert statuses == ["Already playing this track."]


def test_pause_resume_with_nothing_to_play(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path, FakeTransport())

    asyncio.run(app.action_pause_resume())

    assert statuses == ["Nothing to play."]


def test_pause_resume_toggles_running_playback(monkeypatch, tmp_path) -> None:
    playback = FakeTransport(running=True, current="v1")
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    asyncio.run(app.action_pause_resume())
    asyncio.run(app.action_pause_resume())

    assert statuses == ["Paused.", "Playing."]


def test_pause_resume_reports_error_when_queue_start_fails(monkeypatch, tmp_path) -> None:
    playback = FakeTransport()
    playback.queue = ["v1"]
    playback.error = PlaybackError("mpv failed")
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    asyncio.run(app.action_pause_resume())

    assert statuses[-1] == "mpv failed"


def test_pause_resume_aborts_when_playlist_load_fails(monkeypatch, tmp_path) -> None:
    app, widgets, statuses = _make_app(monkeypatch, tmp_path, FakeTransport())
    widgets["#results"].highlighted_child = SimpleNamespace(playlist_id="PL1")

    async def fail_load(playlist_id: str) -> bool:
        assert playlist_id == "PL1"
        return False

    monkeypatch.setattr(app, "_load_playlist_queue", fail_load)

    asyncio.run(app.action_pause_resume())

    assert statuses == []


def test_next_track_reports_new_track(monkeypatch, tmp_path) -> None:
    playback = FakeTransport()
    playback.queue = ["v2"]
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    asyncio.run(app.action_next_track())

    assert app.playback_was_active is True
    assert statuses[-1] == "Next track."


def test_previous_track_success_and_error(monkeypatch, tmp_path) -> None:
    playback = FakeTransport()
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    asyncio.run(app.action_previous_track())
    assert statuses[-1] == "Previous track."

    playback.error = PlaybackError("no deck")
    asyncio.run(app.action_previous_track())
    assert statuses[-1] == "no deck"


def test_play_queue_item_falls_back_to_single_video(monkeypatch, tmp_path) -> None:
    playback = FakeTransport()
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    asyncio.run(app._play_queue_item(SimpleNamespace(video_id="solo")))

    assert playback.current_video_id == "solo"
    assert statuses[-1] == "Playing."


def test_play_queue_item_ignores_items_without_video_id(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path, FakeTransport())

    asyncio.run(app._play_queue_item(None))

    assert statuses == []


def test_play_queue_item_reports_playback_error(monkeypatch, tmp_path) -> None:
    playback = FakeTransport()
    playback.error = PlaybackError("mpv failed")
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    asyncio.run(app._play_queue_item(SimpleNamespace(video_id="v1")))

    assert statuses[-1] == "mpv failed"


def test_auto_advance_reports_error_and_clears_pending(monkeypatch, tmp_path) -> None:
    playback = FakeTransport()
    playback.queue = ["v2"]
    playback.error = PlaybackError("mpv failed")
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)
    app.playback_was_active = True
    app.auto_advance_pending = True

    asyncio.run(app._auto_advance())

    assert app.playback_was_active is False
    assert app.auto_advance_pending is False
    assert statuses[-1] == "mpv failed"


def test_seek_actions_send_relative_offsets(monkeypatch, tmp_path) -> None:
    playback = FakeTransport(running=True, current="v1")
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    app.action_seek_backward()
    app.action_seek_forward()
    app.action_seek_large_backward()
    app.action_seek_large_forward()

    assert playback.seeks == [-10, 10, -30, 30]
    assert statuses == [
        "Seeked back 10s.",
        "Seeked forward 10s.",
        "Seeked back 30s.",
        "Seeked forward 30s.",
    ]


def test_seek_helpers_report_errors(monkeypatch, tmp_path) -> None:
    playback = FakeTransport()
    playback.error = PlaybackError("ipc down")
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    app._seek_relative(10)
    app._seek_absolute(95)

    assert statuses == ["ipc down", "ipc down"]


def test_seek_absolute_reports_target_position(monkeypatch, tmp_path) -> None:
    playback = FakeTransport(running=True, current="v1")
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    app._seek_absolute(95)

    assert playback.seeks == [95]
    assert statuses == ["Seeked to 1:35."]


def test_mute_and_volume_report_errors(monkeypatch, tmp_path) -> None:
    playback = FakeTransport()
    playback.error = PlaybackError("ipc down")
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    app.action_mute()
    app._change_volume(5)

    assert statuses == ["ipc down", "ipc down"]


def test_mute_reports_state(monkeypatch, tmp_path) -> None:
    playback = FakeTransport(running=True, current="v1")
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    app.action_mute()

    assert statuses == ["Unmuted."]
