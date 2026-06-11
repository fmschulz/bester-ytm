"""Transport and playback actions for the TUI."""

from __future__ import annotations

from textual.widgets import ListView

from .config import ConfigError, save_transition_settings
from .playback import PlaybackError, PlaybackStatus
from .transitions import TransitionSettings, TransitionStyle
from .tui_effects import format_time


class PlaybackActions:
    """Mixin with play/pause/seek/volume and DJ transition actions for BesterYTMApp."""

    playlist_video_ids: list[str]

    async def action_play_selected(self) -> None:
        try:
            focused = self.focused
        except Exception:
            focused = None
        if getattr(focused, "id", None) == "queue":
            item = getattr(focused, "highlighted_child", None)
            await self._play_queue_item(item)
            return

        if await self._queue_selected_results():
            return

        results = self.query_one("#results", ListView)
        item = results.highlighted_child
        search_item = getattr(item, "search_item", None) if item else None
        if search_item:
            loaded = await self._load_search_item(search_item)
            if loaded:
                return

        playlist_id = getattr(item, "playlist_id", None) if item else None
        if playlist_id:
            await self._load_playlist_queue(str(playlist_id))
            return

        candidate = getattr(item, "candidate", None) if item else None
        if candidate is None:
            return
        self.candidates_by_video_id[candidate.video_id] = candidate
        try:
            if self.playback.status().running:
                self.playback.enqueue([candidate.video_id])
                self.playlist_video_ids.append(candidate.video_id)
                await self._render_queue()
                self._set_status(f"Queued {candidate.video_id}.")
                return
            self.playback.replace_queue([candidate.video_id])
            self.playlist_video_ids = [candidate.video_id]
            self.playlist_title = "Queue"
            status = self.playback.play_queue()
            self.playback_was_active = True
        except PlaybackError as exc:
            await self._report_playback_error(exc)
            return
        self.current_candidate = candidate
        self._update_track_label(candidate.display_name)
        await self._render_queue()
        self._refresh_playback(status)
        self._set_status(f"Playing {candidate.video_id}.")

    async def action_pause_resume(self) -> None:
        status = self.playback.status()
        if not status.running:
            results = self.query_one("#results", ListView)
            item = results.highlighted_child
            playlist_id = getattr(item, "playlist_id", None) if item else None
            if playlist_id and not self.playback.queue:
                loaded = await self._load_playlist_queue(str(playlist_id))
                if not loaded:
                    return
            if self.playback.queue:
                try:
                    status = self.playback.play_queue()
                    self.playback_was_active = True
                except PlaybackError as exc:
                    await self._report_playback_error(exc)
                    return
                await self._show_playback_status(
                    status, f"Playing {status.current_video_id or 'none'}."
                )
                return
            self._set_status("Nothing to play.")
            return

        status = self.playback.pause_resume()
        self._refresh_playback(status)
        self._set_status("Paused." if status.paused else "Playing.")

    async def action_next_track(self) -> None:
        try:
            status = self.playback.next()
            self.playback_was_active = status.running
        except PlaybackError as exc:
            await self._report_playback_error(exc)
            return
        await self._show_playback_status(status, f"Next: {status.current_video_id or 'none'}.")

    async def action_previous_track(self) -> None:
        try:
            status = self.playback.previous()
            self.playback_was_active = status.running
        except PlaybackError as exc:
            await self._report_playback_error(exc)
            return
        await self._show_playback_status(
            status, f"Previous: {status.current_video_id or 'none'}."
        )

    async def _play_queue_item(self, item) -> None:
        video_id = getattr(item, "video_id", None) if item else None
        if not video_id:
            return

        current = self.playback.status().current_video_id
        if video_id == current:
            self._set_status(f"Already playing {video_id}.")
            return

        video_ids = list(self.playlist_video_ids or self.playback.queue)
        try:
            start = video_ids.index(video_id)
        except ValueError:
            video_ids = [video_id]
            start = 0

        try:
            self.playback.replace_queue(video_ids[start:])
            status = self.playback.play_queue()
            self.playback_was_active = True
        except PlaybackError as exc:
            await self._report_playback_error(exc)
            return

        await self._show_playback_status(status, f"Playing {status.current_video_id or 'none'}.")

    async def _auto_advance(self) -> None:
        try:
            await self._advance_to_next_playable()
        finally:
            # The flag must reset even if a widget update blows up, or
            # auto-advance would be disabled for the rest of the session.
            self.auto_advance_pending = False

    async def _advance_to_next_playable(self) -> None:
        last_error: PlaybackError | None = None
        for _ in range(len(self.playback.queue) + 1):
            try:
                status = self.playback.next()
            except PlaybackError as exc:
                last_error = exc
                if not self.playback.queue:
                    break
                skipped = self.playback.queue.pop(0)
                self._set_status(f"Skipping unplayable track {skipped}: {exc}")
                continue
            self.playback_was_active = status.running
            await self._show_playback_status(
                status, f"Auto next: {status.current_video_id or 'none'}."
            )
            return
        self.playback_was_active = False
        if last_error is not None:
            await self._report_playback_error(last_error)

    async def _report_playback_error(self, exc: PlaybackError) -> None:
        self._sync_current_track(self.playback.status().current_video_id)
        await self._render_queue()
        self._set_status(str(exc))

    async def _show_playback_status(self, status: PlaybackStatus, message: str) -> None:
        self._sync_current_track(status.current_video_id)
        await self._render_queue()
        self._refresh_playback(status)
        self._set_status(message)

    def action_seek_backward(self) -> None:
        self._seek_relative(-10)

    def action_seek_forward(self) -> None:
        self._seek_relative(10)

    def action_seek_large_backward(self) -> None:
        self._seek_relative(-30)

    def action_seek_large_forward(self) -> None:
        self._seek_relative(30)

    def action_volume_down(self) -> None:
        self._change_volume(-5)

    def action_volume_up(self) -> None:
        self._change_volume(5)

    def action_mute(self) -> None:
        try:
            status = self.playback.toggle_mute()
        except PlaybackError as exc:
            self._set_status(str(exc))
            return
        self._refresh_playback(status)
        self._set_status("Muted." if status.muted else "Unmuted.")

    def _seek_relative(self, seconds: float) -> None:
        try:
            status = self.playback.seek_relative(seconds)
        except PlaybackError as exc:
            self._set_status(str(exc))
            return
        self._refresh_playback(status)
        direction = "forward" if seconds > 0 else "back"
        self._set_status(f"Seeked {direction} {abs(int(seconds))}s.")

    def _seek_absolute(self, seconds: float) -> None:
        try:
            status = self.playback.seek_absolute(seconds)
        except PlaybackError as exc:
            self._set_status(str(exc))
            return
        self._refresh_playback(status)
        self._set_status(f"Seeked to {format_time(seconds)}.")

    def _change_volume(self, delta: float) -> None:
        try:
            status = self.playback.change_volume(delta)
        except PlaybackError as exc:
            self._set_status(str(exc))
            return
        self._refresh_playback(status)
        if status.volume is not None:
            self._set_status(f"Volume {int(status.volume)}%.")

    def action_cycle_transition(self) -> None:
        settings = self.playback.cycle_transition_style()
        self.transition_settings = settings
        suffix = self._persist_transition(settings)
        if settings.style is TransitionStyle.CUT:
            self._set_status(f"Transition: cut.{suffix}")
            return
        self._set_status(
            f"Transition: crossfade {settings.fade_seconds:g}s ([ / ] adjust fade).{suffix}"
        )

    def action_fade_shorter(self) -> None:
        self._adjust_fade(-1.0)

    def action_fade_longer(self) -> None:
        self._adjust_fade(1.0)

    def _adjust_fade(self, delta: float) -> None:
        previous_fade = self.transition_settings.fade_seconds
        settings = self.playback.adjust_fade_seconds(delta)
        self.transition_settings = settings
        suffix = self._persist_transition(settings)
        self._set_status(f"{self._fade_message(previous_fade, settings, delta)}{suffix}")

    def _fade_message(
        self, previous_fade: float, settings: TransitionSettings, delta: float
    ) -> str:
        if settings.fade_seconds == previous_fade:
            bound = "minimum (1s)" if delta < 0 else "maximum (15s)"
            return f"Fade length at {bound}."
        if settings.style is TransitionStyle.CUT:
            return f"Fade length {settings.fade_seconds:g}s (transition is cut; press t to mix)."
        return f"Fade length {settings.fade_seconds:g}s."

    def _persist_transition(self, settings: TransitionSettings) -> str:
        try:
            save_transition_settings(settings)
        except ConfigError as exc:
            return f" Not saved: {exc}"
        return ""
