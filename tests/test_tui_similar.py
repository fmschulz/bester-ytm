from __future__ import annotations

import asyncio

from bester_ytm import tui_similar
from bester_ytm.intelligence.llm import IntelligenceError, IntelligenceSettings
from bester_ytm.playlist_plan import SongCandidate
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
    def __init__(self, current: str | None, queue: list[str]) -> None:
        self.current_video_id = current
        self.queue = queue
        self.enqueued: list[str] = []

    def enqueue(self, video_ids: list[str]) -> None:
        self.enqueued.extend(video_ids)
        self.queue.extend(video_ids)

    def status(self):
        from bester_ytm.playback import PlaybackStatus

        return PlaybackStatus(running=False, current_video_id=self.current_video_id)


class FakeTimer:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def _candidate(video_id: str) -> SongCandidate:
    return SongCandidate(video_id=video_id, title=video_id, artists=["A"])


def _make_app(monkeypatch, playback) -> tuple[BesterYTMApp, dict, list]:
    widgets = {"#status": FakeStatic(), "#queue": FakeListView(), "#track": FakeStatic()}
    workers: list = []
    app = BesterYTMApp()
    app.playback = playback
    app.intelligence_settings = IntelligenceSettings(provider="codex")
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(
        app, "_query_optional", lambda selector, widget_type=None: widgets.get(selector)
    )
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: workers.append(work))
    monkeypatch.setattr(app, "call_from_thread", lambda fn, *args: fn(*args))
    return app, widgets, workers


def _arm_count_window(monkeypatch, app) -> list:
    """Press g with set_timer captured so tests expire the window by hand."""
    timers: list = []

    def fake_set_timer(delay, callback):
        timers.append(callback)
        return FakeTimer()

    monkeypatch.setattr(app, "set_timer", fake_set_timer)
    app.action_add_similar()
    return timers


def _press(app, key: str, character: str | None = None) -> None:
    from textual import events

    app.on_key(events.Key(key=key, character=character))


def test_add_similar_requires_seed_tracks(monkeypatch) -> None:
    app, widgets, workers = _make_app(monkeypatch, FakePlayback(None, []))

    app.action_add_similar()

    assert "Play or queue something first" in widgets["#status"].value
    assert workers == []


def test_g_waits_for_digits_then_adds_default_count(monkeypatch) -> None:
    playback = FakePlayback("v1", [])
    app, widgets, workers = _make_app(monkeypatch, playback)
    app.candidates_by_video_id = {"v1": _candidate("v1")}
    app.playlist_video_ids = ["v1"]
    suggested = [_candidate("n1"), _candidate("n2")]
    monkeypatch.setattr(
        tui_similar,
        "find_similar_candidates",
        lambda client, seeds, count, settings: (suggested, "codex"),
    )
    timers = _arm_count_window(monkeypatch, app)

    assert "type a number" in widgets["#status"].value
    assert workers == []

    timers[-1]()  # the digit window expires
    assert "Finding 5 similar songs via codex" in widgets["#status"].value
    assert len(workers) == 1

    workers[0]()  # the thread worker body
    asyncio.run(workers[1])  # the scheduled queue re-render

    assert playback.enqueued == ["n1", "n2"]
    assert app.playlist_video_ids == ["v1", "n1", "n2"]
    assert "Added 2 similar track(s) via codex" in widgets["#status"].value


def test_g_with_digits_requests_that_many_tracks(monkeypatch) -> None:
    playback = FakePlayback("v1", [])
    app, widgets, workers = _make_app(monkeypatch, playback)
    app.candidates_by_video_id = {"v1": _candidate("v1")}
    counts: list[int] = []

    def fake_find(client, seeds, count, settings):
        counts.append(count)
        return [_candidate("n1")], "codex"

    monkeypatch.setattr(tui_similar, "find_similar_candidates", fake_find)
    timers = _arm_count_window(monkeypatch, app)

    _press(app, "1", "1")
    _press(app, "1", "1")
    assert "Adding 11 similar songs" in widgets["#status"].value

    timers[-1]()
    assert "Finding 11 similar songs via codex" in widgets["#status"].value
    workers[0]()
    asyncio.run(workers[1])  # the scheduled queue re-render
    assert counts == [11]


def test_second_g_flushes_the_pending_count(monkeypatch) -> None:
    playback = FakePlayback("v1", [])
    app, widgets, workers = _make_app(monkeypatch, playback)
    app.candidates_by_video_id = {"v1": _candidate("v1")}
    _arm_count_window(monkeypatch, app)

    _press(app, "7", "7")
    app.action_add_similar()  # g again fires immediately

    assert "Finding 7 similar songs via codex" in widgets["#status"].value
    assert len(workers) == 1


def test_escape_cancels_the_pending_count(monkeypatch) -> None:
    playback = FakePlayback("v1", [])
    app, widgets, workers = _make_app(monkeypatch, playback)
    app.candidates_by_video_id = {"v1": _candidate("v1")}
    timers = _arm_count_window(monkeypatch, app)

    _press(app, "escape")
    assert "cancelled" in widgets["#status"].value

    timers[-1]()  # the stale timer callback must be a no-op
    assert workers == []


def test_add_similar_reports_provider_errors(monkeypatch) -> None:
    playback = FakePlayback("v1", [])
    app, widgets, workers = _make_app(monkeypatch, playback)
    app.candidates_by_video_id = {"v1": _candidate("v1")}

    def failing(client, seeds, count, settings):
        raise IntelligenceError("codex CLI is not installed or not on PATH")

    monkeypatch.setattr(tui_similar, "find_similar_candidates", failing)

    timers = _arm_count_window(monkeypatch, app)
    timers[-1]()
    workers[0]()

    assert widgets["#status"].value == "codex CLI is not installed or not on PATH"
    assert playback.enqueued == []


def test_add_similar_rejects_misconfigured_provider(monkeypatch) -> None:
    playback = FakePlayback("v1", [])
    app, widgets, workers = _make_app(monkeypatch, playback)
    app.candidates_by_video_id = {"v1": _candidate("v1")}
    app.intelligence_settings = IntelligenceSettings(provider="auto")
    monkeypatch.setattr(
        tui_similar, "resolve_provider", lambda settings: (_ for _ in ()).throw(
            IntelligenceError("unknown intelligence provider")
        )
    )

    timers = _arm_count_window(monkeypatch, app)
    timers[-1]()

    assert "unknown intelligence provider" in widgets["#status"].value
    assert workers == []


def test_double_g_keypress_fires_once_and_does_not_rearm(monkeypatch) -> None:
    """Real key dispatch: on_key must consume the second g before the binding."""
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent-bytm-config")

    async def run_flow() -> None:
        app = BesterYTMApp()
        app.playback = FakePlayback("v1", [])
        app.candidates_by_video_id = {"v1": _candidate("v1")}
        launches: list[int] = []
        monkeypatch.setattr(app, "_launch_similar", launches.append)
        async with app.run_test() as pilot:
            app.set_focus(None)  # the search Input would swallow the g keys
            await pilot.pause()
            await pilot.press("g")
            assert app._similar_digits == ""
            await pilot.press("g")
            await pilot.pause()
            assert launches == [5]
            assert app._similar_digits is None  # no second window was armed

    asyncio.run(run_flow())


def test_g_binding_maps_to_add_similar() -> None:
    from textual.binding import Binding

    actions = {
        (b.key if isinstance(b, Binding) else b[0]): (
            b.action if isinstance(b, Binding) else b[1]
        )
        for b in BesterYTMApp.BINDINGS
    }
    assert actions["g"] == "add_similar"
    assert actions["a"] == "add_to_queue"
