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


def test_add_similar_requires_seed_tracks(monkeypatch) -> None:
    app, widgets, workers = _make_app(monkeypatch, FakePlayback(None, []))

    app.action_add_similar()

    assert "Play or queue something first" in widgets["#status"].value
    assert workers == []


def test_add_similar_enqueues_resolved_tracks(monkeypatch) -> None:
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

    app.action_add_similar()
    assert "Asking codex for" in widgets["#status"].value
    assert len(workers) == 1

    workers[0]()  # the thread worker body
    asyncio.run(workers[1])  # the scheduled queue re-render

    assert playback.enqueued == ["n1", "n2"]
    assert app.playlist_video_ids == ["v1", "n1", "n2"]
    assert "Added 2 similar track(s) via codex" in widgets["#status"].value


def test_add_similar_reports_provider_errors(monkeypatch) -> None:
    playback = FakePlayback("v1", [])
    app, widgets, workers = _make_app(monkeypatch, playback)
    app.candidates_by_video_id = {"v1": _candidate("v1")}

    def failing(client, seeds, count, settings):
        raise IntelligenceError("codex CLI is not installed or not on PATH")

    monkeypatch.setattr(tui_similar, "find_similar_candidates", failing)

    app.action_add_similar()
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

    app.action_add_similar()

    assert "unknown intelligence provider" in widgets["#status"].value
    assert workers == []


def test_g_binding_maps_to_add_similar() -> None:
    from textual.binding import Binding

    actions = {
        (b.key if isinstance(b, Binding) else b[0]): (
            b.action if isinstance(b, Binding) else b[1]
        )
        for b in BesterYTMApp.BINDINGS
    }
    assert actions["g"] == "add_similar"
