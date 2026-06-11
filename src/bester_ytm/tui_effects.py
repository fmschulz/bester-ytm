"""Visualizer rendering and playback status widgets for the TUI."""

from __future__ import annotations

from collections.abc import Callable

from textual.widgets import Button, Input, Label, ListItem, ListView, ProgressBar, Static

from .playback import PlaybackError, PlaybackStatus
from .stores import MAX_RATING, TrackMetadataStore
from .tui_visuals import AudioLevelMeter, render_visual_panel

METER_SLOTS = 12
EFFECT_WIDTH = 18
MAX_LEVEL_HISTORY = 256


def format_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "0:00"
    whole = int(seconds)
    minutes, secs = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def effect_meter(position: float | None, duration: float | None) -> str:
    if not duration or duration <= 0:
        filled = 0
    else:
        filled = int(METER_SLOTS * min(1.0, max(0.0, (position or 0.0) / duration)))
    return "[" + "#" * filled + "-" * (METER_SLOTS - filled) + "]"


def effect_bars(frame: int) -> str:
    pattern = [1, 3, 2, 4, 2, 3]
    bars = []
    for index in range(3):
        value = pattern[(frame + index * 2) % len(pattern)]
        bars.append("[" + "#" * value + "-" * (4 - value) + "]")
    return " ".join(bars)


def effect_wave(frame: int) -> str:
    pattern = "_.-~^~-._"
    return "".join(pattern[(frame + col) % len(pattern)] for col in range(EFFECT_WIDTH))


def effect_pulse(frame: int) -> str:
    widths = [2, 6, 10, 14, 16, 14, 10, 6]
    span = widths[frame % len(widths)]
    pad = (EFFECT_WIDTH - 2 - span) // 2
    tail = EFFECT_WIDTH - 2 - span - pad
    return "[" + " " * pad + "=" * span + " " * tail + "]"


def effect_scope(frame: int) -> str:
    levels = " .:!|!:."
    return "".join(
        levels[(frame * 3 + col * col) % len(levels)] for col in range(EFFECT_WIDTH)
    )


def effect_mythos(frame: int) -> str:
    glyphs = "·∙●∙· "
    return "".join(
        glyphs[(frame + col * 3) % len(glyphs)] for col in range(EFFECT_WIDTH)
    )


VISUALIZER_EFFECTS: dict[str, Callable[[int], str]] = {
    "mythos": effect_mythos,
    "bars": effect_bars,
    "wave": effect_wave,
    "pulse": effect_pulse,
    "scope": effect_scope,
}


def mix_meter(progress: float) -> str:
    filled = int(METER_SLOTS * min(1.0, max(0.0, progress)))
    return "[" + "#" * filled + "-" * (METER_SLOTS - filled) + "]"


def style_label(status) -> str:
    if status.transition_style == "cut":
        return "cut"
    return f"xfade {status.fade_seconds:g}s"


def deck_line(status) -> str:
    label = style_label(status)
    if status.mix_progress is None:
        return f"DECK  {status.active_deck}  {label}"
    outgoing = "B" if status.active_deck == "A" else "A"
    return f"MIX   {outgoing} {mix_meter(status.mix_progress)} {status.active_deck}  {label}"


def render_visualizer(status, frame: int, effect: str = "bars") -> str:
    animate = VISUALIZER_EFFECTS.get(effect, effect_bars)
    if status.running and not status.paused:
        spinner = "-\\|/"[frame % 4]
        lines = [
            f"PLAY  {spinner} signal live",
            f"EQ    {animate(frame)}",
            f"SEEK  {effect_meter(status.position_seconds, status.duration_seconds)}",
        ]
    elif status.running:
        lines = [
            "PAUSED signal held",
            "EQ    [##--] [##--] [##--]",
            f"SEEK  {effect_meter(status.position_seconds, status.duration_seconds)}",
        ]
    else:
        lines = [
            "IDLE  no signal",
            "EQ    [----] [----] [----]",
            "SEEK  [------------]",
        ]
    lines.append(deck_line(status))
    return "\n".join(lines)


class PlaybackRenderer:
    """Mixin that reflects playback and queue state into the mounted widgets."""

    was_mixing: bool
    auto_advance_pending: bool
    playback_was_active: bool
    effect_frame: int
    visualizer_effect: str
    visual_phase: float
    audio_levels: list[float]
    last_playback_status: PlaybackStatus | None
    audio_meter: AudioLevelMeter
    _rendered_now_playing_id: str | None
    selected_queue_video_id: str | None
    _queue_render_active: bool
    _queue_render_pending: bool
    _queue_render_focus: str | None

    def _refresh_playback(self, status=None) -> None:
        try:
            status = status or self.playback.status()
        except PlaybackError:
            return
        self.last_playback_status = status
        self._update_playback_effects(status)
        self._announce_transition(status)
        if self._handle_auto_advance(status):
            return
        if status.current_video_id:
            self._sync_current_track(status.current_video_id)
        self._refresh_now_playing_marker(status.current_video_id)
        self._update_transport_widgets(status)

    def _refresh_now_playing_marker(self, current_video_id: str | None) -> None:
        """Re-render the queue only when the playing track changed (no per-tick flicker)."""
        if current_video_id == self._rendered_now_playing_id:
            return
        self.run_worker(self._render_queue(), exclusive=True, group="queue-render")

    def _announce_transition(self, status) -> None:
        is_mixing = status.mix_progress is not None
        if is_mixing and not self.was_mixing:
            self._set_status(f"Mixing into {status.current_video_id}.")
        self.was_mixing = is_mixing
        if status.transition_error:
            self._set_status(f"Mix failed; using cut: {status.transition_error}")
            # This is the only display site; retire the one-shot message here.
            self.playback.consume_transition_error()

    def _handle_auto_advance(self, status) -> bool:
        if status.running:
            self.playback_was_active = True
            return False
        if (
            self.playback_was_active
            and self.playback.queue
            and not self.auto_advance_pending
        ):
            self.auto_advance_pending = True
            self.run_worker(
                self._auto_advance(),
                name="auto-advance",
                group="playback",
                exclusive=True,
            )
            return True
        if self.playback_was_active and not self.playback.queue:
            self.playback_was_active = False
            self._sync_current_track(None)
            self._set_status("Queue finished.")
        return False

    def _update_transport_widgets(self, status) -> None:
        duration = status.duration_seconds or 1
        position = min(status.position_seconds or 0, duration)
        progress = self._query_optional("#progress", ProgressBar)
        if progress:
            progress.update(total=duration, progress=position)

        progress_time = self._query_optional("#progress-time", Static)
        if progress_time:
            state = "paused" if status.paused else "playing" if status.running else "stopped"
            progress_time.update(
                f"{format_time(position)} / {format_time(status.duration_seconds)}  {state}"
            )

        volume = self._query_optional("#volume-status", Static)
        if volume:
            if status.volume is None:
                volume.update("Vol --")
            else:
                muted = " muted" if status.muted else ""
                volume.update(f"Vol {int(status.volume)}%{muted}")

        play_button = self._query_optional("#play-button", Button)
        if play_button:
            play_button.label = "Resume" if status.paused else "Pause" if status.running else "Play"

        mute_button = self._query_optional("#mute-button", Button)
        if mute_button:
            mute_button.label = "Unmute" if status.muted else "Mute"

    def _update_playback_effects(self, status) -> None:
        visualizer = self._query_optional("#visualizer", Static)
        panel = self._query_optional("#right")
        playing = bool(status.running and not status.paused)
        paused = bool(status.running and status.paused)
        idle = not status.running

        self._toggle_widget_class(panel, "playing-effect", playing)
        self._toggle_widget_class(panel, "paused-effect", paused)
        self._toggle_widget_class(visualizer, "idle-effect", idle)
        self._toggle_widget_class(visualizer, "paused-effect", paused)

        if visualizer is None:
            return
        if playing:
            self.effect_frame = (self.effect_frame + 1) % 64
        effect = getattr(self, "visualizer_effect", "bars")
        visualizer.update(render_visualizer(status, self.effect_frame, effect))

    def _animate_visual_panel(self) -> None:
        """Fast animation tick for the large center-pane visual, fed by live loudness."""
        widget = self._query_optional("#big-visual", Static)
        if widget is None:
            return
        status = getattr(self, "last_playback_status", None)
        running = bool(status and status.running)
        paused = bool(status and status.running and status.paused)
        self._toggle_widget_class(widget, "idle-effect", not running)
        self._toggle_widget_class(widget, "paused-effect", paused)
        if running and not paused:
            self._advance_audio_visual()
        size = getattr(widget, "size", None)
        if size is None or size.width <= 0 or size.height <= 0:
            return
        widget.update(
            render_visual_panel(
                getattr(self, "visualizer_effect", "mythos"),
                self.visual_phase,
                size.width,
                size.height,
                running=running,
                levels=self.audio_levels,
            )
        )

    def _advance_audio_visual(self) -> None:
        """Sample live loudness, push it onto the history, and advance the audio-driven phase."""
        read_level = getattr(self.playback, "read_audio_level_db", None)
        if read_level is not None:
            self.audio_meter.update(read_level())
        level = self.audio_meter.level
        previous = self.audio_levels[-1] if self.audio_levels else level
        onset = max(0.0, level - previous)
        self.audio_levels.append(level)
        if len(self.audio_levels) > MAX_LEVEL_HISTORY:
            del self.audio_levels[:-MAX_LEVEL_HISTORY]
        # Near-still in lulls, flowing when loud, with an extra kick on each loudness
        # onset so the motion locks to the beat instead of drifting at a constant rate.
        self.visual_phase += 0.2 + 1.4 * level + 3.0 * onset

    def _toggle_widget_class(self, widget, class_name: str, enabled: bool) -> None:
        if widget is None:
            return
        if enabled:
            add_class = getattr(widget, "add_class", None)
            if callable(add_class):
                add_class(class_name)
            return
        remove_class = getattr(widget, "remove_class", None)
        if callable(remove_class):
            remove_class(class_name)

    def _sync_current_track(self, video_id: str | None) -> None:
        if not video_id:
            self.current_candidate = None
            self._update_track_label("No track playing.")
            self._update_track_metadata(None)
            return
        candidate = self.candidates_by_video_id.get(video_id)
        self.current_candidate = candidate
        label = candidate.display_name if candidate else video_id
        self._update_track_label(label)
        self._update_track_metadata(video_id)

    def _update_track_label(self, label: str) -> None:
        track = self._query_optional("#track", Static)
        if track:
            track.update(label)

    def _update_queue_title(self, count: int) -> None:
        title = self._query_optional("#queue-title", Label)
        if title:
            title.update(f"{self.playlist_title} ({count})")

    def _update_track_metadata(
        self,
        video_id: str | None,
        *,
        sync_tags_input: bool = True,
    ) -> None:
        output = self._query_optional("#track-metadata", Static)
        tags_input = self._query_optional("#tags-input", Input)
        if not video_id:
            if output:
                output.update("Rating --  Tags --")
            if tags_input and sync_tags_input:
                tags_input.value = ""
            return
        metadata = TrackMetadataStore().get(video_id)
        tags = ", ".join(metadata.tags) if metadata.tags else "--"
        if output:
            output.update(f"Rating {metadata.rating}/{MAX_RATING}  Tags {tags}")
        if tags_input and sync_tags_input:
            tags_input.value = ", ".join(metadata.tags)

    async def _render_queue(self, focus_video_id: str | None = None) -> None:
        """Serialize rebuilds so a direct render and a tick render cannot interleave into dupes."""
        self._queue_render_focus = focus_video_id
        self._queue_render_pending = True
        if self._queue_render_active:
            return
        self._queue_render_active = True
        try:
            while self._queue_render_pending:
                self._queue_render_pending = False
                await self._draw_queue(self._queue_render_focus)
        finally:
            self._queue_render_active = False

    async def _draw_queue(self, focus_video_id: str | None) -> None:
        queue = self.query_one("#queue", ListView)
        held_cursor_id = getattr(getattr(queue, "highlighted_child", None), "video_id", None)
        try:
            current = self.playback.status().current_video_id
        except AttributeError:
            current = getattr(self.playback, "current_video_id", None)
        # Set before the first await so a tick firing mid-rebuild sees no change and skips a render.
        self._rendered_now_playing_id = current
        await queue.clear()
        video_ids = self.playlist_video_ids or self.playback.queue
        self._update_queue_title(len(video_ids))
        for index, video_id in enumerate(video_ids, start=1):
            candidate = self.candidates_by_video_id.get(video_id)
            label = candidate.display_name if candidate else video_id
            prefix = "NOW" if video_id == current else f"{index:02d}"
            item = ListItem(Label(f"{prefix}  {label}"))
            if video_id == current:
                item.add_class("playing")
            item.video_id = video_id  # type: ignore[attr-defined]
            await queue.append(item)
        cursor_id: str | None = focus_video_id
        if cursor_id is None:
            cursor_id = held_cursor_id or self.selected_queue_video_id
        self._set_queue_cursor(queue, list(video_ids), cursor_id)

    def _set_queue_cursor(self, queue, video_ids: list[str], target_id: str | None) -> None:
        """Keep the selection cursor on the user's row across a rebuild, not the now-playing row."""
        if target_id is None or target_id not in video_ids:
            return
        queue.index = video_ids.index(target_id)
