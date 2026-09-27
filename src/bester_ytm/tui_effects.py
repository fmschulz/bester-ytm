"""Reflect playback into the stage, the player deck, and the queue."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Literal

from textual.content import Content
from textual.widgets import Button, ListView, Static

from .playback import PlaybackError, PlaybackStatus
from .playlist_plan import SongCandidate
from .tui_player import (
    ENVELOPE_BUCKETS,
    FAVORITE_GLYPH,
    NOT_FAVORITE_GLYPH,
    PAUSE_GLYPH,
    PLAY_GLYPH,
    SeekBar,
    TrackEnvelope,
    VolumeMeter,
    crossfader_text,
    format_time,
    loudness,
    track_text,
)
from .tui_rows import QueueRow, queue_heading
from .tui_stage import Stage
from .tui_visuals import AudioSignal

NO_TRACK = "No track playing."

StageState = Literal["live", "paused", "idle"]


class PlaybackRenderer:
    """Mixin that reflects playback and queue state into the mounted widgets."""

    was_mixing: bool
    auto_advance_pending: bool
    playback_was_active: bool
    visualizer_effect: str
    signal: AudioSignal
    envelope: TrackEnvelope
    last_playback_status: PlaybackStatus | None
    current_candidate: SongCandidate | None
    _status_clock: float
    _playback_instance: tuple[str | None, int | None]
    _stage_state: StageState | None
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
        self._status_clock = time.monotonic()
        self._follow_playback_instance(status)
        self._announce_transition(status)
        if self._handle_auto_advance(status):
            return
        # Resync only on an actual track change; a per-tick resync would
        # redraw the Now Playing label and queue for no reason.
        if status.current_video_id and status.current_video_id != self._synced_current_video_id:
            self._sync_current_track(status.current_video_id)
        self._maybe_poll_radio(status)
        self._refresh_now_playing_marker(status.current_video_id)
        self._update_transport_widgets(status)
        if self.visual_fps == 0:
            self._animate_visual_panel()

    def _follow_playback_instance(self, status: PlaybackStatus) -> None:
        """Start a fresh seek bar picture whenever a track starts playing.

        Every start and crossfade runs a new mpv process, so the (track, process)
        pair changes even when the same song follows itself; a stop clears both.
        """
        instance = (status.current_video_id, status.process_id)
        if instance != self._playback_instance:
            self._playback_instance = instance
            self.envelope.start(status.current_video_id)

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

    def _update_transport_widgets(self, status: PlaybackStatus) -> None:
        position = self._position_seconds(status)
        elapsed = self._query_optional("#progress-time", Static)
        if elapsed is not None:
            elapsed.update(format_time(position))
        total = self._query_optional("#duration-time", Static)
        if total is not None:
            total.update(self._duration_label(status))
        self._update_seek_bar(status, position)
        play_button = self._query_optional("#play-button", Button)
        if play_button is not None:
            is_playing = status.running and not status.paused
            play_button.label = PAUSE_GLYPH if is_playing else PLAY_GLYPH
        crossfader = self._query_optional("#crossfader", Static)
        if crossfader is not None:
            crossfader.update(crossfader_text(status))
        volume = self._query_optional("#volume", VolumeMeter)
        if volume is not None:
            volume.show(status.volume, muted=status.muted)

    def _update_seek_bar(self, status: PlaybackStatus, position: float) -> None:
        seek_bar = self._query_optional("#progress", SeekBar)
        if seek_bar is None:
            return
        if not status.running:
            seek_bar.show(None, ())
        elif status.duration_seconds:
            heard = self.envelope.video_id == status.current_video_id
            seek_bar.show(position / status.duration_seconds, self.envelope.levels if heard else ())
        else:  # a stream has no end: show its recent loudness instead
            seek_bar.show(1.0, list(self.signal.history)[-ENVELOPE_BUCKETS:])

    def _position_seconds(self, status: PlaybackStatus) -> float:
        """The last reported position plus the time played since that report."""
        position = status.position_seconds or 0.0
        if status.running and not status.paused:
            position += time.monotonic() - self._status_clock
        if status.duration_seconds:
            position = min(position, status.duration_seconds)
        return position

    @staticmethod
    def _duration_label(status: PlaybackStatus) -> str:
        if status.duration_seconds:
            return format_time(status.duration_seconds)
        return "live" if status.running else "0:00"

    def _animate_visual_panel(self) -> None:
        """Sample and draw the stage while music plays; draw once per state change."""
        state = self._playback_state()
        if state == "live" and self.visual_fps > 0:
            rms_db = self._read_audio_level()
            self.signal.sample(rms_db)
            self._record_envelope(rms_db)
        elif state == self._stage_state:
            return  # paused or idle: the last frame stays on screen
        self._stage_state = state
        self._draw_stage(state)

    def _record_envelope(self, rms_db: float | None) -> None:
        """Note the loudness just heard at the playhead and redraw the seek bar."""
        status = self.last_playback_status
        if status is None:
            return
        position = self._position_seconds(status)
        if rms_db is not None and status.current_video_id and status.duration_seconds:
            fraction = position / status.duration_seconds
            self.envelope.record(status.current_video_id, fraction, loudness(rms_db))
        self._update_seek_bar(status, position)

    def _draw_stage(self, state: StageState) -> None:
        stage = self._query_optional("#big-visual", Stage)
        if stage is None:
            return
        stage.set_class(state == "paused", "paused-effect")
        stage.set_class(state == "idle", "idle-effect")
        frame = self.signal.still() if state == "idle" else self.signal.frame()
        stage.show(self.visualizer_effect, frame)

    def _playback_state(self) -> StageState:
        status = self.last_playback_status
        if status is None or not status.running:
            return "idle"
        return "paused" if status.paused else "live"

    def _read_audio_level(self) -> float | None:
        # Test doubles of the playback controller may not measure loudness.
        read = getattr(self.playback, "read_audio_level_db", None)
        return read() if read is not None else None

    def _sync_current_track(self, video_id: str | None) -> None:
        self._synced_current_video_id = video_id
        candidate = self.candidates_by_video_id.get(video_id) if video_id else None
        self.current_candidate = candidate
        if not video_id:
            self._update_track_label(NO_TRACK)
            self._show_playing_favorite(False)
            return
        self._update_track_label(track_text(candidate) if candidate else video_id)
        self._show_playing_favorite(video_id in self._favorite_video_ids())

    def _update_track_label(self, label: str | Content) -> None:
        track = self._query_optional("#track", Static)
        if track:
            track.update(label)

    def _show_playing_favorite(self, is_favorite: bool) -> None:
        """Fill the player's star when the playing song is a favorite."""
        button = self._query_optional("#favorite-playing-button", Button)
        if button is None:
            return
        button.label = FAVORITE_GLYPH if is_favorite else NOT_FAVORITE_GLYPH
        button.set_class(is_favorite, "is-favorite")

    def _update_queue_title(self, video_ids: Sequence[str]) -> None:
        """Name, size and running time in the queue's border; an empty queue says so."""
        candidates = [self.candidates_by_video_id.get(video_id) for video_id in video_ids]
        seconds = sum(candidate.duration_seconds or 0 for candidate in candidates if candidate)
        pane = self._query_optional("#center")
        if pane is not None:
            pane.border_title = queue_heading(self.playlist_title, len(video_ids), seconds)
        empty = self._query_optional("#queue-empty")
        if empty is not None:
            empty.display = not video_ids

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
        video_ids = list(self.playlist_video_ids or self.playback.queue)
        self._update_queue_title(video_ids)
        favorite_ids = self._favorite_video_ids()
        playing_index = video_ids.index(current) if current in video_ids else 0
        for position, video_id in enumerate(video_ids, start=1):
            row = QueueRow(
                video_id,
                position,
                self.candidates_by_video_id.get(video_id),
                is_playing=video_id == current,
                is_played=position <= playing_index,
                is_favorite=video_id in favorite_ids,
            )
            await queue.append(row)
        cursor_id: str | None = focus_video_id
        if cursor_id is None:
            cursor_id = held_cursor_id or self.selected_queue_video_id
        self._set_queue_cursor(queue, list(video_ids), cursor_id)

    def _set_queue_cursor(self, queue, video_ids: list[str], target_id: str | None) -> None:
        """Keep the selection cursor on the user's row across a rebuild, not the now-playing row."""
        if target_id is None or target_id not in video_ids:
            return
        queue.index = video_ids.index(target_id)
