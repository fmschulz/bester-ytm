"""One-line rows for the results and queue lists.

Each row splits into a ``label`` (marker, title, artist, detail) and a ``tail``
(favorite star, then a duration or the kind of item) and lays them out to the width
it gets: the label is cut with an ellipsis, the tail stays right-aligned. Markers
are flags, so marking or starring a row never rewrites label strings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import events
from textual.content import Content
from textual.reactive import reactive
from textual.widgets import ListItem

from .playlist_plan import SongCandidate
from .search_query import SearchItem
from .tui_player import FAVORITE_GLYPH, PLAY_GLYPH, format_time

if TYPE_CHECKING:
    from .tui import BesterYTMApp

MARKED_GLYPH = "●"
KIND_TAGS = {"album": "album", "playlist": "playlist", "local_playlist": "local", "radio": "radio"}


class Row(ListItem):
    """A list row that fits its label and right-aligned tail into one line."""

    @property
    def label(self) -> Content:
        """The left part: what the row is."""
        raise NotImplementedError

    @property
    def short_label(self) -> Content:
        """The label to fall back on when the full one does not fit."""
        return self.label

    @property
    def tail(self) -> Content:
        """The right part: favorite star and duration or kind."""
        raise NotImplementedError

    def render(self) -> Content:
        width = self.content_size.width
        tail = self.tail
        room = max(0, width - tail.cell_length - 1)
        label = self.label if self.label.cell_length <= room else self.short_label
        label = label.truncate(room, ellipsis=True)
        gap = max(1, width - label.cell_length - tail.cell_length)
        return Content.assemble(label, " " * gap, tail)


class ResultRow(Row):
    """A search result. Marked rows queue together; favorites carry a star."""

    marked: reactive[bool] = reactive(False)
    favorite: reactive[bool] = reactive(False)

    def __init__(self, search_item: SearchItem, *, favorite: bool = False) -> None:
        super().__init__()
        self.search_item = search_item
        self.candidate = search_item.candidate
        self.playlist_id = search_item.playlist_id
        self.playlist_title = search_item.title
        self.set_reactive(ResultRow.favorite, favorite)

    @property
    def label(self) -> Content:
        item = self.search_item
        marker = (MARKED_GLYPH if self.marked else " ", "bold $accent")
        if item.candidate is not None and item.item_type == "song":
            return Content.assemble(marker, " ", *_song_parts(item.candidate))
        details = item.subtitle
        if item.year and item.year not in details:
            details = f"{details} ({item.year})" if details else item.year
        return Content.assemble(
            marker, " ", (item.title, "bold"), ("  " + details, "dim") if details else ""
        )

    @property
    def short_label(self) -> Content:
        candidate = self.search_item.candidate
        if candidate is None or self.search_item.item_type != "song":
            return self.label
        marker = (MARKED_GLYPH if self.marked else " ", "bold $accent")
        return Content.assemble(marker, " ", *_song_parts(candidate, album=False))

    @property
    def tail(self) -> Content:
        item = self.search_item
        if item.item_type != "song":
            kind = KIND_TAGS.get(item.item_type, item.item_type)
        else:
            kind = _duration(item.candidate)
        return Content.assemble(_star(self.favorite), (kind, "dim"))

    def _on_click(self, event: events.Click) -> None:  # type: ignore[override]
        # Shift+click extends the marked range before ListView treats it as a pick.
        app = cast("BesterYTMApp", self.app)
        if event.shift and app._range_select_clicked_result(self):
            event.stop()
            event.prevent_default()
            return
        super()._on_click(event)


class QueueRow(Row):
    """A queue entry. The playing row carries a play mark; rows already played dim."""

    def __init__(
        self,
        video_id: str,
        position: int,
        candidate: SongCandidate | None,
        *,
        is_playing: bool = False,
        is_played: bool = False,
        is_favorite: bool = False,
    ) -> None:
        super().__init__(classes="playing" if is_playing else "played" if is_played else "")
        self.video_id = video_id
        self.position = position
        self.candidate = candidate
        self.is_playing = is_playing
        self.is_favorite = is_favorite

    @property
    def label(self) -> Content:
        marker = (PLAY_GLYPH if self.is_playing else " ", "bold $accent")
        number = (f" {self.position:>2}  ", "dim")
        if self.candidate is None:
            return Content.assemble(marker, number, self.video_id)
        return Content.assemble(marker, number, *_song_parts(self.candidate, album=False))

    @property
    def tail(self) -> Content:
        return Content.assemble(_star(self.is_favorite), (_duration(self.candidate), "dim"))


def queue_heading(title: str, count: int, seconds: float) -> Content:
    """``Late Night  14 tracks, 1 h 04 min``: the queue's name, size and running time."""
    tracks = f"{count} track" if count == 1 else f"{count} tracks"
    summary = f"{tracks}, {_running_time(seconds)}" if seconds else tracks
    return Content.assemble((title, "bold"), ("  " + summary, "dim"))


def _running_time(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def _song_parts(candidate: SongCandidate, *, album: bool = True) -> list[str | tuple[str, str]]:
    parts: list[str | tuple[str, str]] = [(candidate.title, "bold")]
    if candidate.artist_text:
        parts.append("  " + candidate.artist_text)
    if album and candidate.album:
        parts.append(("  " + candidate.album, "dim"))
    return parts


def _star(is_favorite: bool) -> tuple[str, str]:
    return (FAVORITE_GLYPH + " ", "$accent") if is_favorite else ("  ", "")


def _duration(candidate: SongCandidate | None) -> str:
    if candidate is None or not candidate.duration_seconds:
        return ""
    return format_time(candidate.duration_seconds)
