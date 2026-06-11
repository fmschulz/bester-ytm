import asyncio

from bester_ytm import tui
from bester_ytm.playback import PlaybackStatus
from bester_ytm.playlist_plan import SongCandidate


class FakeLabel:
    def __init__(self, text: str) -> None:
        self.text = text

    def update(self, text: str) -> None:
        self.text = text


class FakeResultItem:
    def __init__(self, video_id: str, title: str) -> None:
        self.candidate = SongCandidate(video_id=video_id, title=title, artists=["A"])
        self.base_label = self.candidate.display_name
        self.label_widget = FakeLabel(self.base_label)


class FakeResults:
    def __init__(self, items) -> None:
        self.children = items
        self.highlighted_child = items[0] if items else None

    async def clear(self) -> None:
        self.children = []


class FakeQueueView:
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
    def __init__(self, running: bool = False) -> None:
        self.running = running
        self.queue: list[str] = []
        self.current_video_id: str | None = "now" if running else None
        self.replaced: list[str] | None = None
        self.enqueued: list[str] = []

    def status(self) -> PlaybackStatus:
        return PlaybackStatus(
            running=self.running,
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

    def play_queue(self) -> PlaybackStatus:
        self.running = True
        self.current_video_id = self.queue.pop(0)
        return self.status()


def _make_app(monkeypatch, results, playback):
    widgets = {
        "#results": results,
        "#queue": FakeQueueView(),
        "#track": FakeStatic(),
        "#status": FakeStatic(),
    }
    app = tui.BesterYTMApp()
    app.playback = playback
    monkeypatch.setattr(
        app, "_query_optional", lambda selector, widget_type=None: widgets.get(selector)
    )
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    return app, widgets


def test_toggle_select_marks_and_unmarks_highlighted_result(monkeypatch) -> None:
    items = [FakeResultItem("v1", "One"), FakeResultItem("v2", "Two")]
    app, _ = _make_app(monkeypatch, FakeResults(items), FakePlayback())

    app.action_toggle_select()
    assert app.selected_result_video_ids == {"v1"}
    assert items[0].label_widget.text.startswith("* ")

    app.action_toggle_select()
    assert app.selected_result_video_ids == set()
    assert items[0].label_widget.text == items[0].base_label


def test_enter_queues_selection_in_display_order_and_plays(monkeypatch) -> None:
    items = [
        FakeResultItem("v1", "One"),
        FakeResultItem("v2", "Two"),
        FakeResultItem("v3", "Three"),
    ]
    playback = FakePlayback(running=False)
    app, widgets = _make_app(monkeypatch, FakeResults(items), playback)
    # Select out of order: third first, then first.
    app.selected_result_video_ids = {"v3", "v1"}

    asyncio.run(app.action_play_selected())

    assert playback.replaced == ["v1", "v3"]
    assert playback.current_video_id == "v1"
    assert app.playlist_video_ids == ["v1", "v3"]
    assert app.selected_result_video_ids == set()
    assert "1/2" in widgets["#status"].value


def test_enter_appends_selection_while_playing(monkeypatch) -> None:
    items = [FakeResultItem("v1", "One"), FakeResultItem("v2", "Two")]
    playback = FakePlayback(running=True)
    app, widgets = _make_app(monkeypatch, FakeResults(items), playback)
    app.playlist_video_ids = ["now"]
    app.selected_result_video_ids = {"v1", "v2"}

    asyncio.run(app.action_play_selected())

    assert playback.replaced is None
    assert playback.enqueued == ["v1", "v2"]
    assert app.playlist_video_ids == ["now", "v1", "v2"]
    assert app.selected_result_video_ids == set()
    assert widgets["#status"].value == "Queued 2 track(s)."


def test_enter_appends_selection_to_loaded_but_idle_playlist(monkeypatch) -> None:
    items = [FakeResultItem("v1", "One"), FakeResultItem("v2", "Two")]
    playback = FakePlayback(running=False)
    playback.queue = ["p1", "p2"]
    app, widgets = _make_app(monkeypatch, FakeResults(items), playback)
    app.playlist_video_ids = ["p1", "p2"]
    app.playlist_title = "AI Mix"
    app.selected_result_video_ids = {"v1", "v2"}

    asyncio.run(app.action_play_selected())

    assert playback.replaced is None  # the loaded playlist was not wiped
    assert playback.enqueued == ["v1", "v2"]
    assert app.playlist_video_ids == ["p1", "p2", "v1", "v2"]
    assert widgets["#status"].value == "Added 2 track(s) to AI Mix."


def test_shift_click_toggles_result_selection(monkeypatch) -> None:
    items = [FakeResultItem("v1", "One")]
    app, _ = _make_app(monkeypatch, FakeResults(items), FakePlayback())

    class FakeChild:
        parent = items[0]

    assert app._toggle_clicked_result(FakeChild()) is True
    assert app.selected_result_video_ids == {"v1"}


def test_toggle_select_outside_results_shows_hint(monkeypatch) -> None:
    app, widgets = _make_app(monkeypatch, FakeResults([]), FakePlayback())

    app.action_toggle_select()

    assert app.selected_result_video_ids == set()
    assert "shift+click" in widgets["#status"].value
