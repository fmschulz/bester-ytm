"""Searchable keyboard guide derived from the running app's bindings."""

from __future__ import annotations

from collections.abc import Iterable

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

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
    "leave_stage": "Stage & navigation",
    "auth_status": "Other",
    "quit": "Other",
}

ACTION_DESCRIPTIONS = {
    "focus_search": "Focus search; type a query and press Enter",
    "play_selected": "Play queue row; play/add result or marked songs",
    "help": "Open this guide (F1 also works while typing)",
    "toggle_favorite": "Toggle favorite for focused song; otherwise the playing song",
    "show_favorites": "Browse saved favorites on this device",
    "show_playlists": "Browse local and YouTube playlists",
    "save_queue_playlist": "Save the current queue as a local playlist",
    "pause_resume": "Mark a search result; pause/resume elsewhere",
    "toggle_playback": "Pause/resume playback from any pane",
    "add_to_queue": "Add highlighted song/album or marked songs",
    "remove_from_queue": "Remove the highlighted queue row",
    "clear_queue": "Clear the queue",
    "move_queue_track_up": "Move highlighted queue row up",
    "move_queue_track_down": "Move highlighted queue row down",
    "toggle_select": "Mark/unmark a song in results",
    "range_select": "Mark a range from the last marked result",
    "cycle_visualizer": "Cycle visualizer effects, including Astra",
    "toggle_stage": "Open/close the immersive visualizer stage",
    "toggle_tools": "Open workspace tools; toggle them on a narrow terminal",
    "command_palette": "Choose a theme or run a command",
    "leave_stage": "Return from the stage to the library",
    "cycle_transition": "Cycle the track transition style",
    "fade_shorter": "Shorten the transition fade",
    "fade_longer": "Lengthen the transition fade",
}

HelpRow = tuple[str, str]


def _as_binding(binding: BindingType) -> Binding:
    return binding if isinstance(binding, Binding) else Binding(*binding)


def key_display(binding: Binding) -> str:
    return binding.key_display or binding.key


def help_sections(bindings: Iterable[BindingType]) -> list[tuple[str, list[HelpRow]]]:
    """Include every binding, with context where a short footer label is ambiguous."""
    grouped: dict[str, list[HelpRow]] = {section: [] for section in SECTION_ORDER}
    for entry in bindings:
        binding = _as_binding(entry)
        section = ACTION_SECTIONS.get(binding.action, "Other")
        description = ACTION_DESCRIPTIONS.get(binding.action, binding.description or binding.action)
        grouped[section].append((key_display(binding), description))
    return [(section, rows) for section, rows in grouped.items() if rows]


class HelpScreen(ModalScreen[None]):
    """Keep search and exit controls visible while the shortcut list scrolls."""

    DEFAULT_CSS = """
    HelpScreen { align: center middle; background: #040813 85%; }
    HelpScreen #help-panel {
        width: 88; max-width: 96%; height: 90%;
        border: round #55d9e8; background: #0b1220; padding: 1 2;
    }
    HelpScreen #help-heading { height: 3; align-vertical: middle; }
    HelpScreen #help-title { width: 1fr; color: #55d9e8; text-style: bold; }
    HelpScreen #help-close { min-width: 12; width: 12; }
    HelpScreen #help-intro { height: auto; margin-bottom: 1; color: #c4cfdf; }
    HelpScreen #help-filter { height: 3; margin-bottom: 1; }
    HelpScreen #help-shortcuts { height: 1fr; scrollbar-size-vertical: 1; }
    HelpScreen .help-section { color: #55d9e8; text-style: bold; margin-top: 1; }
    HelpScreen .help-row { height: auto; min-height: 1; }
    HelpScreen .help-key { width: 15; color: #f1c77b; text-style: bold; }
    HelpScreen .help-desc { width: 1fr; height: auto; padding-left: 1; }
    HelpScreen #help-empty { height: auto; color: #c4cfdf; padding: 1 0; }
    HelpScreen #help-hint { height: auto; color: #8b9bb4; margin-top: 1; }
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
