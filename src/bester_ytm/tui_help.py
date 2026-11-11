"""Searchable keyboard guide derived from the running app's bindings."""

from __future__ import annotations

from collections.abc import Iterable

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from .tui_visuals import EFFECT_LABELS

SECTION_ORDER = (
    "Start here",
    "Favorites & library",
    "Transport",
    "Seek & volume",
    "Queue",
    "Selection",
    "Stage & navigation",
    "Other",
)

ACTION_SECTIONS = {
    "focus_search": "Start here",
    "play_selected": "Start here",
    "help": "Start here",
    "toggle_favorite": "Favorites & library",
    "show_favorites": "Favorites & library",
    "show_playlists": "Favorites & library",
    "show_radio": "Favorites & library",
    "new_playlist": "Favorites & library",
    "add_to_local_playlist": "Favorites & library",
    "remove_from_playlist": "Favorites & library",
    "save_queue_playlist": "Favorites & library",
    "build_playlist": "Favorites & library",
    "pause_resume": "Transport",
    "toggle_playback": "Transport",
    "next_track": "Transport",
    "previous_track": "Transport",
    "cycle_transition": "Transport",
    "fade_shorter": "Transport",
    "fade_longer": "Transport",
    "seek_backward": "Seek & volume",
    "seek_forward": "Seek & volume",
    "seek_large_backward": "Seek & volume",
    "seek_large_forward": "Seek & volume",
    "volume_down": "Seek & volume",
    "volume_up": "Seek & volume",
    "mute": "Seek & volume",
    "add_to_queue": "Queue",
    "play_album": "Queue",
    "add_similar": "Queue",
    "shuffle_queue": "Queue",
    "remove_from_queue": "Queue",
    "clear_queue": "Queue",
    "move_queue_track_up": "Queue",
    "move_queue_track_down": "Queue",
    "toggle_select": "Selection",
    "range_select": "Selection",
    "focus_next": "Stage & navigation",
    "focus_previous": "Stage & navigation",
    "cycle_visualizer": "Stage & navigation",
    "toggle_stage": "Stage & navigation",
    "toggle_tools": "Stage & navigation",
    "command_palette": "Stage & navigation",
    "cancel_or_leave": "Stage & navigation",
    "auth_status": "Other",
    "quit": "Other",
}

ACTION_DESCRIPTIONS = {
    "focus_search": "Focus search, then type a query and press Enter.",
    "play_selected": "Play a queue row; play or queue a result or marked songs.",
    "help": "Open this guide; F1 also works while typing.",
    "toggle_favorite": "Toggle favorite for the focused song, else the playing song.",
    "show_favorites": "Browse saved favorites on this device.",
    "show_playlists": "Browse local and YouTube playlists.",
    "show_radio": "Browse web radio stations.",
    "new_playlist": "Start a new playlist and focus its name field.",
    "add_to_local_playlist": "Add the highlighted track to the named local playlist.",
    "remove_from_playlist": "Remove the highlighted track from the loaded playlist.",
    "save_queue_playlist": "Save the current queue as a local playlist.",
    "build_playlist": "Build a playlist from seeds or a brief in the builder box.",
    "pause_resume": "Mark a search result; pause or resume elsewhere.",
    "toggle_playback": "Pause or resume playback from any pane.",
    "next_track": "Play the next queued track, leaving a radio station if one plays.",
    "previous_track": "Play the previous track.",
    "add_to_queue": "Add the highlighted song or album, or marked songs, to the queue.",
    "play_album": "Replace the queue and play the album or marked songs now.",
    "add_similar": "Queue similar songs; type digits after g to set the count.",
    "shuffle_queue": "Shuffle the upcoming tracks in the queue.",
    "remove_from_queue": "Remove a queue row; press twice on a playlist to delete it.",
    "clear_queue": "Clear the queue and keep the playing track.",
    "move_queue_track_up": "Move the highlighted queue row up.",
    "move_queue_track_down": "Move the highlighted queue row down.",
    "toggle_select": "Mark or unmark a song in results.",
    "range_select": "Mark a range from the first marked result.",
    "cycle_visualizer": f"Cycle the stage scenes: {', '.join(EFFECT_LABELS.values())}.",
    "toggle_stage": "Toggle the full-screen stage; Esc returns.",
    "toggle_tools": "Open workspace tools; toggle them on a narrow terminal.",
    "command_palette": "Choose a theme or run a command.",
    "cancel_or_leave": "Cancel a running build, leave the full stage, or leave an input.",
    "cycle_transition": "Cycle the track transition style.",
    "fade_shorter": "Shorten the transition fade.",
    "fade_longer": "Lengthen the transition fade.",
    "seek_backward": "Seek backward by 10 seconds.",
    "seek_forward": "Seek forward by 10 seconds.",
    "seek_large_backward": "Seek backward by 30 seconds.",
    "seek_large_forward": "Seek forward by 30 seconds.",
    "volume_down": "Lower the playback volume.",
    "volume_up": "Raise the playback volume.",
    "mute": "Mute or unmute playback.",
    "focus_next": "Focus the next control.",
    "focus_previous": "Focus the previous control.",
    "auth_status": "Check the YouTube Music login status.",
    "quit": "Stop playback and quit the app.",
}

HelpRow = tuple[str, str]


def _as_binding(binding: BindingType) -> Binding:
    return binding if isinstance(binding, Binding) else Binding(*binding)


def key_display(binding: Binding) -> str:
    if binding.key_display:
        return binding.key_display
    names = {"escape": "Esc", "comma": ",", "full_stop": ".", "slash": "/"}
    parts = binding.key.split("+")
    return "+".join(
        names.get(part, part.upper() if len(parts) > 1 and len(part) == 1 else part.title())
        if len(part) > 1 or len(parts) > 1
        else part
        for part in parts
    )


def help_sections(bindings: Iterable[BindingType]) -> list[tuple[str, list[HelpRow]]]:
    """Group all keys for an action in one row with a full description."""
    grouped: dict[str, list[HelpRow]] = {section: [] for section in SECTION_ORDER}
    actions: dict[str, list[str]] = {}
    for entry in bindings:
        binding = _as_binding(entry)
        actions.setdefault(binding.action, []).append(key_display(binding))
    for action, keys in actions.items():
        section = ACTION_SECTIONS.get(action, "Other")
        grouped[section].append((" / ".join(keys), ACTION_DESCRIPTIONS[action]))
    return [(section, rows) for section, rows in grouped.items() if rows]


class HelpScreen(ModalScreen[None]):
    """Keep search and exit controls visible while the shortcut list scrolls."""

    DEFAULT_CSS = """
    HelpScreen { align: center middle; background: $background 85%; }
    HelpScreen #help-panel {
        width: 88; max-width: 96%; height: 90%;
        border: round $primary; background: $surface; padding: 1 2;
    }
    HelpScreen #help-heading { height: 3; align-vertical: middle; }
    HelpScreen #help-title { width: 1fr; color: $primary; text-style: bold; }
    HelpScreen #help-close { min-width: 12; width: 12; }
    HelpScreen #help-intro { height: auto; margin-bottom: 1; color: $foreground 85%; }
    HelpScreen #help-filter { height: 3; margin-bottom: 1; }
    HelpScreen #help-shortcuts { height: 1fr; scrollbar-size-vertical: 1; }
    HelpScreen .help-section { color: $primary; text-style: bold; margin-top: 1; }
    HelpScreen .help-row { height: auto; min-height: 1; }
    HelpScreen .help-key { width: 15; color: $warning; text-style: bold; }
    HelpScreen .help-desc { width: 1fr; height: auto; padding-left: 1; }
    HelpScreen #help-empty { height: auto; color: $foreground 85%; padding: 1 0; }
    HelpScreen #help-hint { height: auto; color: $text-muted; margin-top: 1; }
    HelpScreen.short #help-panel { padding: 0 1; height: 96%; }
    HelpScreen.short #help-heading { height: 1; }
    HelpScreen.short #help-intro { display: none; }
    HelpScreen.short #help-hint { height: 1; }
    """

    BINDINGS = [
        Binding("escape", "dismiss_help", "Close", show=False, priority=True),
        Binding("f1", "dismiss_help", "Close", show=False, priority=True),
        Binding("q", "dismiss_help", "Close", show=False),
        Binding("question_mark", "dismiss_help", "Close", show=False),
        Binding("slash", "filter_help", "Filter", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-panel"):
            with Horizontal(id="help-heading"):
                yield Static("KEYBOARD GUIDE", id="help-title")
                yield Button("Close Esc", id="help-close", compact=True)
            yield Static(
                "Type a search and press Enter. Choose a song, then Enter to play/add.\n"
                "Space marks results. "
                "Ctrl+Space pauses anywhere.\n"
                "f saves the focused song (or the playing song). Ctrl+F opens favorites.\n"
                "V opens the full stage. Esc returns. F1 opens help even while typing.",
                id="help-intro",
            )
            yield Input(
                placeholder="Filter by key or action, e.g. favorite, volume, ctrl", id="help-filter"
            )
            with VerticalScroll(id="help-shortcuts"):
                for index, (section, rows) in enumerate(help_sections(self.app.BINDINGS)):
                    yield Static(section, id=f"help-section-{index}", classes="help-section")
                    for key, description in rows:
                        with Horizontal(classes=f"help-row help-group-{index}"):
                            yield Static(key, classes="help-key", markup=False)
                            yield Static(description, classes="help-desc", markup=False)
                yield Static("No shortcuts match. Try a key or action name.", id="help-empty")
            yield Static(
                "/ Filter   Tab Move focus   Scroll to browse   Esc / F1 Close", id="help-hint"
            )

    def on_mount(self) -> None:
        self.query_one("#help-empty").display = False
        self.query_one("#help-shortcuts").focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "help-filter":
            return
        query = event.value.strip().casefold()
        any_matches = False
        for index, (section, _rows) in enumerate(help_sections(self.app.BINDINGS)):
            section_matches = False
            for row in self.query(f".help-group-{index}"):
                content = " ".join(str(label.content) for label in row.query(Static))
                row.display = query in f"{section} {content}".casefold()
                section_matches |= row.display
            self.query_one(f"#help-section-{index}").display = section_matches
            any_matches |= section_matches
        self.query_one("#help-empty").display = not any_matches
        self.query_one("#help-shortcuts", VerticalScroll).scroll_home(animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close":
            self.action_dismiss_help()

    def action_filter_help(self) -> None:
        self.query_one("#help-filter", Input).focus()

    def action_dismiss_help(self) -> None:
        self.dismiss(None)
