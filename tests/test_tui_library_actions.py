from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bester_ytm import tui, tui_builder
from bester_ytm.playback import PlaybackError, PlaybackStatus
from bester_ytm.playlist_builder import PlaylistBuildError
from bester_ytm.playlist_plan import PlaylistPlan, SongCandidate
from bester_ytm.search_query import SearchItem, search_item_from_song
from bester_ytm.stores import LocalPlaylistStore
from bester_ytm.ytm_client import PlaylistSnapshot, YTMClientError


class FakeListView:
    def __init__(self) -> None:
        self.items: list[object] = []
        self.highlighted_child: object | None = None

    async def clear(self) -> None:
        self.items.clear()

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


class FakePlayback:
    def __init__(self) -> None:
        self.queue: list[str] = []
        self.current_video_id: str | None = None

    def status(self) -> PlaybackStatus:
        return PlaybackStatus(
            running=bool(self.current_video_id),
            current_video_id=self.current_video_id,
            queue_size=len(self.queue),
        )

    def replace_queue(self, video_ids: list[str]) -> None:
        self.queue = list(video_ids)


def _make_app(monkeypatch, tmp_path, widgets=None) -> tuple[tui.BesterYTMApp, dict, list[str]]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    app = tui.BesterYTMApp()
    app.playback = FakePlayback()  # type: ignore[assignment]
    widgets = widgets or {"#results": FakeListView(), "#queue": FakeListView()}
    statuses: list[str] = []
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(app, "_set_status", statuses.append)
    return app, widgets, statuses


def _capture_workers(app, monkeypatch) -> list:
    """Synchronous seam: collect scheduled workers instead of running threads."""
    workers: list = []
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: workers.append(work))
    monkeypatch.setattr(app, "call_from_thread", lambda fn, *args: fn(*args))
    return workers


def _drain_workers(workers: list) -> None:
    """Run captured thread-worker bodies and any coroutines they schedule.

    Consumes the list so repeated drains only run newly scheduled work.
    """
    while workers:
        work = workers.pop(0)
        if asyncio.iscoroutine(work):
            asyncio.run(work)
        else:
            work()


def test_search_with_blank_query_only_clears_results(monkeypatch, tmp_path) -> None:
    app, widgets, statuses = _make_app(monkeypatch, tmp_path)
    widgets["#results"].items.append(object())
    app.selected_queue_video_id = "v1"

    asyncio.run(app._search("   "))

    assert widgets["#results"].items == []
    assert app.selected_queue_video_id is None
    assert statuses == []


def test_search_reports_client_error(monkeypatch, tmp_path) -> None:
    class FailingClient:
        def structured_search(self, parsed, limit: int = 25):
            raise YTMClientError("quota exceeded")

    app, _, statuses = _make_app(monkeypatch, tmp_path)
    app.client = FailingClient()  # type: ignore[assignment]
    workers = _capture_workers(app, monkeypatch)

    asyncio.run(app._search("free text"))
    _drain_workers(workers)

    assert statuses[-1] == "quota exceeded"


def test_search_registers_song_candidates(monkeypatch, tmp_path) -> None:
    candidate = SongCandidate(video_id="v1", title="Myth", artists=["Beach House"])

    class SongClient:
        def structured_search(self, parsed, limit: int = 25):
            return [search_item_from_song(candidate)]

    app, widgets, statuses = _make_app(monkeypatch, tmp_path)
    app.client = SongClient()  # type: ignore[assignment]
    workers = _capture_workers(app, monkeypatch)

    asyncio.run(app._search("beach house"))
    assert statuses[-1] == "Searching 'beach house'..."
    _drain_workers(workers)

    item = widgets["#results"].items[0]
    assert item.candidate is candidate
    assert app.candidates_by_video_id["v1"] is candidate
    assert statuses[-1] == "1 songs result(s)."


def test_new_search_supersedes_stale_results(monkeypatch, tmp_path) -> None:
    class SongClient:
        def __init__(self, candidate: SongCandidate) -> None:
            self.candidate = candidate

        def structured_search(self, parsed, limit: int = 25):
            return [search_item_from_song(self.candidate)]

    stale = SongCandidate(video_id="old", title="Old", artists=["A"])
    fresh = SongCandidate(video_id="new", title="New", artists=["B"])
    app, widgets, statuses = _make_app(monkeypatch, tmp_path)
    workers = _capture_workers(app, monkeypatch)

    app.client = SongClient(stale)  # type: ignore[assignment]
    asyncio.run(app._search("old query"))
    app.client = SongClient(fresh)  # type: ignore[assignment]
    asyncio.run(app._search("new query"))
    _drain_workers(workers)  # both workers finish; only the newest may land

    assert [item.candidate.video_id for item in widgets["#results"].items] == ["new"]
    assert statuses[-1] == "1 songs result(s)."


def test_load_search_item_passes_songs_through(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path)

    loaded = asyncio.run(app._load_search_item(SearchItem(item_type="song", title="Myth")))

    assert loaded is False
    assert statuses == []


def test_load_search_item_requires_ids(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path)

    assert asyncio.run(app._load_search_item(SearchItem(item_type="album", title="A")))
    assert asyncio.run(app._load_search_item(SearchItem(item_type="playlist", title="P")))
    assert asyncio.run(
        app._load_search_item(SearchItem(item_type="local_playlist", title="L"))
    )
    assert statuses == [
        "Album result has no browse id.",
        "Playlist result has no playlist id.",
        "Local playlist result has no id.",
    ]


def test_load_search_item_loads_remote_playlist_off_the_ui_thread(
    monkeypatch, tmp_path
) -> None:
    class PlaylistClient:
        def get_playlist(self, playlist_id: str) -> PlaylistSnapshot:
            assert playlist_id == "PL1"
            return PlaylistSnapshot(
                playlist_id="PL1",
                title="Mix",
                video_ids=["v1"],
                tracks=[SongCandidate(video_id="v1", title="One", artists=["A"])],
            )

    widgets = {
        "#results": FakeListView(),
        "#queue": FakeListView(),
        "#track": FakeStatic(),
        "#track-metadata": FakeStatic(),
        "#tags-input": FakeInput(),
        "#playlist-name": FakeInput(),
        "#queue-title": FakeStatic(),
    }
    app, _, statuses = _make_app(monkeypatch, tmp_path, widgets)
    app.client = PlaylistClient()  # type: ignore[assignment]
    workers = _capture_workers(app, monkeypatch)
    item = SearchItem(item_type="playlist", title="Mix", playlist_id="PL1")

    loaded = asyncio.run(app._load_search_item(item))

    # The fetch is deferred to a worker; the UI thread only shows progress.
    assert loaded is True
    assert app.playback.queue == []
    assert statuses[-1] == "Loading playlist tracks..."

    _drain_workers(workers)

    assert app.playback.queue == ["v1"]
    assert app.active_youtube_playlist_id == "PL1"
    assert app.active_local_playlist_id is None
    assert statuses[-1] == "Loaded Mix: 1 track(s)."


def test_load_search_item_loads_album_off_the_ui_thread(monkeypatch, tmp_path) -> None:
    class AlbumClient:
        def get_album(self, browse_id: str) -> PlaylistSnapshot:
            assert browse_id == "b1"
            return PlaylistSnapshot(
                playlist_id="b1",
                title="Against",
                video_ids=["v1"],
                tracks=[SongCandidate(video_id="v1", title="Against", artists=["S"])],
            )

    widgets = {
        "#results": FakeListView(),
        "#queue": FakeListView(),
        "#track": FakeStatic(),
        "#track-metadata": FakeStatic(),
        "#tags-input": FakeInput(),
        "#playlist-name": FakeInput(),
        "#queue-title": FakeStatic(),
    }
    app, _, statuses = _make_app(monkeypatch, tmp_path, widgets)
    app.client = AlbumClient()  # type: ignore[assignment]
    workers = _capture_workers(app, monkeypatch)
    item = SearchItem(item_type="album", title="Against", browse_id="b1")

    loaded = asyncio.run(app._load_search_item(item))

    assert loaded is True
    assert app.playback.queue == []
    assert statuses[-1] == "Loading album tracks..."

    _drain_workers(workers)

    assert app.playback.queue == ["v1"]
    assert app.active_youtube_playlist_id is None
    assert statuses[-1] == "Loaded album Against: 1 track(s)."


def test_load_search_item_reports_lookup_error(monkeypatch, tmp_path) -> None:
    class FailingClient:
        def get_album(self, browse_id: str) -> PlaylistSnapshot:
            raise YTMClientError("album gone")

    app, _, statuses = _make_app(monkeypatch, tmp_path)
    app.client = FailingClient()  # type: ignore[assignment]
    workers = _capture_workers(app, monkeypatch)
    item = SearchItem(item_type="album", title="A", browse_id="b1")

    loaded = asyncio.run(app._load_search_item(item))
    _drain_workers(workers)

    assert loaded is True
    assert statuses[-1] == "album gone"


def test_stale_search_results_are_dropped_after_scheduling(monkeypatch, tmp_path) -> None:
    from bester_ytm.search_query import parse_search_query, search_item_from_song

    app, widgets, statuses = _make_app(monkeypatch, tmp_path)
    workers = _capture_workers(app, monkeypatch)
    parsed = parse_search_query("old query")
    stale = [search_item_from_song(SongCandidate(video_id="old", title="Old"))]

    app._results_load_id = 1
    app._finish_search(parsed, stale, 1)  # schedules the render coroutine
    app._results_load_id = 2  # a newer search starts before the coroutine runs
    _drain_workers(workers)

    assert widgets["#results"].items == []
    assert statuses == []


def test_focus_first_result_tolerates_unfocusable_widgets(monkeypatch, tmp_path) -> None:
    class StubbornListView:
        focused = False

        @property
        def index(self) -> int:
            return 0

        def focus(self) -> None:
            self.focused = True

    app, _, _ = _make_app(monkeypatch, tmp_path)
    results = StubbornListView()

    app._focus_first_result(results, has_items=False)
    assert results.focused is False

    app._focus_first_result(results, has_items=True)
    assert results.focused is True


def test_rating_and_tags_require_selection(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path)

    app.action_rate_down()
    app.action_save_tags()

    assert statuses == [
        "No track selected for rating.",
        "No track selected for tags.",
    ]


def test_rate_down_clamps_rating_at_zero(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path)
    app.selected_queue_video_id = "v1"

    app.action_rate_down()

    assert statuses[-1] == "Rating 0/3."


def test_r_key_cycles_rating_and_wraps_to_zero(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path)
    app.selected_queue_video_id = "v1"

    for _ in range(4):
        app.action_cycle_rating()

    assert statuses[-4:] == ["Rating 1/3.", "Rating 2/3.", "Rating 3/3.", "Rating 0/3."]


def test_rating_on_corrupt_store_reports_error_instead_of_crashing(
    monkeypatch, tmp_path
) -> None:
    from bester_ytm.stores import TrackMetadataStore

    app, _, statuses = _make_app(monkeypatch, tmp_path)
    app.selected_queue_video_id = "v1"
    store = TrackMetadataStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("[1, 2]", encoding="utf-8")  # not an object mapping

    app.action_cycle_rating()

    assert "corrupt" in statuses[-1]
    assert "Move the file aside" in statuses[-1]


def test_add_to_local_playlist_requires_candidate(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path)

    app.action_add_to_local_playlist()

    assert statuses == ["No track selected to add."]


def test_add_uses_active_playlist_name_when_input_empty(monkeypatch, tmp_path) -> None:
    widgets = {
        "#results": FakeListView(),
        "#queue": FakeListView(),
        "#playlist-name": FakeInput(""),
    }
    app, _, statuses = _make_app(monkeypatch, tmp_path, widgets)
    existing = LocalPlaylistStore().add_track(
        "Road Mix", SongCandidate(video_id="v0", title="Zero", artists=["A"])
    )
    app.active_local_playlist_id = existing.id
    candidate = SongCandidate(video_id="v1", title="One", artists=["A"])
    app.candidates_by_video_id["v1"] = candidate
    app.selected_queue_video_id = "v1"

    app.action_add_to_local_playlist()

    assert LocalPlaylistStore().load("road-mix").video_ids == ["v0", "v1"]
    assert widgets["#playlist-name"].value == "Road Mix"
    assert statuses[-1] == "Added to Road Mix."


def test_add_falls_back_when_active_playlist_is_missing(monkeypatch, tmp_path) -> None:
    widgets = {
        "#results": FakeListView(),
        "#queue": FakeListView(),
        "#playlist-name": FakeInput(""),
    }
    app, _, statuses = _make_app(monkeypatch, tmp_path, widgets)
    app.active_local_playlist_id = "ghost"
    candidate = SongCandidate(video_id="v1", title="One", artists=["A"])
    app.candidates_by_video_id["v1"] = candidate
    app.selected_queue_video_id = "v1"

    app.action_add_to_local_playlist()

    assert statuses[-1] == "Added to TUI Playlist."


def test_remove_from_playlist_guards(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path)

    asyncio.run(app.action_remove_from_playlist())
    assert statuses[-1] == "No current track to remove."

    app.selected_queue_video_id = "v1"
    asyncio.run(app.action_remove_from_playlist())
    assert statuses[-1] == (
        "Load a playlist first (Ctrl+P); Remove drops the highlighted track."
    )


def test_remove_reports_missing_playlist_file(monkeypatch, tmp_path) -> None:
    widgets = {
        "#results": FakeListView(),
        "#queue": FakeListView(),
        "#playlist-name": FakeInput("Ghost List"),
    }
    app, _, statuses = _make_app(monkeypatch, tmp_path, widgets)
    app.selected_queue_video_id = "v1"

    asyncio.run(app.action_remove_from_playlist())

    assert "ghost-list" in statuses[-1]


def test_remove_targets_active_youtube_playlist(monkeypatch, tmp_path) -> None:
    class FakeRemovalClient:
        removed: list[tuple[str, str]] = []

        def __init__(self, authenticated: bool = True) -> None:
            pass

        def remove_playlist_item(self, playlist_id: str, video_id: str) -> int:
            FakeRemovalClient.removed.append((playlist_id, video_id))
            return 1

    FakeRemovalClient.removed = []
    monkeypatch.setattr("bester_ytm.tui_metadata.YTMClient", FakeRemovalClient)
    widgets = {
        "#results": FakeListView(),
        "#queue": FakeListView(),
        "#playlist-name": FakeInput("ByteFM Inspired 30"),
    }
    app, _, statuses = _make_app(monkeypatch, tmp_path, widgets)
    monkeypatch.setattr(app, "_render_queue", _noop_render(app))
    app.active_youtube_playlist_id = "PL1"
    app.playlist_title = "ByteFM Inspired 30"
    app.playlist_video_ids = ["v1", "v2"]
    app.playback.queue = ["v2"]
    app.selected_queue_video_id = "v2"

    asyncio.run(app.action_remove_from_playlist())

    assert FakeRemovalClient.removed == [("PL1", "v2")]
    assert app.playlist_video_ids == ["v1"]
    assert app.playback.queue == []
    assert statuses[-1] == "Removed track from YouTube playlist 'ByteFM Inspired 30'."


def test_remove_reports_track_missing_from_youtube_playlist(monkeypatch, tmp_path) -> None:
    class EmptyRemovalClient:
        def __init__(self, authenticated: bool = True) -> None:
            pass

        def remove_playlist_item(self, playlist_id: str, video_id: str) -> int:
            return 0

    monkeypatch.setattr("bester_ytm.tui_metadata.YTMClient", EmptyRemovalClient)
    app, _, statuses = _make_app(monkeypatch, tmp_path)
    app.active_youtube_playlist_id = "PL1"
    app.playlist_title = "Mix"
    app.selected_queue_video_id = "v9"

    asyncio.run(app.action_remove_from_playlist())

    assert statuses[-1] == "Track is not in YouTube playlist 'Mix'."


def _noop_render(app):
    async def _render(**kwargs) -> None:
        return None

    return _render


def test_favorite_current_requires_and_saves_track(monkeypatch, tmp_path) -> None:
    app, _, statuses = _make_app(monkeypatch, tmp_path)

    asyncio.run(app.action_favorite_current())
    assert statuses[-1] == "No current track to favorite."

    app.current_candidate = SongCandidate(video_id="v1", title="One", artists=["A"])
    asyncio.run(app.action_favorite_current())
    assert statuses[-1] == "Favorite saved."


class FakeBuilder:
    last: dict[str, object] = {}

    def build_from_text(self, text, source, name, count, brief="") -> PlaylistPlan:
        FakeBuilder.last = {"text": text, "brief": brief}
        return _plan(name, count)

    def build_from_favorites(self, source, name, count, brief="") -> PlaylistPlan:
        FakeBuilder.last = {"source": source, "brief": brief}
        return _plan(name, count)


def _plan(name: str, count: int) -> PlaylistPlan:
    return PlaylistPlan(id="plan-1", name=name, target_count=count)


def _builder_widgets(text: str) -> dict[str, object]:
    return {
        "#results": FakeListView(),
        "#queue": FakeListView(),
        "#builder": SimpleNamespace(text=text),
    }


def _run_build(app, monkeypatch) -> None:
    """Drive the build action plus every worker it schedules (threads and coroutines)."""
    workers: list = []
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: workers.append(work))
    monkeypatch.setattr(app, "call_from_thread", lambda fn, *args: fn(*args))
    asyncio.run(app.action_build_playlist())
    index = 0
    while index < len(workers):
        work = workers[index]
        index += 1
        if asyncio.iscoroutine(work):
            asyncio.run(work)
        else:
            work()


def test_build_playlist_from_pasted_text(monkeypatch, tmp_path) -> None:
    widgets = _builder_widgets("Beach House - Myth")
    app, _, statuses = _make_app(monkeypatch, tmp_path, widgets)
    monkeypatch.setattr(tui_builder, "PlaylistBuilder", FakeBuilder)

    _run_build(app, monkeypatch)

    assert FakeBuilder.last == {"text": "Beach House - Myth", "brief": ""}
    assert statuses[0] == "Building playlist..."
    assert statuses[-1] == (
        "plan saved: plan-1.json (0/30 resolved). No resolved tracks to queue."
    )


def test_build_playlist_imports_favorites_when_builder_empty(
    monkeypatch, tmp_path
) -> None:
    favs = tmp_path / "favs.md"
    favs.write_text("- Beach House - Myth\n", encoding="utf-8")
    widgets = _builder_widgets("")
    app, _, statuses = _make_app(monkeypatch, tmp_path, widgets)
    monkeypatch.setattr(tui_builder, "PlaylistBuilder", FakeBuilder)
    monkeypatch.setattr(tui_builder, "resolve_existing_input", lambda path: favs)

    _run_build(app, monkeypatch)

    assert FakeBuilder.last["source"] == favs
    assert statuses[-1] == (
        "Imported 1 favorites; plan saved: plan-1.json (0/30 resolved). "
        "No resolved tracks to queue."
    )


def test_build_playlist_reports_build_errors(monkeypatch, tmp_path) -> None:
    class FailingBuilder:
        def build_from_text(self, *args, **kwargs) -> PlaylistPlan:
            raise PlaylistBuildError("no seeds found")

    widgets = _builder_widgets("Beach House - Myth")
    app, _, statuses = _make_app(monkeypatch, tmp_path, widgets)
    monkeypatch.setattr(tui_builder, "PlaylistBuilder", FailingBuilder)

    _run_build(app, monkeypatch)

    assert statuses[-1] == "no seeds found"


def test_build_playlist_from_brief_runs_in_background_with_feedback(
    monkeypatch, tmp_path
) -> None:
    from bester_ytm.intelligence.llm import IntelligenceSettings

    class FakeBriefBuilder:
        last: dict[str, object] = {}

        def build_from_brief(self, brief, name, count) -> PlaylistPlan:
            FakeBriefBuilder.last = {"brief": brief, "name": name, "count": count}
            return _plan(name, count)

    brief = "create a playlist with 10 songs of bands similar to blind guardian"
    widgets = _builder_widgets(brief)
    app, _, statuses = _make_app(monkeypatch, tmp_path, widgets)
    app.intelligence_settings = IntelligenceSettings(provider="codex")
    monkeypatch.setattr(tui_builder, "PlaylistBuilder", FakeBriefBuilder)

    _run_build(app, monkeypatch)

    assert statuses[0] == (
        "Building playlist from brief via codex (this can take a minute)..."
    )
    assert FakeBriefBuilder.last["count"] == 10
    assert FakeBriefBuilder.last["brief"] == brief
    assert "plan saved: plan-1.json (0/10 resolved)" in statuses[-1]


def test_highlighted_queue_video_id_prefers_focused_queue(monkeypatch, tmp_path) -> None:
    app, widgets, _ = _make_app(monkeypatch, tmp_path)
    widgets["#queue"].highlighted_child = SimpleNamespace(video_id="v9")
    monkeypatch.setattr(
        tui.BesterYTMApp, "focused", SimpleNamespace(id="queue"), raising=False
    )

    assert app._highlighted_queue_video_id() == "v9"


def test_current_video_id_falls_back_to_candidate_then_status(
    monkeypatch, tmp_path
) -> None:
    app, _, _ = _make_app(monkeypatch, tmp_path)
    app.current_candidate = SongCandidate(video_id="v5", title="Five")
    assert app._current_video_id() == "v5"

    class FailingPlayback:
        def status(self) -> PlaybackStatus:
            raise PlaybackError("ipc down")

    app.current_candidate = None
    app.playback = FailingPlayback()  # type: ignore[assignment]
    assert app._current_video_id() is None


def test_current_candidate_falls_back_to_highlighted_result(
    monkeypatch, tmp_path
) -> None:
    app, widgets, _ = _make_app(monkeypatch, tmp_path)
    unregistered = SongCandidate(video_id="v7", title="Seven")
    widgets["#results"].highlighted_child = SimpleNamespace(candidate=unregistered)
    assert app._current_candidate() is unregistered

    widgets["#results"].highlighted_child = None
    fallback = SongCandidate(video_id="v8", title="Eight")
    app.current_candidate = fallback
    assert app._current_candidate() is fallback
