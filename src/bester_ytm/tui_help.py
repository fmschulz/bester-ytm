"""Keyboard help overlay listing every app binding, grouped by purpose."""

from __future__ import annotations

from collections.abc import Iterable

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

SECTION_ORDER = (
    "Transport",
    "Seek / Volume",
    "Queue",
    "Playlists",
    "Selection",
    "Panes / Visuals",
    "Other",
)

ACTION_SECTIONS = {
    "pause_resume": "Transport",
    "play_selected": "Transport",
    "next_track": "Transport",
    "previous_track": "Transport",
    "cycle_transition": "Transport",
    "fade_shorter": "Transport",
    "fade_longer": "Transport",
    "seek_backward": "Seek / Volume",
    "seek_forward": "Seek / Volume",
    "seek_large_backward": "Seek / Volume",
    "seek_large_forward": "Seek / Volume",
    "volume_down": "Seek / Volume",
    "volume_up": "Seek / Volume",
    "mute": "Seek / Volume",
    "add_to_queue": "Queue",
    "play_album": "Queue",
    "add_similar": "Queue",
    "shuffle_queue": "Queue",
    "remove_from_queue": "Queue",
    "clear_queue": "Queue",
    "move_queue_track_up": "Queue",
    "move_queue_track_down": "Queue",
    "show_playlists": "Playlists",
    "save_queue_playlist": "Playlists",
    "build_playlist": "Playlists",
    "toggle_select": "Selection",
    "range_select": "Selection",
    "focus_next": "Panes / Visuals",
    "focus_previous": "Panes / Visuals",
    "cycle_visualizer": "Panes / Visuals",
    "focus_search": "Other",
    "cycle_rating": "Other",
    "favorite_current": "Other",
    "auth_status": "Other",
    "help": "Other",
    "quit": "Other",
}

HelpRow = tuple[str, str]


def _as_binding(binding: BindingType) -> Binding:
    return binding if isinstance(binding, Binding) else Binding(*binding)


def key_display(binding: Binding) -> str:
    return binding.key_display or binding.key


def help_sections(bindings: Iterable[BindingType]) -> list[tuple[str, list[HelpRow]]]:
    """Group app bindings into (section, rows) so the overlay never drifts."""
    grouped: dict[str, list[HelpRow]] = {section: [] for section in SECTION_ORDER}
    for entry in bindings:
        binding = _as_binding(entry)
        section = ACTION_SECTIONS.get(binding.action, "Other")
        row = (key_display(binding), binding.description or binding.action)
        grouped[section].append(row)
    return [(section, rows) for section, rows in grouped.items() if rows]


class HelpScreen(ModalScreen[None]):
    """Modal overlay rendering every key binding of the running app."""

    BINDINGS = [
        Binding("escape", "dismiss_help", "Close", show=False),
        Binding("q", "dismiss_help", "Close", show=False),
        Binding("question_mark", "dismiss_help", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-panel"):
            yield Static("Keyboard shortcuts", id="help-title")
            for section, rows in help_sections(self.app.BINDINGS):
                yield from self._compose_section(section, rows)
            yield Static("escape / q / ? closes this overlay", id="help-hint")

    def _compose_section(self, section: str, rows: list[HelpRow]) -> ComposeResult:
        yield Static(section, classes="help-section")
        for key, description in rows:
            with Horizontal(classes="help-row"):
                yield Static(key, classes="help-key")
                yield Static(description, classes="help-desc")

    def action_dismiss_help(self) -> None:
        self.dismiss(None)
