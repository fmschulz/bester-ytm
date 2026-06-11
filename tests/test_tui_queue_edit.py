from __future__ import annotations

import asyncio

import pytest

from bester_ytm.playback import PlaybackStatus
from bester_ytm.playlist_plan import PlannedTrack, PlaylistPlan, SongCandidate
from bester_ytm.stores import LocalPlaylistStore
from bester_ytm.tui import BesterYTMApp


class FakeStatic:
    def __init__(self) -> None:
        self.value = ""

    def update(self, value: str) -> None:
        self.value = value


class FakeListView:
    def __init__(self) -> None:
        self.items = []

    async def clear(self) -> None:
        self.items.clear()

    async def append(self, item) -> None:
        self.items.append(item)


class FakePlayback:
    def __init__(self, current: str | None = None, queue: list[str] | None = None) -> None:
        self.current_video_id = current
        self.queue = queue or []
        self.enqueued: list[str] = []
        self.replaced: list[str] | None = None

    def status(self) -> PlaybackStatus:
        return PlaybackStatus(
            running=self.current_video_id is not None,
            current_video_id=self.current_video_id,
            queue_size=len(self.queue),
        )

    def enqueue(self, video_ids: list[str]) -> None:
        self.enqueued.extend(video_ids)
        self.queue.extend(video_ids)

    def replace_queue(self, video_ids: list[str]) -> None:
        self.replaced = list(video_ids)
        self.queue = list(video_ids)
        self.current_video_id = None


def _candidate(video_id: str) -> SongCandidate:
    return SongCandidate(video_id=video_id, title=video_id.upper(), artists=["Band"])


def _resolved_plan(video_ids: list[str]) -> PlaylistPlan:
    tracks = []
    for video_id in video_ids:
        track = PlannedTrack(
            artist="Band",
            title=video_id.upper(),
            reason="test",
            query=f"Band {video_id}",
            candidates=[_candidate(video_id)],
        )
        track.selected_video_id = video_id
        tracks.append(track)
    return PlaylistPlan(id="plan-9", name="AI Mix", target_count=len(tracks), planned_tracks=tracks)


def _make_app(monkeypatch, tmp_path, playback) -> tuple[BesterYTMApp, dict, list[str]]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    widgets = {
        "#queue": FakeListView(),
        "#track": FakeStatic(),
        "#queue-title": FakeStatic(),
    }
    statuses: list[str] = []
    app = BesterYTMApp()
    app.playback = playback
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(
        app, "_query_optional", lambda selector, widget_type=None: widgets.get(selector)
    )
    monkeypatch.setattr(app, "_set_status", statuses.append)
    return app, widgets, statuses


def test_built_plan_loads_into_queue_when_idle(monkeypatch, tmp_path) -> None:
    playback = FakePlayback()
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)

    asyncio.run(app._load_plan_into_queue(_resolved_plan(["v1", "v2"]), "plan saved."))

    assert playback.replaced == ["v1", "v2"]
    assert app.playlist_video_ids == ["v1", "v2"]
    assert app.playlist_title == "AI Mix"
    assert app.active_local_playlist_id == "ai-mix"
    assert LocalPlaylistStore().load("ai-mix").video_ids == ["v1", "v2"]
    assert "Created local playlist 'AI Mix'" in statuses[-1]
    assert "press Space to play" in statuses[-1]
    assert "d removes" in statuses[-1]


def test_built_plan_becomes_new_playlist_while_playing(monkeypatch, tmp_path) -> None:
    playback = FakePlayback(current="now", queue=["old1", "old2"])
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)
    app.playlist_video_ids = ["now", "old1", "old2"]
    app.playlist_title = "Old Mix"

    asyncio.run(app._load_plan_into_queue(_resolved_plan(["v1"]), "plan saved."))

    assert playback.enqueued == []
    assert playback.queue == ["v1"]
    assert playback.current_video_id == "now"
    assert app.playlist_video_ids == ["now", "v1"]
    assert app.playlist_title == "AI Mix"
    assert app.active_local_playlist_id == "ai-mix"
    assert LocalPlaylistStore().load("ai-mix").video_ids == ["v1"]
    assert "Created local playlist 'AI Mix'" in statuses[-1]
    assert "queued after the current song" in statuses[-1]


def test_clear_queue_keeps_the_playing_track(monkeypatch, tmp_path) -> None:
    playback = FakePlayback(current="now", queue=["v1", "v2"])
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)
    app.playlist_video_ids = ["now", "v1", "v2"]

    asyncio.run(app.action_clear_queue())

    assert playback.queue == []
    assert app.playlist_video_ids == ["now"]
    assert statuses[-1] == "Queue cleared. The playing track keeps playing."


def test_clear_queue_when_idle_empties_everything(monkeypatch, tmp_path) -> None:
    playback = FakePlayback(current=None, queue=["v1"])
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)
    app.playlist_video_ids = ["v1"]
    app.playlist_title = "AI Mix"

    asyncio.run(app.action_clear_queue())

    assert playback.queue == []
    assert app.playlist_video_ids == []
    assert app.playlist_title == "Queue"
    assert statuses[-1] == "Queue cleared."

    asyncio.run(app.action_clear_queue())
    assert statuses[-1] == "The queue is already empty."


def test_loading_a_plan_prefills_the_save_name(monkeypatch, tmp_path) -> None:
    playback = FakePlayback()
    app, widgets, _ = _make_app(monkeypatch, tmp_path, playback)
    name_input = FakeStatic()
    name_input.value = ""
    widgets["#playlist-name"] = name_input

    asyncio.run(app._load_plan_into_queue(_resolved_plan(["v1"]), "plan saved."))

    assert name_input.value == "AI Mix"


def test_remove_from_queue_updates_playlist_and_playback(monkeypatch, tmp_path) -> None:
    playback = FakePlayback(current="now", queue=["v1", "v2"])
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)
    app.playlist_video_ids = ["now", "v1", "v2"]
    app.selected_queue_video_id = "v1"

    asyncio.run(app.action_remove_from_queue())

    assert app.playlist_video_ids == ["now", "v2"]
    assert playback.queue == ["v2"]
    assert statuses[-1] == "Removed v1 from the queue."


def test_cannot_remove_the_playing_track(monkeypatch, tmp_path) -> None:
    playback = FakePlayback(current="now", queue=["v1"])
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)
    app.playlist_video_ids = ["now", "v1"]
    app.selected_queue_video_id = "now"

    asyncio.run(app.action_remove_from_queue())

    assert app.playlist_video_ids == ["now", "v1"]
    assert "Cannot remove the playing track" in statuses[-1]


def test_move_queue_track_up_keeps_playback_order_in_sync(monkeypatch, tmp_path) -> None:
    playback = FakePlayback(current="now", queue=["v1", "v2", "v3"])
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)
    app.playlist_video_ids = ["now", "v1", "v2", "v3"]
    app.selected_queue_video_id = "v3"

    asyncio.run(app.action_move_queue_track_up())

    assert app.playlist_video_ids == ["now", "v1", "v3", "v2"]
    assert playback.queue == ["v1", "v3", "v2"]
    assert statuses[-1] == "Moved v3 up."


def test_move_queue_track_down_at_end_is_a_noop(monkeypatch, tmp_path) -> None:
    playback = FakePlayback(current=None, queue=["v1", "v2"])
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)
    app.playlist_video_ids = ["v1", "v2"]
    app.selected_queue_video_id = "v2"

    asyncio.run(app.action_move_queue_track_down())

    assert app.playlist_video_ids == ["v1", "v2"]


def test_save_queue_as_local_playlist(monkeypatch, tmp_path) -> None:
    playback = FakePlayback(current=None, queue=[])
    app, _, statuses = _make_app(monkeypatch, tmp_path, playback)
    app.playlist_video_ids = ["v1", "v2"]
    app.playlist_title = "AI Mix"
    app.candidates_by_video_id = {"v1": _candidate("v1"), "v2": _candidate("v2")}

    app.action_save_queue_playlist()

    saved = LocalPlaylistStore().load("ai-mix")
    assert saved.video_ids == ["v1", "v2"]
    assert "Saved 2 track(s) to local playlist 'AI Mix'" in statuses[-1]
    assert app.active_local_playlist_id == "ai-mix"


def test_removing_a_track_and_saving_persists_the_removal(monkeypatch, tmp_path) -> None:
    playback = FakePlayback(current=None, queue=["v1", "v2", "v3"])
    app, _, _ = _make_app(monkeypatch, tmp_path, playback)
    app.playlist_video_ids = ["v1", "v2", "v3"]
    app.playlist_title = "AI Mix"
    app.candidates_by_video_id = {
        "v1": _candidate("v1"),
        "v2": _candidate("v2"),
        "v3": _candidate("v3"),
    }
    app.action_save_queue_playlist()

    app.selected_queue_video_id = "v2"
    asyncio.run(app.action_remove_from_queue())
    app.action_save_queue_playlist()

    saved = LocalPlaylistStore().load("ai-mix")
    assert saved.video_ids == ["v1", "v3"]


def test_save_empty_queue_reports_nothing_to_save(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path, FakePlayback())
    app.playlist_video_ids = []

    app.action_save_queue_playlist()

    assert statuses[-1] == "The queue is empty; nothing to save."


def test_second_build_is_rejected_while_one_runs(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path, FakePlayback())
    app.build_in_progress = True

    asyncio.run(app.action_build_playlist())

    assert statuses[-1] == "A playlist build is already running; wait for it to finish."


@pytest.mark.parametrize(
    ("key", "action"),
    [
        ("d", "remove_from_queue"),
        ("k", "move_queue_track_up"),
        ("j", "move_queue_track_down"),
        ("w", "save_queue_playlist"),
    ],
)
def test_queue_edit_bindings(key: str, action: str) -> None:
    from textual.binding import Binding

    actions = {
        (b.key if isinstance(b, Binding) else b[0]): (
            b.action if isinstance(b, Binding) else b[1]
        )
        for b in BesterYTMApp.BINDINGS
    }
    assert actions[key] == action
