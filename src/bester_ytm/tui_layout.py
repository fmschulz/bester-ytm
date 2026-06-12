"""Static widget tree for the BesterYTMApp screen."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import (
    Button,
    Input,
    Label,
    ListView,
    ProgressBar,
    Select,
    Static,
    TextArea,
)

from .playlist_plan import parse_seed_text
from .tui_splitter import PaneSplitter
from .tui_visuals import EFFECT_OPTIONS


class BuilderTextArea(TextArea):
    """Seed box where Enter on a prose prompt submits instead of adding a line."""

    class Submitted(Message):
        pass

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter" and self._is_prose_prompt():
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted())
            return
        await super()._on_key(event)

    def _is_prose_prompt(self) -> bool:
        text = self.text.strip()
        return bool(text) and not parse_seed_text(text, "builder")


def build_layout(visualizer_text: str, effect: str = "mythos") -> ComposeResult:
    with Horizontal(id="main"):
        with Vertical(id="left"):
            yield Input(placeholder="Search YouTube Music", id="search")
            yield ListView(id="results")
            yield Static("", id="left-visual")
        yield PaneSplitter("left", "right", grows_leftward=False)
        with Vertical(id="center"):
            yield Label("Playlist / Queue", id="queue-title")
            yield ListView(id="queue")
            yield Static("", id="big-visual")
        yield PaneSplitter("right", "left", grows_leftward=True)
        with Vertical(id="right"):
            yield from _build_player_panel(visualizer_text, effect)


def _build_player_panel(visualizer_text: str, effect: str = "mythos") -> ComposeResult:
    yield Label("Now Playing", id="player-title")
    yield Static("No track playing.", id="track")
    yield Static("0:00 / 0:00", id="progress-time")
    yield ProgressBar(total=1, show_eta=False, id="progress")
    yield Static(visualizer_text, id="visualizer")
    with Horizontal(id="transport"):
        yield Button("Prev", id="prev-button", compact=True)
        yield Button("-10s", id="rewind-button", compact=True)
        yield Button("Play", id="play-button", compact=True)
        yield Button("+10s", id="forward-button", compact=True)
        yield Button("Next", id="next-button", compact=True)
    with Horizontal(id="queue-actions"):
        yield Button("Shuffle", id="shuffle-button", compact=True)
        yield Button("Mix", id="transition-button", compact=True)
        yield Button("Clear", id="clear-button", compact=True)
    with Horizontal(id="fade-row"):
        yield Button("Fade-", id="fade-down-button", compact=True)
        yield Button("Fade+", id="fade-up-button", compact=True)
    yield Static("Vol --", id="volume-status")
    with Horizontal(id="volume-row"):
        yield Button("Vol-", id="volume-down-button", compact=True)
        yield Button("Vol+", id="volume-up-button", compact=True)
        yield Button("Mute", id="mute-button", compact=True)
    yield Label("Track Details", id="track-details-title")
    yield Static("Rating --  Tags --", id="track-metadata")
    yield Input(placeholder="tags: metal, favorite", id="tags-input")
    yield Input(placeholder="local playlist name", id="playlist-name")
    with Horizontal(id="track-actions"):
        yield Button("Rate-", id="rate-down-button", compact=True)
        yield Button("Rate+", id="rate-up-button", compact=True)
        yield Button("Save Tags", id="save-tags-button", compact=True)
    with Horizontal(id="playlist-actions"):
        yield Button("Add", id="add-local-playlist-button", compact=True)
        yield Button("Remove", id="remove-local-playlist-button", compact=True)
        yield Button("Save", id="save-queue-button", compact=True)
    yield Label("Playlist Builder", id="builder-title")
    yield BuilderTextArea(id="builder", language="markdown")
    with Horizontal(id="builder-actions"):
        yield Button("Build Playlist", id="build-button", compact=True)
    with Horizontal(id="effect-row"):
        yield Label("Visuals", id="effect-label")
        yield Select(EFFECT_OPTIONS, value=effect, allow_blank=False, id="effect-select")
    yield Static("", id="status")
    yield Static("", id="right-visual")
