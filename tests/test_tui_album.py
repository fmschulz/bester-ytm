from __future__ import annotations

import asyncio

from bester_ytm import tui
from bester_ytm.playback import PlaybackStatus
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.search_query import SearchItem
from bester_ytm.tui_album import AlbumTree
from bester_ytm.ytm_client import PlaylistSnapshot, YTMClientError

ALBUMS = {
    "b1": PlaylistSnapshot(
        playlist_id="AP1",
        title="Master of Puppets",
        video_ids=["t1", "t2"],
        tracks=[
            SongCandidate(video_id="t1", title="Battery", artists=["Metallica"]),
            SongCandidate(video_id="t2", title="Master of Puppets", artists=["Metallica"]),
        ],
    ),
    "b2": PlaylistSnapshot(
        playlist_id="AP2",
        title="Ride the Lightning",
        video_ids=["t3"],
        tracks=[SongCandidate(video_id="t3", title="Fight Fire with Fire", artists=["Metallica"])],
    ),
}


class FakeClient:
    def __init__(self) -> None:
        self.album_calls: list[str] = []

    def structured_search(self, parsed, limit: int = 25) -> list[SearchItem]:
        return [
            SearchItem(item_type="album", title="Master of Puppets", subtitle="Metallica",
                       browse_id="b1", year="1986"),
            SearchItem(item_type="album", title="Ride the Lightning", subtitle="Metallica",
                       browse_id="b2", year="1984"),
        ]

    def get_album(self, browse_id: str) -> PlaylistSnapshot:
        self.album_calls.append(browse_id)
        return ALBUMS[browse_id]


class FakePlayback:
    def __init__(self) -> None:
        self.queue: list[str] = []
        self.current_video_id: str | None = None
        self.running = False

    def status(self) -> PlaybackStatus:
        return PlaybackStatus(
            running=self.running,
            current_video_id=self.current_video_id if self.running else None,
            queue_size=len(self.queue),
        )

    def replace_queue(self, video_ids: list[str]) -> None:
        self.queue = list(video_ids)
        self.running = False
        self.current_video_id = None

    def enqueue(self, video_ids: list[str]) -> None:
        self.queue.extend(video_ids)

    def play_queue(self) -> PlaybackStatus:
        self.current_video_id = self.queue.pop(0)
        self.running = True
        return self.status()


def _labels(node) -> list[str]:
    return [str(child.label) for child in node.children]


def _inline_workers(app, monkeypatch) -> None:
    """Seam for run_test flows: thread workers run inline, coroutines as tasks."""

    def run_worker(work, **kwargs):
        if asyncio.iscoroutine(work):
            return asyncio.get_running_loop().create_task(work)
        return work()

    monkeypatch.setattr(app, "run_worker", run_worker)
    monkeypatch.setattr(app, "call_from_thread", lambda fn, *args: fn(*args))


def test_album_search_populates_tree_and_lazy_loads(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    async def run() -> None:
        app = tui.BesterYTMApp()
        async with app.run_test() as pilot:
            app.client = FakeClient()
            app.playback = FakePlayback()
            _inline_workers(app, monkeypatch)
            await app._search("album:metallica")
            await pilot.pause()

            tree = app.query_one("#album-tree", AlbumTree)
            assert tree.display is True
            assert app.query_one("#results").display is False
            assert _labels(tree.root) == [
                "Master of Puppets - Metallica (1986)",
                "Ride the Lightning - Metallica (1984)",
            ]
            # No songs fetched until an album is expanded.
            assert app.client.album_calls == []

            tree.focus()
            await pilot.pause()
            await pilot.press("enter")  # expand the first album
            await pilot.pause()

            first = tree.root.children[0]
            assert first.is_expanded
            assert _labels(first) == ["Metallica - Battery", "Metallica - Master of Puppets"]
            assert app.client.album_calls == ["b1"]

            # Switching to a song search hides the tree again.
            app.client = FakeClient()
            await app._search("song:metallica")
            await pilot.pause()
            assert tree.display is False
            assert app.query_one("#results").display is True

    asyncio.run(run())


def test_select_song_then_add_queues_only_that_song(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    async def run() -> None:
        app = tui.BesterYTMApp()
        async with app.run_test() as pilot:
            app.client = FakeClient()
            app.playback = FakePlayback()
            _inline_workers(app, monkeypatch)
            await app._search("album:metallica")
            await pilot.pause()
            tree = app.query_one("#album-tree", AlbumTree)
            tree.focus()
            await pilot.pause()
            await pilot.press("enter")  # expand album 1
            await pilot.pause()
            await pilot.press("down")  # cursor -> Battery
            await pilot.pause()

            app.action_toggle_select()
            assert app.selected_result_video_ids == {"t1"}
            assert str(tree.cursor_node.label) == "* Metallica - Battery"

            await app.action_add_to_queue()
            await pilot.pause()
            # Nothing was playing, so the one selected song starts immediately.
            assert app.playback.current_video_id == "t1"
            assert app.selected_result_video_ids == set()
            assert str(tree.cursor_node.label) == "Metallica - Battery"

    asyncio.run(run())


def test_album_space_shift_space_and_enter_queue_selected_range(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    async def run() -> None:
        app = tui.BesterYTMApp()
        async with app.run_test() as pilot:
            app.client = FakeClient()
            app.playback = FakePlayback()
            _inline_workers(app, monkeypatch)
            await app._search("album:metallica")
            await pilot.pause()
            tree = app.query_one("#album-tree", AlbumTree)
            tree.focus()
            await pilot.pause()

            await pilot.press("enter")  # expand album 1
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")  # expand album 2 before selecting
            await pilot.press("up")
            await pilot.press("up")  # cursor -> Battery (t1)
            await pilot.pause()

            await pilot.press("space")
            await pilot.pause()
            assert app.selected_result_video_ids == {"t1"}
            assert app.result_selection_anchor_video_id == "t1"

            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("down")  # cursor -> Fight Fire with Fire (t3)
            await pilot.press("shift+space")
            await pilot.pause()

            assert app.selected_result_video_ids == {"t1", "t2", "t3"}

            await pilot.press("enter")
            await pilot.pause()

            assert app.playback.current_video_id == "t1"
            assert app.playback.queue == ["t2", "t3"]
            assert app.selected_result_video_ids == set()
            assert app.result_selection_anchor_video_id is None

    asyncio.run(run())


def test_enter_expands_collapsed_album_while_selection_is_active(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    async def run() -> None:
        app = tui.BesterYTMApp()
        async with app.run_test() as pilot:
            app.client = FakeClient()
            app.playback = FakePlayback()
            _inline_workers(app, monkeypatch)
            await app._search("album:metallica")
            await pilot.pause()
            tree = app.query_one("#album-tree", AlbumTree)
            tree.focus()
            await pilot.pause()

            await pilot.press("enter")  # expand album 1
            await pilot.press("down")  # cursor -> Battery (t1)
            await pilot.press("space")
            await pilot.press("down")
            await pilot.press("down")  # cursor -> collapsed album 2
            await pilot.press("enter")
            await pilot.pause()

            second = tree.root.children[1]
            assert second.is_expanded
            assert _labels(second) == ["Metallica - Fight Fire with Fire"]
            assert app.selected_result_video_ids == {"t1"}
            assert app.playback.current_video_id is None

    asyncio.run(run())


def test_add_on_album_node_queues_all_its_songs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    async def run() -> None:
        app = tui.BesterYTMApp()
        async with app.run_test() as pilot:
            app.client = FakeClient()
            app.playback = FakePlayback()
            _inline_workers(app, monkeypatch)
            app.playback.running = True
            app.playback.current_video_id = "playing"
            await app._search("album:metallica")
            await pilot.pause()
            tree = app.query_one("#album-tree", AlbumTree)
            tree.focus()
            await pilot.pause()
            # Cursor is on the first album node; add the whole album without expanding.
            await app.action_add_to_queue()
            await pilot.pause()

            assert app.playback.queue == ["t1", "t2"]
            assert app.client.album_calls == ["b1"]

    asyncio.run(run())


def test_play_album_replaces_existing_queue(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    async def run() -> None:
        app = tui.BesterYTMApp()
        async with app.run_test() as pilot:
            app.client = FakeClient()
            app.playback = FakePlayback()
            _inline_workers(app, monkeypatch)
            app.playback.queue = ["old1", "old2"]
            app.playlist_video_ids = ["old1", "old2"]
            await app._search("album:metallica")
            await pilot.pause()
            tree = app.query_one("#album-tree", AlbumTree)
            tree.focus()
            await pilot.pause()
            # Cursor sits on the first album node; shift+a plays it now.
            await app.action_play_album()
            await pilot.pause()

            assert app.playback.current_video_id == "t1"
            assert app.playback.queue == ["t2"]
            assert app.playlist_title == "Master of Puppets"

    asyncio.run(run())


def test_play_album_from_song_starts_at_that_song(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    async def run() -> None:
        app = tui.BesterYTMApp()
        async with app.run_test() as pilot:
            app.client = FakeClient()
            app.playback = FakePlayback()
            _inline_workers(app, monkeypatch)
            await app._search("album:metallica")
            await pilot.pause()
            tree = app.query_one("#album-tree", AlbumTree)
            tree.focus()
            await pilot.pause()
            await pilot.press("enter")  # expand album 1
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("down")  # cursor -> Master of Puppets (t2)
            await pilot.pause()

            await app.action_play_album()
            await pilot.pause()
            # Plays the album from the highlighted song, clearing what was there.
            assert app.playback.current_video_id == "t2"
            assert app.playback.queue == []
            assert app.playlist_title == "Master of Puppets"

    asyncio.run(run())


def test_add_on_single_song_node_queues_one(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    async def run() -> None:
        app = tui.BesterYTMApp()
        async with app.run_test() as pilot:
            app.client = FakeClient()
            app.playback = FakePlayback()
            _inline_workers(app, monkeypatch)
            app.playback.running = True
            app.playback.current_video_id = "playing"
            await app._search("album:metallica")
            await pilot.pause()
            tree = app.query_one("#album-tree", AlbumTree)
            tree.focus()
            await pilot.pause()
            await pilot.press("enter")  # expand album 1
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("down")  # cursor -> Master of Puppets (t2)
            await pilot.pause()
            assert str(tree.cursor_node.label) == "Metallica - Master of Puppets"

            await app.action_add_to_queue()
            await pilot.pause()
            assert app.playback.queue == ["t2"]

    asyncio.run(run())


def test_album_expand_error_sets_status_and_allows_retry(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    class FlakyClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        def get_album(self, browse_id: str) -> PlaylistSnapshot:
            if self.fail:
                raise YTMClientError("album fetch failed")
            return super().get_album(browse_id)

    async def run() -> None:
        app = tui.BesterYTMApp()
        async with app.run_test() as pilot:
            app.client = FlakyClient()
            app.playback = FakePlayback()
            _inline_workers(app, monkeypatch)
            statuses: list[str] = []
            monkeypatch.setattr(app, "_set_status", statuses.append)
            await app._search("album:metallica")
            await pilot.pause()
            tree = app.query_one("#album-tree", AlbumTree)
            tree.focus()
            await pilot.pause()

            await pilot.press("enter")  # expand album 1; the fetch fails
            await pilot.pause()

            first = tree.root.children[0]
            assert statuses[-1] == "album fetch failed"
            assert _labels(first) == []

            app.client.fail = False
            await pilot.press("enter")  # collapse
            await pilot.press("enter")  # expand again retries the fetch
            await pilot.pause()

            assert _labels(first) == [
                "Metallica - Battery",
                "Metallica - Master of Puppets",
            ]

    asyncio.run(run())
