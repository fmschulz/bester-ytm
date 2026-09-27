"""Static widget tree for the BesterYTMApp screen."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import (
    Button,
    Collapsible,
    Input,
    Label,
    ListView,
    ProgressBar,
    Select,
    Static,
    TextArea,
)

from .playlist_plan import parse_seed_text
from .tui_album import AlbumTree
from .tui_splitter import PaneSplitter
from .tui_stage import Stage
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


class WorkspaceScreen(Screen):
    """Restore responsive classes after resizing with a modal on top."""

    def on_screen_resume(self) -> None:
        self.set_class(self.app.size.width < 110, "compact")
        self.set_class(self.app.size.height < 35, "short")


def build_layout(visualizer_text: str, effect: str = "astra") -> ComposeResult:
    with Horizontal(id="navigation"):
        yield Label("B / Y  •  MUSIC TERMINAL", id="brand")
        yield Button("Favorites", id="favorites-button", compact=True)
        yield Button("Playlists", id="playlists-button", compact=True)
        yield Button("Radio", id="radio-button", compact=True)
        yield Button("Tools", id="tools-button", compact=True)
        yield Button("? Help", id="help-button", compact=True)
    with Horizontal(id="main"):
        with Vertical(id="left"):
            yield Label("DISCOVER", id="library-title")
            yield Input(placeholder="Search songs, artists, albums…", id="search")
            yield Static(
                "Find something worth keeping.\n\n"
                "Search a song or artist, then Enter.\n"
                "Try album: Discovery or radio:\n\n"
                "Favorites keeps your finds on this device.\n"
                "F1 opens the keyboard guide.",
                id="library-empty", markup=False,
            )
            yield ListView(id="results")
            yield AlbumTree("albums", id="album-tree")
            yield Static("Enter play / add   Space mark   f favorite", id="results-hint")
        yield PaneSplitter("left", "right", grows_leftward=False)
        with Vertical(id="center"):
            yield Label("Queue (0)", id="queue-title", markup=False)
            yield ListView(id="queue")
            yield Static("Enter play   d remove   j/k reorder", id="queue-hint")
        yield PaneSplitter("right", "left", grows_leftward=True)
        with Vertical(id="right"):
            yield Label("YOUR WORKSPACE", id="tools-title")
            yield from _build_tools()
    with Vertical(id="stage"):
        with Horizontal(id="stage-heading"):
            yield Select(
                EFFECT_OPTIONS,
                value=effect,
                allow_blank=False,
                compact=True,
                id="effect-select",
                tooltip="Scene (v cycles)",
            )
            yield Button("Full screen", id="stage-button", compact=True, tooltip="Full screen (V)")
        yield Stage(effect, id="big-visual")
    with Vertical(id="player"):
        with Horizontal(id="now-playing"):
            yield Label("NOW PLAYING", id="player-title")
            yield Static("No track playing.", id="track", markup=False)
            yield Static("0:00 / 0:00", id="progress-time")
        yield ProgressBar(total=1, show_eta=False, show_percentage=False, id="progress")
        with Horizontal(id="controls"):
            with Horizontal(id="transport"):
                yield Button("Prev", id="prev-button", compact=True)
                yield Button("-10s", id="rewind-button", compact=True)
                yield Button("Play", id="play-button", compact=True)
                yield Button("+10s", id="forward-button", compact=True)
                yield Button("Next", id="next-button", compact=True)
            with Horizontal(id="volume-row"):
                yield Button("Vol-", id="volume-down-button", compact=True)
                yield Button("Vol+", id="volume-up-button", compact=True)
                yield Button("Mute", id="mute-button", compact=True)
            yield Button("Favorite playing", id="favorite-playing-button", compact=True)
            yield Static(visualizer_text, id="visualizer")
    yield Static("", id="status", markup=False)


def _build_tools() -> ComposeResult:
    with Collapsible(title="Playlist / Queue", collapsed=False, id="playlist-tools"):
        yield Input(placeholder="Playlist name", id="playlist-name")
        with Horizontal(id="playlist-actions"):
            yield Button("New", id="new-playlist-button", compact=True)
            yield Button("Save", id="save-queue-button", compact=True)
            yield Button("Add", id="add-local-playlist-button", compact=True)
            yield Button("Remove", id="remove-local-playlist-button", compact=True)
        with Horizontal(id="queue-actions"):
            yield Button("Shuffle", id="shuffle-button", compact=True)
            yield Button("Clear", id="clear-button", compact=True)
    with Collapsible(title="Playlist builder", collapsed=False, id="builder-tools"):
        yield BuilderTextArea(id="builder", language="markdown")
        with Horizontal(id="builder-actions"):
            yield Button("Build Playlist", id="build-button", compact=True)
    with Collapsible(title="DJ / Crossfade", collapsed=True, id="mix-tools"):
        with Horizontal(id="transition-row"):
            yield Button("Mix", id="transition-button", compact=True)
            yield Button("Fade-", id="fade-down-button", compact=True)
            yield Button("Fade+", id="fade-up-button", compact=True)
