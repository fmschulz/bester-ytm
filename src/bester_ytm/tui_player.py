"""The player deck: a seek bar drawn from the music's loudness, crossfader, and volume.

The seek bar remembers how loud each stretch of the current track was when it was
heard, so the played part draws the song's shape (quiet intro, drop, breakdown)
while the rest waits as a faint baseline. The crossfader shows the dual-deck
engine at work, and the volume wedge shows the level at a glance.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import groupby

from rich.segment import Segment
from textual import events
from textual.content import Content
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

from .playback_status import PlaybackStatus
from .playlist_plan import SongCandidate

LEVEL_GLYPHS = "▁▂▃▄▅▆▇█"
BASELINE = LEVEL_GLYPHS[0]
ENVELOPE_BUCKETS = 240
# The seek bar compares parts of one track, so it uses a fixed loudness scale
# rather than the stage's adaptive meter, which would lift a quiet intro to mid.
QUIET_DB = -42.0
LOUD_DB = -12.0
RAIL_CELLS = 11
PLAY_GLYPH = "▶"
PAUSE_GLYPH = "❚❚"
FAVORITE_GLYPH = "★"
NOT_FAVORITE_GLYPH = "☆"


def format_time(seconds: float | None) -> str:
    """``m:ss``, or ``h:mm:ss`` from an hour up; unknown or negative reads ``0:00``."""
    if seconds is None or seconds < 0:
        return "0:00"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def loudness(rms_db: float) -> float:
    """An RMS reading on the fixed 0..1 scale the seek bar draws."""
    return min(1.0, max(0.0, (rms_db - QUIET_DB) / (LOUD_DB - QUIET_DB)))


class TrackEnvelope:
    """The loudness heard at each stretch of one track; stretches never heard stay None.

    Each time a track starts playing the picture starts afresh. Seeking back
    within one play keeps the louder reading, so the picture only fills in.
    """

    def __init__(self, buckets: int = ENVELOPE_BUCKETS) -> None:
        self.video_id: str | None = None
        self.levels: list[float | None] = [None] * buckets

    def start(self, video_id: str | None) -> None:
        """Forget what was heard and follow ``video_id`` (None: nothing plays)."""
        self.video_id = video_id
        self.levels = [None] * len(self.levels)

    def record(self, video_id: str, fraction: float, level: float) -> None:
        """Note ``level`` heard at ``fraction`` (0..1) of track ``video_id``."""
        if video_id != self.video_id:
            self.start(video_id)
        index = min(len(self.levels) - 1, max(0, int(fraction * len(self.levels))))
        heard = self.levels[index]
        self.levels[index] = level if heard is None else max(heard, level)


class SeekBar(Widget):
    """Progress drawn as the loudness each stretch had when it played; click to seek."""

    COMPONENT_CLASSES = {"seek-bar--played", "seek-bar--head", "seek-bar--rest"}
    DEFAULT_CSS = """
    SeekBar { height: 1; }
    SeekBar > .seek-bar--played { color: $accent; }
    SeekBar > .seek-bar--head { color: $foreground; }
    SeekBar > .seek-bar--rest { color: $foreground 30%; }
    """

    class Seek(Message):
        """The user clicked the bar: seek to ``fraction`` (0..1) of the track."""

        def __init__(self, fraction: float) -> None:
            super().__init__()
            self.fraction = fraction

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._fraction: float | None = None
        self._levels: Sequence[float | None] = ()

    def show(self, fraction: float | None, levels: Sequence[float | None]) -> None:
        """Put the playhead at ``fraction`` over ``levels``, loudness in track order.

        Args:
            fraction: How far the track has played, 0..1; None when nothing plays.
            levels: Loudness per stretch of the track, None where nothing was heard.
        """
        self._fraction = fraction
        self._levels = levels
        self.refresh()

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if y > 0 or width == 0:
            return Strip.blank(width, self.rich_style)
        head = -1 if self._fraction is None else min(width - 1, int(self._fraction * width))
        cells = [
            (_glyph(level), _part(column, head))
            for column, level in enumerate(_resample(self._levels, width))
        ]
        styles = {
            part: self.rich_style + self.get_component_rich_style(f"seek-bar--{part}")
            for part in ("played", "head", "rest")
        }
        segments = [
            Segment("".join(glyph for glyph, _ in run), styles[part])
            for part, run in groupby(cells, key=lambda cell: cell[1])
        ]
        return Strip(segments, width)

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        width = self.size.width
        if offset is not None and width > 1:
            self.post_message(self.Seek(min(1.0, offset.x / (width - 1))))


class VolumeMeter(Static):
    """The volume as a wedge of rising bars; a click mutes, the wheel turns it."""

    def show(self, volume: float | None, *, muted: bool) -> None:
        """Draw ``volume`` in percent; None keeps the last known level on screen."""
        if volume is not None:
            self.update(volume_text(volume, muted=muted))

    async def on_click(self, event: events.Click) -> None:
        await self.app.run_action("mute")

    async def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        await self.app.run_action("volume_up")

    async def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        await self.app.run_action("volume_down")


def track_text(candidate: SongCandidate) -> Content:
    """Title in bold, then the artists, then album and year dimmed."""
    album = " ".join(part for part in (candidate.album, candidate.year) if part)
    return Content.assemble(
        (candidate.title, "bold"),
        ("  " + candidate.artist_text) if candidate.artist_text else "",
        ("  " + album, "dim") if album else "",
    )


def crossfader_text(status: PlaybackStatus) -> Content:
    """``A ━━━━●━━━━ B  8s``: the knob rests on the live deck and slides during a blend."""
    knob = round(_knob_position(status) * (RAIL_CELLS - 1))
    is_cut = status.transition_style == "cut"
    rail = "┄" if is_cut else "━"
    on_deck_a = knob <= (RAIL_CELLS - 1) / 2
    live, idle = "bold $accent", "dim"
    return Content.assemble(
        ("A ", live if on_deck_a else idle),
        (rail * knob, "dim"),
        ("●", live),
        (rail * (RAIL_CELLS - 1 - knob), "dim"),
        (" B", idle if on_deck_a else live),
        ("  cut" if is_cut else f"  {status.fade_seconds:g}s", "dim"),
    )


def volume_text(volume: float, *, muted: bool) -> Content:
    """``▁▂▃▄▅▆▇█ 80%``: bars lit up to the volume; dark and "mute" while muted."""
    percent = round(volume)
    lit = 0 if muted else round(min(100, max(0, percent)) / 100 * len(LEVEL_GLYPHS))
    label = "mute" if muted else f"{percent}%"
    return Content.assemble(
        (LEVEL_GLYPHS[:lit], "$accent"),
        (LEVEL_GLYPHS[lit:], "dim"),
        (f" {label:>4}", "dim"),
    )


def _knob_position(status: PlaybackStatus) -> float:
    """0 on deck A, 1 on deck B. During a blend ``active_deck`` is the incoming deck."""
    toward_b = status.active_deck == "B"
    if status.mix_progress is None:
        return 1.0 if toward_b else 0.0
    return status.mix_progress if toward_b else 1.0 - status.mix_progress


def _resample(levels: Sequence[float | None], width: int) -> list[float | None]:
    """One level per column: the loudest heard level in that column's share."""
    count = len(levels)
    if count == 0:
        return [None] * width
    columns: list[float | None] = []
    for column in range(width):
        start = column * count // width
        stop = max(start + 1, (column + 1) * count // width)
        heard = [level for level in levels[start:stop] if level is not None]
        columns.append(max(heard) if heard else None)
    return columns


def _glyph(level: float | None) -> str:
    if level is None:
        return BASELINE
    return LEVEL_GLYPHS[round(min(1.0, max(0.0, level)) * (len(LEVEL_GLYPHS) - 1))]


def _part(column: int, head: int) -> str:
    if column < head:
        return "played"
    return "head" if column == head else "rest"
