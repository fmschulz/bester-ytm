from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .deck import remove_socket_file, spawn_mpv, terminate_process
from .mpv_ipc import MpvIpcClient, MpvIpcError, rms_db_from_astats
from .playback_status import PlaybackStatus  # noqa: F401  (re-exported)
from .transitions import (
    MANUAL_MIX_MAX_SECONDS,
    TransitionEngine,
    TransitionSettings,
    TransitionStyle,
)


class PlaybackError(RuntimeError):
    pass


@dataclass
class PlaybackController:
    process: subprocess.Popen[str] | None = None
    current_video_id: str | None = None
    queue: list[str] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    ipc_socket: Path | None = None
    paused: bool = False
    transition: TransitionSettings = field(default_factory=TransitionSettings)
    master_volume: float = 100.0
    active_deck: str = "A"
    last_transition_error: str | None = None
    _engine: TransitionEngine | None = field(default=None, init=False, repr=False)
    _paused_via_signal: bool = field(default=False, init=False, repr=False)

    def _mpv_path(self) -> str:
        mpv = shutil.which("mpv")
        if not mpv:
            raise PlaybackError("mpv is not installed or not on PATH")
        return mpv

    def _require_stream_resolver(self) -> None:
        if not shutil.which("yt-dlp") and not shutil.which("youtube-dl"):
            raise PlaybackError(
                "yt-dlp is not installed or not on PATH; mpv cannot resolve "
                "music.youtube.com streams reliably"
            )

    def play_video(self, video_id: str, seconds: int | None = None) -> PlaybackStatus:
        self.stop()
        self._require_stream_resolver()
        self.current_video_id = None
        ipc_socket = Path(tempfile.gettempdir()) / f"bester-ytm-mpv-{os.getpid()}.sock"
        remove_socket_file(ipc_socket)
        process = spawn_mpv(
            self._mpv_path(),
            video_id,
            ipc_socket,
            paused=False,
            volume=self.master_volume,
        )
        time.sleep(0.25)
        if process.poll() is not None:
            exit_code = process.returncode
            remove_socket_file(ipc_socket)
            raise PlaybackError(
                f"mpv exited before playback started (exit code {exit_code}); "
                "check network access and yt-dlp/mpv support for YouTube Music"
            )
        self.process = process
        self.current_video_id = video_id
        self.ipc_socket = ipc_socket
        self.paused = False
        self.active_deck = "A"
        if seconds:
            try:
                time.sleep(seconds)
            finally:
                self.stop()
        return self.status()

    def enqueue(self, video_ids: list[str]) -> None:
        self.queue.extend(video_ids)

    def replace_queue(self, video_ids: list[str]) -> None:
        self.stop()
        self.current_video_id = None
        self.queue = list(video_ids)
        self.history.clear()
        self.paused = False

    def play_queue(self) -> PlaybackStatus:
        if not self.queue:
            raise PlaybackError("queue is empty")
        next_video = self.queue[0]
        previous_video = self.current_video_id
        status = self.play_video(next_video)
        self.queue.pop(0)
        if previous_video:
            self.history.append(previous_video)
        return status

    def next(self) -> PlaybackStatus:
        if (
            self.queue
            and self._engine is not None
            and self._engine.can_quick_mix(self.queue[0])
            and self._engine.begin_crossfade(
                min(self.transition.fade_seconds, MANUAL_MIX_MAX_SECONDS)
            )
        ):
            return self.status()
        self._snap_active_transition()
        return self.play_queue()

    def previous(self) -> PlaybackStatus:
        self._snap_active_transition()
        if not self.history:
            return self.status()
        previous_video = self.history[-1]
        current_video = self.current_video_id
        status = self.play_video(previous_video)
        self.history.pop()
        if current_video:
            self.queue.insert(0, current_video)
        return status

    def pause_resume(self) -> PlaybackStatus:
        self._snap_active_transition()
        if not self.process or self.process.poll() is not None:
            return self.status()
        if self._paused_via_signal:
            # A stopped mpv cannot answer IPC; resume it with SIGCONT directly.
            self.process.send_signal(signal.SIGCONT)
            self._paused_via_signal = False
        else:
            try:
                self._send_ipc({"command": ["cycle", "pause"]})
            except PlaybackError:
                self.process.send_signal(
                    signal.SIGSTOP if not self.paused else signal.SIGCONT
                )
                self._paused_via_signal = not self.paused
        self.paused = not self.paused
        return self.status()

    def _transport_ipc_unavailable(self) -> bool:
        """No live mpv, or a SIGSTOP-paused one that cannot answer IPC."""
        if not self.process or self.process.poll() is not None:
            return True
        return self._paused_via_signal

    def seek_relative(self, seconds: float) -> PlaybackStatus:
        if self._transport_ipc_unavailable():
            return self.status()
        self._send_ipc({"command": ["seek", seconds, "relative"]})
        return self.status()

    def seek_absolute(self, seconds: float) -> PlaybackStatus:
        if self._transport_ipc_unavailable():
            return self.status()
        self._send_ipc({"command": ["seek", max(0.0, seconds), "absolute"]})
        return self.status()

    def set_volume(self, volume: float) -> PlaybackStatus:
        clamped = max(0.0, min(100.0, volume))
        self.master_volume = clamped
        if self._is_mixing():
            # The fader re-reads master_volume every step; no IPC fight here.
            return self.status()
        if self._transport_ipc_unavailable():
            return self.status()
        self._send_ipc({"command": ["set_property", "volume", clamped]})
        return self.status()

    def change_volume(self, delta: float) -> PlaybackStatus:
        status = self.status()
        current = status.volume if status.volume is not None else 100.0
        return self.set_volume(current + delta)

    def toggle_mute(self) -> PlaybackStatus:
        if self._transport_ipc_unavailable():
            return self.status()
        self._send_ipc({"command": ["cycle", "mute"]})
        if self._is_mixing():
            self._mirror_mute_to_draining_deck()
        return self.status()

    def _mirror_mute_to_draining_deck(self) -> None:
        if self._engine is None:
            return
        try:
            muted = bool(self._get_property("mute"))
        except PlaybackError:
            return
        self._engine.mirror_mute_to_draining(muted)

    def _request_ipc(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            return self._live_client().request(payload)
        except MpvIpcError as exc:
            raise PlaybackError(str(exc)) from exc

    def _live_client(self) -> MpvIpcClient:
        if not self.ipc_socket:
            raise PlaybackError("mpv IPC socket is not configured")
        return MpvIpcClient(socket_path=self.ipc_socket)

    def _send_ipc(self, payload: dict[str, object]) -> None:
        self._request_ipc(payload)

    def _get_property(self, name: str) -> object | None:
        response = self._request_ipc({"command": ["get_property", name]})
        return response.get("data")

    def stop(self) -> None:
        if self._engine is not None:
            self._engine.shutdown()
        if self.process is not None:
            terminate_process(self.process)
        self.process = None
        if self.ipc_socket is not None:
            remove_socket_file(self.ipc_socket)
        self.paused = False
        self._paused_via_signal = False

    def status(self) -> PlaybackStatus:
        self.tick()
        running = bool(self.process and self.process.poll() is None)
        position = None
        duration = None
        volume = None
        muted = False
        paused = self.paused and running
        # A SIGSTOP-paused mpv cannot answer IPC; skip the poll so status
        # returns promptly with the cached paused state instead of wedging.
        if running and self.ipc_socket and not self._paused_via_signal:
            client = self._live_client()
            try:
                position = client.get_float("time-pos")
                duration = client.get_float("duration")
                volume = client.get_float("volume")
                muted = bool(client.get_property("mute"))
                paused = bool(client.get_property("pause"))
                self.paused = paused
            except MpvIpcError:
                # The live mpv may be mid-teardown; report what is known.
                pass
        if self._is_mixing():
            # Report the user-facing level, not the mid-ramp deck volume.
            volume = self.master_volume
        return PlaybackStatus(
            running=running,
            current_video_id=self.current_video_id if running else None,
            queue_size=len(self.queue),
            paused=paused,
            position_seconds=position,
            duration_seconds=duration,
            volume=volume,
            muted=muted,
            transition_style=self.transition.style.value,
            fade_seconds=self.transition.fade_seconds,
            mix_progress=eng.mix_progress if (eng := self._engine) and eng.is_mixing else None,
            active_deck=self.active_deck,
            transition_error=self.last_transition_error,
        )

    def read_audio_level_db(self) -> float | None:
        """Current overall RMS loudness in dB from the live deck, if available."""
        if not self.process or self.process.poll() is not None or not self.ipc_socket:
            return None
        if self._paused_via_signal:
            return None
        try:
            # Polled every visual frame (~50ms); a slow reply must not stall the tick.
            metadata = self._live_client().get_property("af-metadata/astats", 0.05)
        except MpvIpcError:
            return None
        return rms_db_from_astats(metadata)

    def consume_transition_error(self) -> str | None:
        """Return and clear the pending mix-failure message; status() only reports it."""
        error = self.last_transition_error
        self.last_transition_error = None
        return error

    def tick(self) -> None:
        if self._paused_via_signal:
            # A stopped mpv cannot answer the engine's timing reads, and
            # pause_resume() snapped any active fade before signalling.
            return
        if self.transition.style is TransitionStyle.CUT:
            if self._engine is not None:
                self._engine.discard_idle_deck()
            return
        self._ensure_engine().tick()

    def set_transition_style(self, style: TransitionStyle) -> TransitionSettings:
        if style is TransitionStyle.CUT and self._engine is not None:
            self._engine.snap()
            self._engine.discard_idle_deck()
        self.transition = TransitionSettings(
            style=style, fade_seconds=self.transition.fade_seconds
        )
        return self.transition

    def cycle_transition_style(self) -> TransitionSettings:
        if self.transition.style is TransitionStyle.CUT:
            return self.set_transition_style(TransitionStyle.CROSSFADE)
        return self.set_transition_style(TransitionStyle.CUT)

    def adjust_fade_seconds(self, delta: float) -> TransitionSettings:
        self.transition = TransitionSettings(
            style=self.transition.style,
            fade_seconds=self.transition.fade_seconds + delta,
        ).clamped()
        return self.transition

    def _ensure_engine(self) -> TransitionEngine:
        if self._engine is None:
            self._engine = TransitionEngine(self)
        return self._engine

    def _snap_active_transition(self) -> None:
        if self._engine is not None:
            self._engine.snap()

    def _is_mixing(self) -> bool:
        return self._engine is not None and self._engine.is_mixing
