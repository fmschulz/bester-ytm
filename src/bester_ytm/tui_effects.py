"""Visualizer rendering and playback status widgets for the TUI."""

from __future__ import annotations

from textual.widgets import Button, Input, Label, ListItem, ListView, ProgressBar, Static

from .playback import PlaybackError, PlaybackStatus
from .playlist_plan import SongCandidate
from .stores import MAX_RATING, TrackMetadataStore
from .tui_visuals import AudioLevelMeter, render_visual_panel

METER_SLOTS = 12
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


def mix_meter(progress: float) -> str:
    filled = int(METER_SLOTS * min(1.0, max(0.0, progress)))
    return "[" + "#" * filled + "-" * (METER_SLOTS - filled) + "]"


def style_label(status) -> str:
    if status.transition_style == "cut":
        return "cut"
    return f"xfade {status.fade_seconds:g}s"


def render_deck_status(status) -> str:
    """The one-line deck/crossfade readout under the transport (the audio-reactive
    panels carry the motion now; this just reports which deck is live and how it mixes)."""
    label = style_label(status)
    state = "playing" if status.running and not status.paused else (
        "paused" if status.running else "idle"
    )
    if status.mix_progress is None:
        return f"DECK {status.active_deck}  {label}  ({state})"
    outgoing = "B" if status.active_deck == "A" else "A"
    return f"MIX  {outgoing} {mix_meter(status.mix_progress)} {status.active_deck}  {label}"


class PlaybackRenderer:
    """Mixin that reflects playback and queue state into the mounted widgets."""

    was_mixing: bool
    auto_advance_pending: bool
    playback_was_active: bool
    visualizer_effect: str
    visual_phase: float
    audio_levels: list[float]
    last_playback_status: PlaybackStatus | None
    current_candidate: SongCandidate | None
    audio_meter: AudioLevelMeter
    _last_visual_state: str | None
    _rendered_now_playing_id: str | None
    _synced_current_video_id: str | None
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
        # Resync only on an actual track change; a per-tick resync would stomp
        # the Track Details pane and any text being typed into #tags-input.
        if status.current_video_id and status.current_video_id != self._synced_current_video_id:
            self._sync_current_track(status.current_video_id)
        self._refresh_now_playing_marker(status.current_video_id)
        self._update_transport_widgets(status)

    def _refresh_now_playing_marker(self, current_video_id: str | None) -> None:
        """Re-render the queue only when the playing track changed (no per-tick flicker)."""
        if current_video_id == self._rendered_now_playing_id:
            return
        self.run_worker(self._render_queue(), exclusive=True, group="queue-render")

    def _track_display_name(self, video_id: str | None) -> str | None:
        """The human-readable name of a known track, or None when unresolvable."""
        if not video_id:
            return None
        candidate = self.candidates_by_video_id.get(video_id)
        return candidate.display_name if candidate else None

    def _announce_transition(self, status) -> None:
        is_mixing = status.mix_progress is not None
        if is_mixing and not self.was_mixing:
            name = self._track_display_name(status.current_video_id)
            self._set_status(f"Mixing into {name}." if name else "Mixing into the next track.")
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
        visualizer.update(render_deck_status(status))

    def _animate_visual_panel(self) -> None:
        """Fast animation tick for the audio-reactive panels in every pane, fed by live loudness."""
        status = getattr(self, "last_playback_status", None)
        running = bool(status and status.running)
        paused = bool(status and status.running and status.paused)
        # When idle or paused the frame is frozen; redraw it once on entry, then skip the
        # per-tick re-render of every pane until playback actually moves again.
        static_state = None if (running and not paused) else ("idle" if not running else "paused")
        if static_state is not None and static_state == self._last_visual_state:
            return
        self._last_visual_state = static_state
        if running and not paused:
            self._advance_audio_visual()
        effect = getattr(self, "visualizer_effect", "mythos")
        for selector in ("#left-visual", "#big-visual", "#right-visual"):
            widget = self._query_optional(selector, Static)
            if widget is None:
                continue
            self._toggle_widget_class(widget, "idle-effect", not running)
            self._toggle_widget_class(widget, "paused-effect", paused)
            size = getattr(widget, "size", None)
            if size is None or size.width <= 0 or size.height <= 0:
                continue
            widget.update(
                render_visual_panel(
                    effect,
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
        # Drift rates are per second so the on-screen speed is the same at any fps;
        # the onset kick is per beat and stays unscaled.
        dt = self.audio_meter.sample_interval
        self.visual_phase += (1.6 + 11.2 * level) * dt + 3.0 * onset

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
        self._synced_current_video_id = video_id
        if not video_id:
            self.current_candidate = None
            self._update_track_label("No track playing.")
            self._update_track_metadata(None)
            return
        candidate = self.candidates_by_video_id.get(video_id)
        self.current_candidate = candidate
        label = candidate.display_name if candidate else video_id
        self._update_track_label(label)
        # Track Details edits the highlighted queue row (r / Save Tags act on
        # it), so keep showing that row; fall back to the playing track only
        # when no row is highlighted.
        self._update_track_metadata(self._highlighted_queue_video_id() or video_id)

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
        # Never clobber text the user is typing into the tags field.
        if tags_input and getattr(tags_input, "has_focus", False):
            sync_tags_input = False
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
