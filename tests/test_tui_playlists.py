import asyncio
from types import SimpleNamespace

import pytest

from bester_ytm import tui
from bester_ytm.playback import PlaybackError, PlaybackStatus
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.search_query import SearchItem
from bester_ytm.stores import LocalPlaylistStore, TrackMetadataStore
from bester_ytm.ytm_client import PlaylistSnapshot, YTMClientError


def _item_label(item) -> str:
    children = item.children if len(item.children) else item._pending_children
    return str(children[0].render())


class FakeListView:
    def __init__(self) -> None:
        self.items = []
        self.index = 0

    @property
    def highlighted_child(self):
        if not self.items:
            return None
        return self.items[self.index]

    async def clear(self) -> None:
        self.items.clear()
        self.index = 0

    async def append(self, item) -> None:
        self.items.append(item)

    def focus(self) -> None:
        pass


class FakeStatic:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def update(self, value: str) -> None:
        self.value = value


class FakeInput:
    def __init__(self, value: str = "") -> None:
        self.value = value


class FakeQueuePlayback:
    def __init__(self) -> None:
        self.queue = []
        self.current_video_id = None

    def status(self) -> PlaybackStatus:
        return PlaybackStatus(
            running=bool(self.current_video_id),
            current_video_id=self.current_video_id,
            queue_size=len(self.queue),
        )

    def replace_queue(self, video_ids: list[str]) -> None:
        self.queue = list(video_ids)

    def enqueue(self, video_ids: list[str]) -> None:
        self.queue.extend(video_ids)

    def play_queue(self) -> PlaybackStatus:
        self.current_video_id = self.queue.pop(0)
        return self.status()


def test_tui_show_playlists_uses_authenticated_library(monkeypatch, tmp_path) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FakeClient:
        def __init__(self, authenticated: bool = True) -> None:
            assert authenticated is True

        def list_playlists(self, limit: int = 25) -> list[PlaylistSnapshot]:
            return [
                PlaylistSnapshot(
                    playlist_id="PL1",
                    title="ByteFM Inspired 30",
                    track_count=30,
                )
            ]

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    app = tui.BesterYTMApp()
    list_view = FakeListView()
    statuses: list[str] = []

    monkeypatch.setattr(tui, "YTMClient", FakeClient)
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: list_view)
    monkeypatch.setattr(app, "_set_status", statuses.append)

    asyncio.run(app.action_show_playlists())

    assert len(list_view.items) == 1
    assert list_view.items[0].playlist_id == "PL1"
    assert statuses[-1] == "0 local + 1 YouTube playlist(s)."


def test_tui_show_playlists_includes_saved_local_playlists(monkeypatch, tmp_path) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FakeClient:
        def __init__(self, authenticated: bool = True) -> None:
            pass

        def list_playlists(self, limit: int = 25) -> list[PlaylistSnapshot]:
            return [PlaylistSnapshot(playlist_id="PL1", title="Remote", track_count=2)]

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    LocalPlaylistStore().add_track(
        "AI Mix", SongCandidate(video_id="v1", title="One", artists=["A"])
    )
    app = tui.BesterYTMApp()
    list_view = FakeListView()
    statuses: list[str] = []
    monkeypatch.setattr(tui, "YTMClient", FakeClient)
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: list_view)
    monkeypatch.setattr(app, "_set_status", statuses.append)

    asyncio.run(app.action_show_playlists())

    assert len(list_view.items) == 2
    local_item = list_view.items[0]
    assert local_item.search_item.item_type == "local_playlist"
    assert local_item.playlist_id == "ai-mix"
    assert list_view.items[1].playlist_id == "PL1"
    assert statuses[-1] == "1 local + 1 YouTube playlist(s)."


def test_tui_show_playlists_shows_locals_when_youtube_unavailable(
    monkeypatch, tmp_path
) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FailingClient:
        def __init__(self, authenticated: bool = True) -> None:
            pass

        def list_playlists(self, limit: int = 25) -> list[PlaylistSnapshot]:
            raise YTMClientError("not logged in")

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    LocalPlaylistStore().add_track(
        "AI Mix", SongCandidate(video_id="v1", title="One", artists=["A"])
    )
    app = tui.BesterYTMApp()
    list_view = FakeListView()
    statuses: list[str] = []
    monkeypatch.setattr(tui, "YTMClient", FailingClient)
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: list_view)
    monkeypatch.setattr(app, "_set_status", statuses.append)

    asyncio.run(app.action_show_playlists())

    assert len(list_view.items) == 1
    assert list_view.items[0].playlist_id == "ai-mix"
    assert statuses[-1] == (
        "1 local playlist(s). YouTube library unavailable: not logged in"
    )


def test_tui_selecting_playlist_loads_named_tracks(monkeypatch) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []
            self.highlighted_child = None

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FakeStatic:
        def __init__(self) -> None:
            self.value = ""

        def update(self, value: str) -> None:
            self.value = value

    class FakePlayback:
        def __init__(self) -> None:
            self.queue = []
            self.history = []
            self.current_video_id = None

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(
                running=bool(self.current_video_id),
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

        def replace_queue(self, video_ids: list[str]) -> None:
            self.queue = list(video_ids)

    class FakeClient:
        def __init__(self, authenticated: bool = True) -> None:
            assert authenticated is True

        def get_playlist(self, playlist_id: str) -> PlaylistSnapshot:
            assert playlist_id == "PL1"
            return PlaylistSnapshot(
                playlist_id="PL1",
                title="ByteFM Inspired 30",
                video_ids=["v1", "v2"],
                tracks=[
                    SongCandidate(video_id="v1", title="Myth", artists=["Beach House"]),
                    SongCandidate(video_id="v2", title="Silver Soul", artists=["Beach House"]),
                ],
            )

    results = FakeListView()
    selected = SimpleNamespace(playlist_id="PL1")
    results.highlighted_child = selected
    queue = FakeListView()
    track = FakeStatic()
    status = FakeStatic()
    widgets = {"#results": results, "#queue": queue, "#track": track, "#status": status}

    app = tui.BesterYTMApp()
    app.playback = FakePlayback()  # type: ignore[assignment]
    monkeypatch.setattr(tui, "YTMClient", FakeClient)
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    asyncio.run(app.action_play_selected())

    assert app.playback.queue == ["v1", "v2"]
    assert [_item_label(item) for item in queue.items] == [
        "01  Beach House - Myth",
        "02  Beach House - Silver Soul",
    ]
    assert status.value == "Loaded ByteFM Inspired 30: 2 track(s)."


def test_tui_space_on_selected_playlist_loads_and_starts_queue(monkeypatch) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []
            self.highlighted_child = None

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FakeStatic:
        def __init__(self) -> None:
            self.value = ""

        def update(self, value: str) -> None:
            self.value = value

    class FakePlayback:
        def __init__(self) -> None:
            self.queue = []
            self.current_video_id = None

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(
                running=bool(self.current_video_id),
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

        def replace_queue(self, video_ids: list[str]) -> None:
            self.queue = list(video_ids)

        def play_queue(self) -> PlaybackStatus:
            self.current_video_id = self.queue.pop(0)
            return PlaybackStatus(
                running=True,
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

    class FakeClient:
        def __init__(self, authenticated: bool = True) -> None:
            assert authenticated is True

        def get_playlist(self, playlist_id: str) -> PlaylistSnapshot:
            return PlaylistSnapshot(
                playlist_id=playlist_id,
                title="ByteFM Inspired 30",
                video_ids=["v1", "v2"],
                tracks=[
                    SongCandidate(video_id="v1", title="Myth", artists=["Beach House"]),
                    SongCandidate(video_id="v2", title="Silver Soul", artists=["Beach House"]),
                ],
            )

    results = FakeListView()
    selected = SimpleNamespace(playlist_id="PL1")
    results.highlighted_child = selected
    queue = FakeListView()
    track = FakeStatic()
    status = FakeStatic()
    widgets = {"#results": results, "#queue": queue, "#track": track, "#status": status}

    app = tui.BesterYTMApp()
    app.playback = FakePlayback()  # type: ignore[assignment]
    monkeypatch.setattr(tui, "YTMClient", FakeClient)
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    asyncio.run(app.action_pause_resume())

    assert app.playback.current_video_id == "v1"
    assert app.playback.queue == ["v2"]
    assert track.value == "Beach House - Myth"
    assert [_item_label(item) for item in queue.items] == [
        "NOW  Beach House - Myth",
        "02  Beach House - Silver Soul",
    ]
    assert status.value == "Playing."


def test_tui_queue_item_selection_jumps_to_that_song(monkeypatch) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FakeStatic:
        def __init__(self) -> None:
            self.value = ""

        def update(self, value: str) -> None:
            self.value = value

    class FakePlayback:
        def __init__(self) -> None:
            self.queue = ["v2", "v3"]
            self.current_video_id = "v1"

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(
                running=bool(self.current_video_id),
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

        def replace_queue(self, video_ids: list[str]) -> None:
            self.queue = list(video_ids)
            self.current_video_id = None

        def play_queue(self) -> PlaybackStatus:
            self.current_video_id = self.queue.pop(0)
            return PlaybackStatus(
                running=True,
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

    queue = FakeListView()
    track = FakeStatic()
    status = FakeStatic()
    widgets = {"#queue": queue, "#track": track, "#status": status}

    app = tui.BesterYTMApp()
    app.playback = FakePlayback()  # type: ignore[assignment]
    app.playlist_video_ids = ["v1", "v2", "v3"]
    app.candidates_by_video_id = {
        "v1": SongCandidate(video_id="v1", title="One", artists=["Artist A"]),
        "v2": SongCandidate(video_id="v2", title="Two", artists=["Artist B"]),
        "v3": SongCandidate(video_id="v3", title="Three", artists=["Artist C"]),
    }
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    asyncio.run(app._render_queue())
    asyncio.run(app._play_queue_item(queue.items[1]))

    assert app.playback.current_video_id == "v2"
    assert app.playback.queue == ["v3"]
    assert track.value == "Artist B - Two"
    assert [_item_label(item) for item in queue.items] == [
        "01  Artist A - One",
        "NOW  Artist B - Two",
        "03  Artist C - Three",
    ]
    assert status.value == "Playing."


def test_tui_auto_advances_when_playing_track_finishes(monkeypatch) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FakeStatic:
        def __init__(self) -> None:
            self.value = ""

        def update(self, value: str) -> None:
            self.value = value

    class FakePlayback:
        def __init__(self) -> None:
            self.queue = ["v2"]
            self.current_video_id = "v1"

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(
                running=self.current_video_id == "v2",
                current_video_id=self.current_video_id if self.current_video_id == "v2" else None,
                queue_size=len(self.queue),
            )

        def next(self) -> PlaybackStatus:
            self.current_video_id = self.queue.pop(0)
            return PlaybackStatus(
                running=True,
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

    queue = FakeListView()
    track = FakeStatic()
    status = FakeStatic()
    widgets = {"#queue": queue, "#track": track, "#status": status}

    app = tui.BesterYTMApp()
    app.playback = FakePlayback()  # type: ignore[assignment]
    app.playback_was_active = True
    app.playlist_video_ids = ["v1", "v2"]
    app.candidates_by_video_id = {
        "v1": SongCandidate(video_id="v1", title="One", artists=["Artist A"]),
        "v2": SongCandidate(video_id="v2", title="Two", artists=["Artist B"]),
    }
    workers = []

    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: workers.append(work))

    app._refresh_playback()
    assert app.auto_advance_pending is True

    asyncio.run(workers[0])

    assert app.playback.current_video_id == "v2"
    assert app.playback.queue == []
    assert app.playback_was_active is True
    assert app.auto_advance_pending is False
    assert track.value == "Artist B - Two"
    assert [_item_label(item) for item in queue.items] == [
        "01  Artist A - One",
        "NOW  Artist B - Two",
    ]
    assert status.value == "Playing next."


def test_tui_auto_advance_skips_unplayable_track(monkeypatch) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FakeStatic:
        def __init__(self) -> None:
            self.value = ""

        def update(self, value: str) -> None:
            self.value = value

    class FakePlayback:
        def __init__(self) -> None:
            self.queue = ["bad", "v3"]
            self.current_video_id = None

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(
                running=self.current_video_id == "v3",
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

        def next(self) -> PlaybackStatus:
            if self.queue[0] == "bad":
                raise PlaybackError("mpv exited before playback started")
            self.current_video_id = self.queue.pop(0)
            return PlaybackStatus(
                running=True,
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

    queue = FakeListView()
    track = FakeStatic()
    status = FakeStatic()
    widgets = {"#queue": queue, "#track": track, "#status": status}

    app = tui.BesterYTMApp()
    app.playback = FakePlayback()  # type: ignore[assignment]
    app.playback_was_active = True
    app.auto_advance_pending = True
    app.playlist_video_ids = ["bad", "v3"]
    app.candidates_by_video_id = {
        "v3": SongCandidate(video_id="v3", title="Three", artists=["Artist C"]),
    }
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    asyncio.run(app._auto_advance())

    assert app.playback.current_video_id == "v3"
    assert app.playback.queue == []
    assert app.playback_was_active is True
    assert app.auto_advance_pending is False
    assert status.value == "Playing next."


def test_tui_auto_advance_reports_error_when_no_track_is_playable(monkeypatch) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FakeStatic:
        def __init__(self) -> None:
            self.value = ""

        def update(self, value: str) -> None:
            self.value = value

    class FakePlayback:
        def __init__(self) -> None:
            self.queue = ["bad1", "bad2"]
            self.current_video_id = None

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(running=False, queue_size=len(self.queue))

        def next(self) -> PlaybackStatus:
            raise PlaybackError("mpv is not installed or not on PATH")

    widgets = {
        "#queue": FakeListView(),
        "#track": FakeStatic(),
        "#status": FakeStatic(),
    }

    app = tui.BesterYTMApp()
    app.playback = FakePlayback()  # type: ignore[assignment]
    app.playback_was_active = True
    app.auto_advance_pending = True
    app.playlist_video_ids = []
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    asyncio.run(app._auto_advance())

    assert app.playback.queue == []
    assert app.playback_was_active is False
    assert app.auto_advance_pending is False
    assert "mpv is not installed" in widgets["#status"].value


def test_tui_auto_advance_resets_pending_flag_on_unexpected_error(monkeypatch) -> None:
    class FakePlayback:
        queue = ["v2"]
        current_video_id = None

        def next(self) -> PlaybackStatus:
            raise RuntimeError("widget tree exploded")

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(running=False)

    app = tui.BesterYTMApp()
    app.playback = FakePlayback()  # type: ignore[assignment]
    app.auto_advance_pending = True

    with pytest.raises(RuntimeError, match="widget tree exploded"):
        asyncio.run(app._auto_advance())

    assert app.auto_advance_pending is False


def test_tui_shuffle_keeps_current_track_and_shuffles_upcoming(monkeypatch) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FakeStatic:
        def __init__(self) -> None:
            self.value = ""

        def update(self, value: str) -> None:
            self.value = value

    class FakePlayback:
        def __init__(self) -> None:
            self.queue = ["v2", "v3"]
            self.current_video_id = "v1"

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(
                running=True,
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

    queue = FakeListView()
    track = FakeStatic()
    status = FakeStatic()
    widgets = {"#queue": queue, "#track": track, "#status": status}

    app = tui.BesterYTMApp()
    app.playback = FakePlayback()  # type: ignore[assignment]
    app.playlist_video_ids = ["v1", "v2", "v3"]
    app.candidates_by_video_id = {
        "v1": SongCandidate(video_id="v1", title="One", artists=["Artist A"]),
        "v2": SongCandidate(video_id="v2", title="Two", artists=["Artist B"]),
        "v3": SongCandidate(video_id="v3", title="Three", artists=["Artist C"]),
    }

    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(tui.random, "shuffle", lambda items: items.reverse())

    asyncio.run(app.action_shuffle_queue())

    assert app.playlist_video_ids == ["v1", "v3", "v2"]
    assert app.playback.queue == ["v3", "v2"]
    assert [_item_label(item) for item in queue.items] == [
        "NOW  Artist A - One",
        "02  Artist C - Three",
        "03  Artist B - Two",
    ]
    assert status.value == "Shuffled 2 upcoming track(s)."


def test_tui_search_result_replaces_loaded_queue_before_playing(monkeypatch) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []
            self.highlighted_child = None

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FakeStatic:
        def __init__(self) -> None:
            self.value = ""

        def update(self, value: str) -> None:
            self.value = value

    class FakePlayback:
        def __init__(self) -> None:
            self.queue = ["playlist-v1"]
            self.current_video_id = None
            self.replaced_with = None

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(running=False, current_video_id=None, queue_size=len(self.queue))

        def replace_queue(self, video_ids: list[str]) -> None:
            self.replaced_with = list(video_ids)
            self.queue = list(video_ids)

        def play_queue(self) -> PlaybackStatus:
            self.current_video_id = self.queue.pop(0)
            return PlaybackStatus(
                running=True,
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

    candidate = SongCandidate(video_id="search-v1", title="Search Song", artists=["Artist"])
    results = FakeListView()
    results.highlighted_child = SimpleNamespace(candidate=candidate)
    queue = FakeListView()
    track = FakeStatic()
    status = FakeStatic()
    widgets = {"#results": results, "#queue": queue, "#track": track, "#status": status}

    app = tui.BesterYTMApp()
    app.playback = FakePlayback()  # type: ignore[assignment]
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    asyncio.run(app.action_play_selected())

    assert app.playback.replaced_with == ["search-v1"]
    assert app.playback.current_video_id == "search-v1"
    assert app.playback.queue == []
    assert track.value == "Artist - Search Song"
    assert status.value == "Playing."


def test_tui_playback_error_clears_stale_track(monkeypatch) -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.items = []

        async def clear(self) -> None:
            self.items.clear()

        async def append(self, item) -> None:
            self.items.append(item)

    class FakeStatic:
        def __init__(self) -> None:
            self.value = "Old Track"

        def update(self, value: str) -> None:
            self.value = value

    class FakePlayback:
        def __init__(self) -> None:
            self.queue = ["v2"]

        def next(self) -> PlaybackStatus:
            from bester_ytm.playback import PlaybackError

            raise PlaybackError("mpv failed")

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(running=False, current_video_id=None, queue_size=len(self.queue))

    queue = FakeListView()
    track = FakeStatic()
    status = FakeStatic()
    widgets = {"#queue": queue, "#track": track, "#status": status}

    app = tui.BesterYTMApp()
    app.current_candidate = SongCandidate(video_id="old", title="Old Track")
    app.playback = FakePlayback()  # type: ignore[assignment]
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    asyncio.run(app.action_next_track())

    assert app.current_candidate is None
    assert track.value == "No track playing."
    assert [_item_label(item) for item in queue.items] == ["01  v2"]
    assert status.value == "mpv failed"


def test_tui_keyboard_playlist_flow_loads_and_starts_queue(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    class FakePlayback:
        def __init__(self) -> None:
            self.queue = []
            self.current_video_id = None

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(
                running=bool(self.current_video_id),
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

        def replace_queue(self, video_ids: list[str]) -> None:
            self.queue = list(video_ids)

        def play_queue(self) -> PlaybackStatus:
            self.current_video_id = self.queue.pop(0)
            return PlaybackStatus(
                running=True,
                current_video_id=self.current_video_id,
                queue_size=len(self.queue),
            )

    class FakeClient:
        def __init__(self, authenticated: bool = True) -> None:
            self.authenticated = authenticated

        def list_playlists(self, limit: int = 25) -> list[PlaylistSnapshot]:
            assert self.authenticated is True
            return [PlaylistSnapshot(playlist_id="PL1", title="Mix", track_count=2)]

        def get_playlist(self, playlist_id: str) -> PlaylistSnapshot:
            assert self.authenticated is True
            return PlaylistSnapshot(
                playlist_id=playlist_id,
                title="Mix",
                video_ids=["v1", "v2"],
                tracks=[
                    SongCandidate(video_id="v1", title="One", artists=["Artist A"]),
                    SongCandidate(video_id="v2", title="Two", artists=["Artist B"]),
                ],
            )

    async def run_flow() -> None:
        app = tui.BesterYTMApp()
        app.playback = FakePlayback()  # type: ignore[assignment]
        async with app.run_test() as pilot:
            await pilot.press("ctrl+p")
            await pilot.pause()

            results = app.query_one("#results")
            assert results.index == 0
            assert results.highlighted_child.playlist_id == "PL1"

            await pilot.press("enter")
            await pilot.pause()

            queue = app.query_one("#queue")
            assert [_item_label(item) for item in queue.children] == [
                "01  Artist A - One",
                "02  Artist B - Two",
            ]

            await pilot.press("space")
            await pilot.pause()

            assert app.playback.current_video_id == "v1"
            assert app.playback.queue == ["v2"]
            assert str(app.query_one("#track").render()) == "Artist A - One"

    monkeypatch.setattr(tui, "YTMClient", FakeClient)

    asyncio.run(run_flow())


def test_tui_artist_albums_list_loads_album_into_queue(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    class FakeClient:
        def structured_search(self, parsed, limit: int = 25):
            assert parsed.kind == "artist"
            assert parsed.view == "albums"
            return [
                SearchItem(
                    item_type="album",
                    title="Against",
                    browse_id="album-1998",
                    year="1998",
                )
            ]

        def get_album(self, browse_id: str) -> PlaylistSnapshot:
            assert browse_id == "album-1998"
            return PlaylistSnapshot(
                playlist_id="album-1998",
                title="Against",
                video_ids=["v1", "v2"],
                tracks=[
                    SongCandidate(video_id="v1", title="Against", artists=["Sepultura"]),
                    SongCandidate(video_id="v2", title="Choke", artists=["Sepultura"]),
                ],
            )

    results = FakeListView()
    queue = FakeListView()
    status = FakeStatic()
    track = FakeStatic()
    track_metadata = FakeStatic()
    tags_input = FakeInput()
    playlist_name = FakeInput()
    queue_title = FakeStatic()
    widgets = {
        "#results": results,
        "#queue": queue,
        "#status": status,
        "#track": track,
        "#track-metadata": track_metadata,
        "#tags-input": tags_input,
        "#playlist-name": playlist_name,
        "#queue-title": queue_title,
    }

    app = tui.BesterYTMApp()
    app.client = FakeClient()  # type: ignore[assignment]
    app.playback = FakeQueuePlayback()  # type: ignore[assignment]
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    asyncio.run(app._search("artist:sepultura,albums"))
    # An artist album list stays in the results pane; Enter loads the album into the queue.
    asyncio.run(app.action_play_selected())

    assert app.playback.queue == ["v1", "v2"]
    assert app.playlist_title == "Against"
    assert app.selected_queue_video_id == "v1"
    assert [_item_label(item) for item in queue.items] == [
        "01  Sepultura - Against",
        "02  Sepultura - Choke",
    ]
    assert queue_title.value == "Against (2)"
    assert status.value == "Loaded album Against: 2 track(s)."


def test_tui_playlist_query_lists_and_loads_local_playlists(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    LocalPlaylistStore().add_track(
        "Local Metal",
        SongCandidate(video_id="v1", title="Territory", artists=["Sepultura"]),
    )

    results = FakeListView()
    queue = FakeListView()
    status = FakeStatic()
    track = FakeStatic()
    track_metadata = FakeStatic()
    tags_input = FakeInput()
    playlist_name = FakeInput()
    queue_title = FakeStatic()
    widgets = {
        "#results": results,
        "#queue": queue,
        "#status": status,
        "#track": track,
        "#track-metadata": track_metadata,
        "#tags-input": tags_input,
        "#playlist-name": playlist_name,
        "#queue-title": queue_title,
    }

    app = tui.BesterYTMApp()
    app.playback = FakeQueuePlayback()  # type: ignore[assignment]
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    asyncio.run(app._search("playlist:"))
    assert _item_label(results.items[0]) == "LOCAL PLAYLIST  Local Metal"

    asyncio.run(app.action_play_selected())

    assert app.playback.queue == ["v1"]
    assert app.active_local_playlist_id == "local-metal"
    assert playlist_name.value == "Local Metal"
    assert [_item_label(item) for item in queue.items] == ["01  Sepultura - Territory"]
    assert status.value == "Loaded local playlist Local Metal: 1 track(s)."


def test_tui_track_metadata_and_local_playlist_controls_target_highlighted_queue_song(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    results = FakeListView()
    queue = FakeListView()
    status = FakeStatic()
    track = FakeStatic()
    track_metadata = FakeStatic()
    tags_input = FakeInput("thrash, favorite")
    playlist_name = FakeInput("Selected Tracks")
    queue_title = FakeStatic()
    widgets = {
        "#results": results,
        "#queue": queue,
        "#status": status,
        "#track": track,
        "#track-metadata": track_metadata,
        "#tags-input": tags_input,
        "#playlist-name": playlist_name,
        "#queue-title": queue_title,
    }

    app = tui.BesterYTMApp()
    app.playback = FakeQueuePlayback()  # type: ignore[assignment]
    app.playlist_video_ids = ["v1", "v2"]
    app.candidates_by_video_id = {
        "v1": SongCandidate(video_id="v1", title="Against", artists=["Sepultura"]),
        "v2": SongCandidate(video_id="v2", title="Choke", artists=["Sepultura"]),
    }
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    asyncio.run(app._render_queue())
    queue.index = 1
    app.selected_queue_video_id = "v2"

    app.action_rate_up()
    app.action_save_tags()
    app.action_add_to_local_playlist()

    metadata = TrackMetadataStore().get("v2")
    playlist = LocalPlaylistStore().load("selected-tracks")

    assert metadata.rating == 1
    assert metadata.tags == ["thrash", "favorite"]
    assert playlist.video_ids == ["v2"]
    assert playlist.tracks[0].title == "Choke"

    asyncio.run(app.action_remove_from_playlist())

    assert LocalPlaylistStore().load("selected-tracks").video_ids == []
    assert status.value == "Removed from Selected Tracks."


def test_tui_local_playlist_add_uses_search_song_after_new_search(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    old_queue = FakeListView()
    old_queue_item = SimpleNamespace(video_id="old-v1")
    old_queue.items.append(old_queue_item)
    results = FakeListView()
    result_candidate = SongCandidate(
        video_id="search-v1",
        title="Kaiowas",
        artists=["Sepultura"],
    )
    results.items.append(SimpleNamespace(candidate=result_candidate))
    status = FakeStatic()
    playlist_name = FakeInput("Search Picks")
    widgets = {
        "#results": results,
        "#queue": old_queue,
        "#status": status,
        "#playlist-name": playlist_name,
    }

    app = tui.BesterYTMApp()
    app.candidates_by_video_id = {
        "old-v1": SongCandidate(video_id="old-v1", title="Old", artists=["Artist"]),
        "search-v1": result_candidate,
    }
    app.selected_queue_video_id = None
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])

    app.action_add_to_local_playlist()

    playlist = LocalPlaylistStore().load("search-picks")
    assert playlist.video_ids == ["search-v1"]
    assert status.value == "Added to Search Picks."
