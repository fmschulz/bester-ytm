import asyncio

from bester_ytm import tui, tui_radio
from bester_ytm.playback import PlaybackStatus
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.radio import RadioNowPlaying, station_candidate, stations
from bester_ytm.stores import FavoritesStore


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


class FakeYTMClient:
    rated: list[tuple[str, str]] = []
    results: list[SongCandidate] = []

    def __init__(self, authenticated: bool = False) -> None:
        self.authenticated = authenticated

    def search_songs(self, query: str, limit: int = 5) -> list[SongCandidate]:
        return list(self.results)

    def rate_song(self, video_id: str, rating: str = "LIKE") -> None:
        FakeYTMClient.rated.append((video_id, rating))


def _make_app(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    app = tui.BesterYTMApp()
    app.playback = FakePlayback()
    widgets = {"#results": FakeListView(), "#queue": FakeListView()}
    statuses: list[str] = []
    labels: list[str] = []
    workers: list = []
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(app, "_set_status", statuses.append)
    monkeypatch.setattr(app, "_update_track_label", labels.append)
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: workers.append(work))
    monkeypatch.setattr(app, "call_from_thread", lambda fn, *args: fn(*args))
    FakeYTMClient.rated = []
    FakeYTMClient.results = []
    monkeypatch.setattr(tui_radio, "YTMClient", FakeYTMClient)
    return app, widgets, statuses, labels, workers


def _drain(workers: list) -> None:
    while workers:
        work = workers.pop(0)
        if asyncio.iscoroutine(work):
            asyncio.run(work)
        else:
            work()


def _radio_status(video_id: str | None) -> PlaybackStatus:
    return PlaybackStatus(running=bool(video_id), current_video_id=video_id)


def test_radio_query_lists_stations(monkeypatch, tmp_path) -> None:
    app, widgets, statuses, _, _ = _make_app(monkeypatch, tmp_path)

    asyncio.run(app._search("radio:"))

    items = widgets["#results"].items
    assert [item.candidate.video_id for item in items] == ["radio:bytefm", "radio:kalx"]
    assert statuses[-1] == "2 songs result(s)."


def test_liked_query_aliases_favorites(monkeypatch, tmp_path) -> None:
    app, widgets, statuses, _, _ = _make_app(monkeypatch, tmp_path)
    FavoritesStore().toggle(
        SongCandidate(video_id="v1", title="Myth", artists=["Beach House"])
    )

    asyncio.run(app._search("liked:"))

    items = widgets["#results"].items
    assert [item.candidate.video_id for item in items] == ["v1"]


def test_radio_poll_updates_now_playing_label(monkeypatch, tmp_path) -> None:
    app, _, _, labels, workers = _make_app(monkeypatch, tmp_path)
    info = RadioNowPlaying(station="KALX 90.7FM", artist="Stereolab", song="French Disko")
    monkeypatch.setattr(tui_radio, "now_playing", lambda station: info)

    app._maybe_poll_radio(_radio_status("radio:kalx"))
    _drain(workers)

    assert app.radio_now_playing == info
    assert labels[-1] == "KALX 90.7FM · Stereolab - French Disko"
    # Within the poll window no new fetch is scheduled.
    app._maybe_poll_radio(_radio_status("radio:kalx"))
    assert workers == []


def test_radio_poll_failure_reports_once_and_clears_when_stopped(
    monkeypatch, tmp_path
) -> None:
    app, _, statuses, _, workers = _make_app(monkeypatch, tmp_path)

    def boom(station):
        raise OSError("stream down")

    monkeypatch.setattr(tui_radio, "now_playing", boom)

    app._maybe_poll_radio(_radio_status("radio:bytefm"))
    _drain(workers)

    assert statuses[-1] == "Radio track info unavailable: stream down"
    app._maybe_poll_radio(_radio_status(None))
    assert app.radio_now_playing is None
    assert app._radio_poll_video_id is None


def test_favorite_during_radio_likes_resolved_song_on_ytm(monkeypatch, tmp_path) -> None:
    app, _, statuses, _, workers = _make_app(monkeypatch, tmp_path)
    monkeypatch.setattr(tui_radio, "_has_login", lambda: True)
    station = station_candidate(stations()[1])
    app.candidates_by_video_id[station.video_id] = station
    app.current_candidate = station
    app.radio_now_playing = RadioNowPlaying(
        station="KALX 90.7FM", artist="Stereolab", song="French Disko"
    )
    FakeYTMClient.results = [
        SongCandidate(
            video_id="ytm1",
            title="French Disko",
            artists=["Stereolab"],
            result_type="song",
            duration_seconds=200,
        )
    ]
    monkeypatch.setattr(app, "_focus_context", lambda: "other")

    app.action_toggle_favorite()
    _drain(workers)

    assert FakeYTMClient.rated == [("ytm1", "LIKE")]
    assert FavoritesStore().ids() == {"ytm1"}
    assert statuses[-1] == "Liked on YouTube Music: Stereolab - French Disko."


def test_favorite_during_radio_requires_login_and_track_info(
    monkeypatch, tmp_path
) -> None:
    app, _, statuses, _, workers = _make_app(monkeypatch, tmp_path)
    station = station_candidate(stations()[0])
    app.current_candidate = station
    monkeypatch.setattr(app, "_focus_context", lambda: "other")

    app.action_toggle_favorite()
    assert statuses[-1] == tui_radio.NO_TRACK_INFO_MESSAGE

    app.radio_now_playing = RadioNowPlaying(station="ByteFM", artist="Sault", song="Wildfires")
    app.action_toggle_favorite()
    assert statuses[-1] == tui_radio.LOGIN_FIRST_MESSAGE
    assert workers == []


def test_favorite_during_radio_reports_unresolvable_song(monkeypatch, tmp_path) -> None:
    app, _, statuses, _, workers = _make_app(monkeypatch, tmp_path)
    monkeypatch.setattr(tui_radio, "_has_login", lambda: True)
    app.current_candidate = station_candidate(stations()[0])
    app.radio_now_playing = RadioNowPlaying(station="ByteFM", artist="Obscure", song="B-side")
    FakeYTMClient.results = []
    monkeypatch.setattr(app, "_focus_context", lambda: "other")

    app.action_toggle_favorite()
    _drain(workers)

    assert FakeYTMClient.rated == []
    assert "No confident YouTube Music match" in statuses[-1]


def test_local_fav_syncs_like_to_ytm(monkeypatch, tmp_path) -> None:
    app, _, _, _, workers = _make_app(monkeypatch, tmp_path)
    monkeypatch.setattr(tui_radio, "_has_login", lambda: True)
    song = SongCandidate(video_id="v1", title="Myth", artists=["Beach House"])
    app.current_candidate = song
    monkeypatch.setattr(app, "_focus_context", lambda: "other")

    app.action_toggle_favorite()  # fav
    _drain(workers)
    app.action_toggle_favorite()  # unfav
    _drain(workers)

    assert FakeYTMClient.rated == [("v1", "LIKE"), ("v1", "INDIFFERENT")]


def test_local_fav_skips_ytm_sync_when_logged_out(monkeypatch, tmp_path) -> None:
    app, _, _, _, workers = _make_app(monkeypatch, tmp_path)
    app.current_candidate = SongCandidate(video_id="v1", title="Myth")
    monkeypatch.setattr(app, "_focus_context", lambda: "other")

    app.action_toggle_favorite()
    _drain(workers)

    assert FakeYTMClient.rated == []


def test_stale_poll_result_does_not_delay_next_station(monkeypatch, tmp_path) -> None:
    app, _, _, labels, workers = _make_app(monkeypatch, tmp_path)
    infos = {
        "radio:bytefm": RadioNowPlaying(station="ByteFM", artist="A", song="One"),
        "radio:kalx": RadioNowPlaying(station="KALX 90.7FM", artist="B", song="Two"),
    }
    current = {"video_id": "radio:bytefm"}
    monkeypatch.setattr(
        tui_radio, "now_playing", lambda station: infos[f"radio:{station.key}"]
    )

    app._maybe_poll_radio(_radio_status("radio:bytefm"))
    # The station changes while the bytefm fetch is still in flight.
    app._maybe_poll_radio(_radio_status("radio:kalx"))
    current["video_id"] = "radio:kalx"
    _drain(workers)  # stale bytefm result lands first, then nothing yet for kalx

    assert app.radio_now_playing is None  # stale result was discarded
    app._maybe_poll_radio(_radio_status("radio:kalx"))  # next tick polls at once
    _drain(workers)

    assert app.radio_now_playing == infos["radio:kalx"]
    assert labels[-1] == "KALX 90.7FM · B - Two"
