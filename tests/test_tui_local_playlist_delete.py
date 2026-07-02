from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bester_ytm import tui
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.search_query import SearchItem
from bester_ytm.stores import LocalPlaylist, LocalPlaylistStore


@pytest.fixture()
def store(tmp_path, monkeypatch) -> LocalPlaylistStore:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    store = LocalPlaylistStore()
    store.save(
        LocalPlaylist(
            id="yahoo",
            name="Yahoo",
            tracks=[SongCandidate(video_id="v1", title="One", artists=["A"])],
        )
    )
    return store


def test_load_missing_playlist_gives_actionable_error(store: LocalPlaylistStore) -> None:
    with pytest.raises(FileNotFoundError, match="No local playlist named 'nope'"):
        store.load("nope")


def test_delete_removes_file_and_returns_playlist(store: LocalPlaylistStore) -> None:
    playlist = store.delete("yahoo")

    assert playlist.name == "Yahoo"
    assert not store.path_for_id("yahoo").exists()
    with pytest.raises(FileNotFoundError, match="No local playlist named 'yahoo'"):
        store.delete("yahoo")


class FakeStatic:
    def __init__(self) -> None:
        self.value = ""

    def update(self, value: str) -> None:
        self.value = value


class FakeResultItem:
    def __init__(self, **attrs: object) -> None:
        self.removed = False
        for key, value in attrs.items():
            setattr(self, key, value)

    async def remove(self) -> None:
        self.removed = True


def _make_app(monkeypatch, item) -> tuple[tui.BesterYTMApp, FakeStatic]:
    status = FakeStatic()
    results = SimpleNamespace(highlighted_child=item)
    widgets = {"#results": results, "#status": status}
    app = tui.BesterYTMApp()
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(
        app, "_query_optional", lambda selector, widget_type=None: widgets.get(selector)
    )
    monkeypatch.setattr(app, "_focus_context", lambda: "results")
    return app, status


def _local_playlist_item(playlist_id: str = "yahoo", title: str = "Yahoo") -> FakeResultItem:
    search_item = SearchItem(
        item_type="local_playlist",
        title=title,
        source="local",
        playlist_id=playlist_id,
        track_count=1,
    )
    return FakeResultItem(search_item=search_item)


def test_d_deletes_local_playlist_only_after_second_press(
    monkeypatch, store: LocalPlaylistStore
) -> None:
    item = _local_playlist_item()
    app, status = _make_app(monkeypatch, item)
    app.active_local_playlist_id = "yahoo"

    asyncio.run(app.action_remove_from_queue())

    assert "Press d again" in status.value and "'Yahoo'" in status.value
    assert store.path_for_id("yahoo").exists()
    assert item.removed is False

    asyncio.run(app.action_remove_from_queue())

    assert not store.path_for_id("yahoo").exists()
    assert item.removed is True
    assert app.active_local_playlist_id is None
    assert "Deleted local playlist 'Yahoo'" in status.value


def test_any_other_action_rearms_the_local_delete_confirmation(
    monkeypatch, store: LocalPlaylistStore
) -> None:
    item = _local_playlist_item()
    app, status = _make_app(monkeypatch, item)

    asyncio.run(app.action_remove_from_queue())
    assert app._pending_playlist_delete == "yahoo"

    # Any action other than d (via key binding or button) disarms the confirm.
    asyncio.run(app.run_action("rate_down"))
    assert app._pending_playlist_delete is None

    asyncio.run(app.action_remove_from_queue())

    assert store.path_for_id("yahoo").exists()
    assert item.removed is False
    assert "Press d again" in status.value

    asyncio.run(app.action_remove_from_queue())

    assert not store.path_for_id("yahoo").exists()
    assert item.removed is True


def test_d_on_song_result_only_hints(monkeypatch, store: LocalPlaylistStore) -> None:
    search_item = SearchItem(item_type="song", title="A Song")
    app, status = _make_app(monkeypatch, FakeResultItem(search_item=search_item))

    asyncio.run(app.action_remove_from_queue())

    assert store.path_for_id("yahoo").exists()
    assert "d deletes the highlighted playlist" in status.value


class FakeYTMClient:
    deleted: list[str] = []
    error: Exception | None = None

    def __init__(self, authenticated: bool = True) -> None:
        pass

    def delete_playlist(self, playlist_id: str) -> None:
        if FakeYTMClient.error is not None:
            raise FakeYTMClient.error
        FakeYTMClient.deleted.append(playlist_id)


@pytest.fixture()
def fake_client(monkeypatch) -> type[FakeYTMClient]:
    FakeYTMClient.deleted = []
    FakeYTMClient.error = None
    monkeypatch.setattr("bester_ytm.tui_metadata.YTMClient", FakeYTMClient)
    return FakeYTMClient


def test_d_on_youtube_playlist_deletes_only_after_second_press(
    monkeypatch, store: LocalPlaylistStore, fake_client: type[FakeYTMClient]
) -> None:
    item = FakeResultItem(playlist_id="PL1", playlist_title="Road Trip")
    app, status = _make_app(monkeypatch, item)

    asyncio.run(app.action_remove_from_queue())

    assert "Press d again" in status.value and "'Road Trip'" in status.value
    assert fake_client.deleted == []
    assert item.removed is False

    asyncio.run(app.action_remove_from_queue())

    assert fake_client.deleted == ["PL1"]
    assert item.removed is True
    assert "Deleted YouTube playlist 'Road Trip'" in status.value


def test_moving_to_another_playlist_rearms_the_confirmation(
    monkeypatch, store: LocalPlaylistStore, fake_client: type[FakeYTMClient]
) -> None:
    first = FakeResultItem(playlist_id="PL1", playlist_title="One")
    app, status = _make_app(monkeypatch, first)

    asyncio.run(app.action_remove_from_queue())
    assert "Press d again" in status.value

    second = FakeResultItem(playlist_id="PL2", playlist_title="Two")
    app._query_optional("#results").highlighted_child = second

    asyncio.run(app.action_remove_from_queue())

    assert fake_client.deleted == []
    assert "Press d again" in status.value and "'Two'" in status.value


def test_youtube_delete_failure_surfaces_and_disarms(
    monkeypatch, store: LocalPlaylistStore, fake_client: type[FakeYTMClient]
) -> None:
    from bester_ytm.ytm_client import YTMClientError

    item = FakeResultItem(playlist_id="PL1", playlist_title="One")
    app, status = _make_app(monkeypatch, item)
    fake_client.error = YTMClientError("YouTube Data API returned 403 Forbidden")

    asyncio.run(app.action_remove_from_queue())
    asyncio.run(app.action_remove_from_queue())

    assert "403 Forbidden" in status.value
    assert item.removed is False
    assert app._pending_playlist_delete is None  # next press arms again, not deletes


def test_d_on_missing_playlist_reports_friendly_error(
    monkeypatch, store: LocalPlaylistStore
) -> None:
    item = _local_playlist_item(playlist_id="gone", title="Gone")
    app, status = _make_app(monkeypatch, item)

    asyncio.run(app.action_remove_from_queue())
    assert "Press d again" in status.value

    asyncio.run(app.action_remove_from_queue())

    assert "No local playlist named 'gone'" in status.value
    assert item.removed is False
