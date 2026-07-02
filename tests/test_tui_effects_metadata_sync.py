"""Refresh tick vs Track Details: no per-tick stomping of tags input or metadata pane."""

from __future__ import annotations

from bester_ytm import tui
from bester_ytm.playback import PlaybackStatus
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.stores import TrackMetadataStore


class FakeStatic:
    def __init__(self) -> None:
        self.value = ""

    def update(self, value: str) -> None:
        self.value = value


class FakeInput:
    def __init__(self, value: str = "", has_focus: bool = False) -> None:
        self.value = value
        self.has_focus = has_focus


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


def _make_app(monkeypatch, playback) -> tuple[tui.BesterYTMApp, dict]:
    widgets = {
        "#track": FakeStatic(),
        "#track-metadata": FakeStatic(),
        "#tags-input": FakeInput(),
    }
    app = tui.BesterYTMApp()
    app.playback = playback  # type: ignore[assignment]
    app.candidates_by_video_id = {
        "v1": SongCandidate(video_id="v1", title="One", artists=["A"]),
        "v2": SongCandidate(video_id="v2", title="Two", artists=["B"]),
        "v3": SongCandidate(video_id="v3", title="Three", artists=["C"]),
    }
    monkeypatch.setattr(
        app, "_query_optional", lambda selector, widget_type=None: widgets.get(selector)
    )
    monkeypatch.setattr(app, "_set_status", lambda message: None)
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: work.close())
    return app, widgets


def test_tick_with_unchanged_track_preserves_tags_input_text(monkeypatch, tmp_path) -> None:
    """Text typed into #tags-input survives refresh ticks while the same track plays."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    app, widgets = _make_app(monkeypatch, FakePlayback("v1"))

    app._refresh_playback()  # first tick syncs the newly playing track
    widgets["#tags-input"].value = "half-typed tag"

    app._refresh_playback()
    app._refresh_playback()

    assert widgets["#tags-input"].value == "half-typed tag"


def test_tick_keeps_details_pane_on_highlighted_queue_row(monkeypatch, tmp_path) -> None:
    """The details pane follows the highlighted row; ticks must not snap it back."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    store = TrackMetadataStore()
    store.set_rating("v1", 5)
    store.set_tags("v3", ["doom"])
    app, widgets = _make_app(monkeypatch, FakePlayback("v1"))
    app._refresh_playback()

    # As on_list_view_highlighted does when the user moves to the v3 row.
    app.selected_queue_video_id = "v3"
    app._update_track_metadata("v3")
    assert "Tags doom" in widgets["#track-metadata"].value

    app._refresh_playback()

    assert "Tags doom" in widgets["#track-metadata"].value
    assert widgets["#tags-input"].value == "doom"


def test_track_change_still_updates_display(monkeypatch, tmp_path) -> None:
    """An actual track change (new current_video_id) resyncs label and details."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    TrackMetadataStore().set_tags("v2", ["groove"])
    playback = FakePlayback("v1")
    app, widgets = _make_app(monkeypatch, playback)
    app._refresh_playback()
    assert widgets["#track"].value == "A - One"

    playback.current_video_id = "v2"
    app._refresh_playback()

    assert widgets["#track"].value == "B - Two"
    assert "Tags groove" in widgets["#track-metadata"].value
    assert widgets["#tags-input"].value == "groove"


def test_track_change_keeps_details_on_highlighted_row(monkeypatch, tmp_path) -> None:
    """Even across a track change, details keep matching where r/Save Tags act."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    TrackMetadataStore().set_tags("v3", ["doom"])
    playback = FakePlayback("v1")
    app, widgets = _make_app(monkeypatch, playback)
    app._refresh_playback()
    app.selected_queue_video_id = "v3"
    app._update_track_metadata("v3")

    playback.current_video_id = "v2"
    app._refresh_playback()

    assert widgets["#track"].value == "B - Two"  # now-playing label does update
    assert "Tags doom" in widgets["#track-metadata"].value  # details stay on v3


def test_track_change_does_not_clobber_focused_tags_input(monkeypatch, tmp_path) -> None:
    """A resync while the user is typing must leave #tags-input alone."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    TrackMetadataStore().set_tags("v2", ["groove"])
    playback = FakePlayback("v1")
    app, widgets = _make_app(monkeypatch, playback)
    app._refresh_playback()
    widgets["#tags-input"].has_focus = True
    widgets["#tags-input"].value = "half-typed tag"

    playback.current_video_id = "v2"
    app._refresh_playback()

    assert widgets["#tags-input"].value == "half-typed tag"
    assert "Tags groove" in widgets["#track-metadata"].value
