"""Read playback status and detect failed or truncated audio streams."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from .mpv_ipc import MpvCommandError, MpvIpcError, rms_db_from_astats
from .playback_status import PlaybackStatus
from .radio import is_radio_video_id
from .transition_settings import TransitionStyle

if TYPE_CHECKING:
    from .playback import PlaybackController


def read_status(controller: PlaybackController) -> PlaybackStatus:
    controller.tick()
    check_playback_failure(controller)
    running = bool(controller.process and controller.process.poll() is None)
    position = None
    duration = None
    volume = None
    muted = False
    paused = controller.paused and running
    # A SIGSTOP-paused mpv cannot answer IPC; skip the poll so status
    # returns promptly with the cached paused state instead of wedging.
    if running and controller.ipc_socket and not controller._paused_via_signal:
        client = controller._live_client()
        try:
            sampled_at = time.monotonic()
            position = _available(client.get_float, "time-pos")
            if not is_radio_video_id(controller.current_video_id or ""):
                # mpv reports a live stream's buffered extent as a growing duration.
                duration = _available(client.get_float, "duration")
            cache_timing(controller, position, duration, client.get_float("speed"), sampled_at)
            volume = client.get_float("volume")
            muted = bool(client.get_property("mute"))
            paused = bool(client.get_property("pause"))
            controller.paused = paused
            controller.muted = muted
        except MpvIpcError:
            # The live mpv may be mid-teardown; report what is known.
            pass
    if controller._is_mixing():
        # Report the user-facing level, not the mid-ramp deck volume.
        volume = controller.master_volume
    return PlaybackStatus(
        running=running,
        current_video_id=controller.current_video_id if running else None,
        paused=paused,
        position_seconds=position,
        duration_seconds=duration,
        volume=volume,
        muted=muted,
        transition_style=controller.transition.style.value,
        fade_seconds=controller.transition.fade_seconds,
        mix_progress=eng.mix_progress if (eng := controller._engine) and eng.is_mixing else None,
        active_deck=controller.active_deck,
        transition_error=controller.last_transition_error,
        playback_error=controller.playback_error,
        process_id=controller.process.pid if running and controller.process else None,
    )


def read_audio_level(controller: PlaybackController) -> float | None:
    """Current overall RMS loudness in dB from the live deck, if available."""
    if not controller.process or controller.process.poll() is not None or not controller.ipc_socket:
        return None
    if controller._paused_via_signal:
        return None
    try:
        # Polled every visual frame (~50ms); a slow reply must not stall the tick.
        metadata = controller._live_client().get_property("af-metadata/astats", 0.05)
    except MpvIpcError:
        return None
    return rms_db_from_astats(metadata)


def cache_timing(
    controller: PlaybackController,
    position: float | None,
    duration: float | None,
    speed: float | None,
    sampled_at: float,
) -> None:
    if controller.process is controller._seeked_process:
        return
    if any(value is None or not math.isfinite(value) for value in (position, duration, speed)):
        return
    assert position is not None and duration is not None and speed is not None
    if position < 0 or duration <= 0 or speed <= 0:
        return
    controller._timing_process = controller.process
    controller._timing_sample = (position, duration, speed, sampled_at)


def check_playback_failure(controller: PlaybackController) -> bool:
    if controller.playback_error:
        return True
    if controller.process is None:
        return False
    exit_code = controller.process.poll()
    if exit_code is None:
        return False
    reason = f"mpv exited with exit code {exit_code}" if exit_code else None
    if (
        exit_code == 0
        and controller.process is controller._timing_process
        and controller._timing_sample
    ):
        position, duration, speed, sampled_at = controller._timing_sample
        elapsed = time.monotonic() - sampled_at
        # Old samples cannot distinguish a complete track from a lost stream.
        # Allow twice the sampled speed plus five seconds for timing jitter.
        if 0 <= elapsed <= 10 and duration - position > elapsed * speed * 2 + 5:
            reason = "the audio stream ended early"
    if reason is None:
        return False
    controller.playback_error = f"Playback failed: {reason}. Retry or choose next."
    controller.stop()
    controller._engine = None
    return True


def _available(read: Callable[[str], float | None], name: str) -> float | None:
    """A property value, or None while mpv has none yet (a track that still loads)."""
    try:
        return read(name)
    except MpvCommandError:
        return None


def consume_transition_error(controller: PlaybackController) -> str | None:
    """Return and clear the pending mix-failure message; status() only reports it."""
    error = controller.last_transition_error
    controller.last_transition_error = None
    return error


def tick(controller: PlaybackController) -> None:
    if check_playback_failure(controller):
        return
    if controller._paused_via_signal:
        # A stopped mpv cannot answer the engine's timing reads, and
        # pause_resume() snapped any active fade before signalling.
        return
    if controller.transition.style is TransitionStyle.CUT:
        if controller._engine is not None:
            controller._engine.discard_idle_deck()
        return
    controller._ensure_engine().tick()
