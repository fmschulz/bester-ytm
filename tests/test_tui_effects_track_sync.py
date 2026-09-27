"""Refresh tick vs Now Playing label: resync only on real track changes."""

from __future__ import annotations

from bester_ytm import tui
from bester_ytm.playback import PlaybackStatus
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.stores import FavoritesStore
from bester_ytm.tui_player import FAVORITE_GLYPH


class FakeStatic:
    def __init__(self) -> None:
        self.value = ""
        self.update_count = 0

    def update(self, value: str) -> None:
        self.value = value
        self.update_count += 1


class FakeButton:
    def __init__(self) -> None:
        self.label = ""
        self.classes: set[str] = set()

    def set_class(self, enabled: bool, name: str) -> None:
        if enabled:
            self.classes.add(name)
        else:
            self.classes.discard(name)


class FakePlayback:
    def __init__(self, current: str | None) -> None:
        self.current_video_id = current
        self.queue: list[str] = ["v2", "v3"]

    def status(self) -> PlaybackStatus:
        return PlaybackStatus(
            running=self.current_video_id is not None,
            current_video_id=self.current_video_id,
            queue_size=len(self.queue),
        )


def _make_app(monkeypatch, tmp_path, playback) -> tuple[tui.BesterYTMApp, dict, list[str]]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    widgets = {"#track": FakeStatic(), "#favorite-playing-button": FakeButton()}
    app = tui.BesterYTMApp()
    app.playback = playback  # type: ignore[assignment]
    app.candidates_by_video_id = {
        "v1": SongCandidate(video_id="v1", title="One", artists=["A"]),
        "v2": SongCandidate(video_id="v2", title="Two", artists=["B"]),
    }
    statuses: list[str] = []
    monkeypatch.setattr(
        app, "_query_optional", lambda selector, widget_type=None: widgets.get(selector)
    )
    monkeypatch.setattr(app, "_set_status", statuses.append)
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: work.close())
    return app, widgets, statuses


def test_track_change_updates_now_playing_label(monkeypatch, tmp_path) -> None:
    playback = FakePlayback("v1")
    app, widgets, _ = _make_app(monkeypatch, tmp_path, playback)
    app._refresh_playback()
    assert widgets["#track"].value == "One  A"

    playback.current_video_id = "v2"
    app._refresh_playback()

    assert widgets["#track"].value == "Two  B"


def test_tick_with_unchanged_track_does_not_rerender_label(monkeypatch, tmp_path) -> None:
    app, widgets, _ = _make_app(monkeypatch, tmp_path, FakePlayback("v1"))

    app._refresh_playback()  # first tick syncs the newly playing track
    renders = widgets["#track"].update_count
    app._refresh_playback()
    app._refresh_playback()

    assert widgets["#track"].update_count == renders


def test_player_star_fills_for_a_faved_track(monkeypatch, tmp_path) -> None:
    app, widgets, _ = _make_app(monkeypatch, tmp_path, FakePlayback("v1"))
    FavoritesStore().toggle(app.candidates_by_video_id["v1"])

    app._refresh_playback()

    star = widgets["#favorite-playing-button"]
    assert widgets["#track"].value == "One  A"
    assert star.label == FAVORITE_GLYPH
    assert "is-favorite" in star.classes


def test_corrupt_favorites_store_degrades_to_status_message(monkeypatch, tmp_path) -> None:
    """A corrupt favorites.json surfaces its actionable error instead of crashing the tick."""
    app, widgets, statuses = _make_app(monkeypatch, tmp_path, FakePlayback("v1"))
    store = FavoritesStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{broken", encoding="utf-8")

    app._refresh_playback()

    assert widgets["#track"].value == "One  A"
    assert "corrupt" in statuses[-1]
    assert "Move the file aside" in statuses[-1]
