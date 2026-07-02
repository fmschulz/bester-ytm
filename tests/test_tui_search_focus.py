"""Deferred load completions must not steal focus from a text input mid-typing."""

from __future__ import annotations

import asyncio

from textual.widgets import Input, TextArea

from bester_ytm import tui
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.search_query import SearchItem, search_item_from_song


class FakeListView:
    def __init__(self) -> None:
        self.items: list[object] = []
        self.focus_calls = 0

    async def clear(self) -> None:
        self.items.clear()

    async def append(self, item) -> None:
        self.items.append(item)

    def focus(self) -> None:
        self.focus_calls += 1


class StubInput(Input):
    """Real Input subclass whose value is a plain attribute.

    Assigning to the reactive `value` requires a running app; these tests do not
    run one, and only need isinstance(Input) plus a readable/writable value.
    """

    def __init__(self, value: str = "") -> None:
        super().__init__()
        self._stub_value = value

    @property
    def value(self) -> str:  # type: ignore[override]
        return self._stub_value

    @value.setter
    def value(self, new_value: str) -> None:
        self._stub_value = new_value


class StubTextArea(TextArea):
    """Real TextArea subclass whose text is a plain attribute (same idea as StubInput)."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._stub_text = text

    @property
    def text(self) -> str:  # type: ignore[override]
        return self._stub_text

    @text.setter
    def text(self, new_text: str) -> None:
        self._stub_text = new_text


class FakeTreeRoot:
    def __init__(self) -> None:
        self.children: list[object] = []

    def add(self, label, data=None, expand=False) -> None:
        self.children.append((label, data))


class FakeAlbumTree:
    def __init__(self) -> None:
        self.display = False
        self.root = FakeTreeRoot()
        self.focus_calls = 0

    def clear(self) -> None:
        self.root = FakeTreeRoot()

    def focus(self) -> None:
        self.focus_calls += 1


class SongClient:
    def structured_search(self, parsed, limit: int = 25) -> list[SearchItem]:
        return [search_item_from_song(SongCandidate(video_id="v1", title="Myth"))]


class AlbumClient:
    def structured_search(self, parsed, limit: int = 25) -> list[SearchItem]:
        return [
            SearchItem(
                item_type="album",
                title="Master of Puppets",
                subtitle="Metallica",
                browse_id="b1",
            )
        ]


def _make_app(
    monkeypatch, tmp_path, extra_widgets: dict | None = None
) -> tuple[tui.BesterYTMApp, FakeListView, list]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    app = tui.BesterYTMApp()
    app.client = SongClient()  # type: ignore[assignment]
    results = FakeListView()
    widgets = {"#results": results, "#queue": FakeListView()}
    widgets.update(extra_widgets or {})
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(app, "_set_status", lambda message: None)
    workers: list = []
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: workers.append(work))
    monkeypatch.setattr(app, "call_from_thread", lambda fn, *args: fn(*args))
    return app, results, workers


def _set_focused(monkeypatch, widget) -> None:
    monkeypatch.setattr(tui.BesterYTMApp, "focused", widget, raising=False)


def _drain_workers(workers: list) -> None:
    while workers:
        work = workers.pop(0)
        if asyncio.iscoroutine(work):
            asyncio.run(work)
        else:
            work()


def test_completion_keeps_focus_while_user_types_in_search(monkeypatch, tmp_path) -> None:
    app, results, workers = _make_app(monkeypatch, tmp_path)
    search_input = StubInput("beach house")
    _set_focused(monkeypatch, search_input)

    asyncio.run(app._search("beach house"))
    search_input.value = "beach house tee"  # user keeps typing while the load runs

    _drain_workers(workers)

    assert len(results.items) == 1  # results still land
    assert results.index == 0  # first row is still highlighted
    assert results.focus_calls == 0  # but focus stays on the search input


def test_completion_keeps_focus_when_input_focused_during_load(
    monkeypatch, tmp_path
) -> None:
    app, results, workers = _make_app(monkeypatch, tmp_path)
    _set_focused(monkeypatch, None)

    asyncio.run(app._search("beach house"))
    _set_focused(monkeypatch, StubInput())  # user clicks into search mid-load

    _drain_workers(workers)

    assert len(results.items) == 1
    assert results.focus_calls == 0


def test_completion_focuses_results_when_search_focus_unchanged(
    monkeypatch, tmp_path
) -> None:
    app, results, workers = _make_app(monkeypatch, tmp_path)
    search_input = StubInput("beach house")
    _set_focused(monkeypatch, search_input)  # submit leaves focus on search, untouched

    asyncio.run(app._search("beach house"))
    _drain_workers(workers)

    assert len(results.items) == 1
    assert results.index == 0
    assert results.focus_calls == 1


def test_completion_focuses_results_when_no_input_focused(monkeypatch, tmp_path) -> None:
    app, results, workers = _make_app(monkeypatch, tmp_path)
    _set_focused(monkeypatch, None)

    asyncio.run(app._search("beach house"))
    _drain_workers(workers)

    assert len(results.items) == 1
    assert results.focus_calls == 1


def test_album_completion_keeps_focus_while_user_types_in_search(
    monkeypatch, tmp_path
) -> None:
    tree = FakeAlbumTree()
    app, results, workers = _make_app(monkeypatch, tmp_path, {"#album-tree": tree})
    app.client = AlbumClient()  # type: ignore[assignment]
    search_input = StubInput("album:metallica")
    _set_focused(monkeypatch, search_input)

    asyncio.run(app._search("album:metallica"))
    search_input.value = "album:metallica ride"  # user keeps typing while the load runs

    _drain_workers(workers)

    assert len(tree.root.children) == 1  # albums still land in the tree
    assert tree.focus_calls == 0  # but focus stays on the search input


def test_album_completion_focuses_tree_when_search_focus_unchanged(
    monkeypatch, tmp_path
) -> None:
    tree = FakeAlbumTree()
    app, results, workers = _make_app(monkeypatch, tmp_path, {"#album-tree": tree})
    app.client = AlbumClient()  # type: ignore[assignment]
    _set_focused(monkeypatch, StubInput("album:metallica"))

    asyncio.run(app._search("album:metallica"))
    _drain_workers(workers)

    assert len(tree.root.children) == 1
    assert tree.focus_calls == 1


def test_completion_keeps_focus_when_builder_textarea_focused_mid_load(
    monkeypatch, tmp_path
) -> None:
    app, results, workers = _make_app(monkeypatch, tmp_path)
    _set_focused(monkeypatch, None)

    asyncio.run(app._search("beach house"))
    _set_focused(monkeypatch, StubTextArea("dark synthwave"))  # user clicks into the builder

    _drain_workers(workers)

    assert len(results.items) == 1
    assert results.focus_calls == 0


def test_playlist_listing_error_completion_respects_focused_input(
    monkeypatch, tmp_path
) -> None:
    app, results, _ = _make_app(monkeypatch, tmp_path)
    _set_focused(monkeypatch, StubInput())  # focused after the listing started
    local_items = [SearchItem(item_type="local_playlist", title="Mix", playlist_id="p1")]
    app._results_load_id = 7

    app._finish_show_playlists_error(local_items, "offline", 7)

    assert results.focus_calls == 0
