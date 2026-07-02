"""Tick-driven dual-deck engine for DJ-style crossfade transitions.

All scheduling and host mutation happens in tick(), which the frontends drive
by polling status(). Only the volume ramp runs on a short-lived fader thread.
The engine never advances the queue on a dead live process; cut-advance on
death stays the frontends' fallback, which prevents double-advance races.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .deck import Deck, DeckReaper, DeckState, spawn_prebuffer_deck
from .fader import Fader
from .mpv_ipc import MpvIpcClient, MpvIpcError
from .transition_settings import (  # noqa: F401  (re-exported for import sites)
    DEFAULT_APP_SETTINGS,
    MANUAL_MIX_MAX_SECONDS,
    MAX_FADE_SECONDS,
    MIN_FADE_SECONDS,
    TransitionSettings,
    TransitionStyle,
)

PREBUFFER_LEAD_SECONDS = 12.0
TICK_READ_DEADLINE_SECONDS = 0.3
FADE_SEND_DEADLINE_SECONDS = 0.25
MIN_MIX_SECONDS = 0.5
SPAWN_RETRY_SECONDS = 5.0
SNAP_EXTRA_JOIN_SECONDS = 2.0
ApplyGains = Callable[[float, float], None]


class DeckHost(Protocol):
    """Duck-typed view of PlaybackController; avoids a circular import."""

    process: subprocess.Popen[str] | None
    ipc_socket: Path | None
    current_video_id: str | None
    queue: list[str]
    history: list[str]
    paused: bool
    master_volume: float
    active_deck: str
    transition: TransitionSettings
    last_transition_error: str | None

    def _mpv_path(self) -> str: ...


class TransitionEngine:
    def __init__(self, host: DeckHost) -> None:
        self.host = host
        self.idle_deck: Deck | None = None
        self.draining_deck: Deck | None = None
        self.fader: Fader | None = None
        self.reaper = DeckReaper()
        self._last_spawn_video_id: str | None = None
        self._last_spawn_at: float = 0.0

    @property
    def is_mixing(self) -> bool:
        return self.fader is not None

    @property
    def mix_progress(self) -> float | None:
        return self.fader.progress if self.fader is not None else None

    def can_quick_mix(self, video_id: str) -> bool:
        if self.is_mixing:
            return False
        if self.host.transition.style is not TransitionStyle.CROSSFADE:
            return False
        if not self._is_live_process_running():
            return False
        idle = self.idle_deck
        return idle is not None and idle.state is DeckState.READY and idle.video_id == video_id

    def tick(self) -> None:
        self.reaper.reap()
        if self.fader is not None:
            if not self.fader.is_active:
                self._finalize_fade()
            return
        if self.host.transition.style is not TransitionStyle.CROSSFADE or not self.host.queue:
            self.discard_idle_deck()
            return
        if not self._is_live_process_running():
            return
        timing = self._read_live_timing()
        if timing is None:
            return
        position, duration = timing
        effective_fade = max(MIN_FADE_SECONDS, min(self.host.transition.fade_seconds, duration / 3))
        remaining = max(0.0, duration - position)
        self._maintain_idle_deck(remaining, effective_fade)
        self._maybe_begin_scheduled_crossfade(remaining, effective_fade)

    def begin_crossfade(self, fade_seconds: float) -> bool:
        incoming = self.idle_deck
        if incoming is None or not self._can_promote(incoming):
            self.discard_idle_deck()
            return False
        if not self._prepare_incoming_deck(incoming):
            return False
        self._promote(incoming, fade_seconds)
        return True

    def snap(self) -> None:
        fader = self.fader
        if fader is None:
            return
        fader.cancel()
        if fader.is_active:
            # Wait out an in-flight gain send; finalize must not race it.
            fader.cancel(SNAP_EXTRA_JOIN_SECONDS)
        self._finalize_fade()

    def discard_idle_deck(self) -> None:
        idle, self.idle_deck = self.idle_deck, None
        if idle is not None:
            self.reaper.retire(idle)

    def mirror_mute_to_draining(self, muted: bool) -> None:
        draining = self.draining_deck
        if self.fader is None or draining is None:
            return
        try:
            draining.set_muted(muted)
        except MpvIpcError:
            # Best effort: a dying outgoing deck must not break mute toggling.
            pass

    def shutdown(self) -> None:
        self.snap()
        self.discard_idle_deck()
        self.reaper.flush()

    def _maintain_idle_deck(self, remaining: float, effective_fade: float) -> None:
        idle = self.idle_deck
        if idle is not None and self._is_idle_deck_stale(idle):
            self.discard_idle_deck()
            idle = None
        if idle is None:
            if remaining <= effective_fade + PREBUFFER_LEAD_SECONDS:
                self._spawn_idle_deck()
            return
        if idle.state is DeckState.LOADING:
            idle.refresh_readiness()
            if idle.state is DeckState.LOADING and remaining <= MIN_MIX_SECONDS:
                self.discard_idle_deck()

    def _is_idle_deck_stale(self, idle: Deck) -> bool:
        return idle.video_id != self.host.queue[0] or not idle.is_process_running()

    def _spawn_idle_deck(self) -> None:
        video_id = self.host.queue[0]
        now = time.monotonic()
        is_recent_retry = video_id == self._last_spawn_video_id
        if is_recent_retry and now - self._last_spawn_at < SPAWN_RETRY_SECONDS:
            return
        self._last_spawn_video_id = video_id
        self._last_spawn_at = now
        try:
            self.idle_deck = spawn_prebuffer_deck(
                self._other_deck_name(), video_id, self.host._mpv_path()
            )
        except (MpvIpcError, OSError, RuntimeError) as exc:
            # Includes PlaybackError; a failed prebuffer degrades to a cut.
            self.host.last_transition_error = str(exc)

    def _maybe_begin_scheduled_crossfade(self, remaining: float, effective_fade: float) -> None:
        idle = self.idle_deck
        if self.host.paused or idle is None or idle.state is not DeckState.READY:
            return
        if remaining > effective_fade:
            return
        self.begin_crossfade(min(effective_fade, max(MIN_MIX_SECONDS, remaining)))

    def _can_promote(self, incoming: Deck) -> bool:
        if incoming.state is not DeckState.READY:
            return False
        if not self.host.queue or incoming.video_id != self.host.queue[0]:
            return False
        return self.host.process is not None and self.host.ipc_socket is not None

    def _prepare_incoming_deck(self, incoming: Deck) -> bool:
        outgoing_is_muted = self._read_live_muted()
        try:
            incoming.set_volume(0.0, FADE_SEND_DEADLINE_SECONDS)
            if outgoing_is_muted:
                incoming.set_muted(True, FADE_SEND_DEADLINE_SECONDS)
            incoming.set_paused(False, FADE_SEND_DEADLINE_SECONDS)
        except MpvIpcError as exc:
            self.host.last_transition_error = f"cannot start crossfade deck {incoming.name}: {exc}"
            self.discard_idle_deck()
            return False
        return True

    def _promote(self, incoming: Deck, fade_seconds: float) -> None:
        host = self.host
        self.draining_deck = self._wrap_outgoing_deck()
        started = host.queue.pop(0)
        if host.current_video_id:
            host.history.append(host.current_video_id)
        host.current_video_id = started
        host.process = incoming.process
        host.ipc_socket = incoming.ipc_socket
        host.paused = False
        host.active_deck = incoming.name
        host.last_transition_error = None
        incoming.state = DeckState.LIVE
        self.idle_deck = None
        self.fader = Fader(
            duration_seconds=fade_seconds,
            apply_gains=self._make_apply_gains(self.draining_deck, incoming.ipc_socket),
            get_master_volume=lambda: host.master_volume,
        )
        self.fader.start()

    def _wrap_outgoing_deck(self) -> Deck:
        host = self.host
        return Deck(
            name=host.active_deck,
            video_id=host.current_video_id or "",
            process=host.process,  # type: ignore[arg-type]  # live deck guaranteed by tick()
            ipc_socket=host.ipc_socket,  # type: ignore[arg-type]
            state=DeckState.DRAINING,
        )

    def _make_apply_gains(self, outgoing: Deck, incoming_socket: Path) -> ApplyGains:
        outgoing_client = MpvIpcClient(socket_path=outgoing.ipc_socket)
        incoming_client = MpvIpcClient(socket_path=incoming_socket)

        def apply_gains(outgoing_volume: float, incoming_volume: float) -> None:
            try:
                _send_volume(outgoing_client, outgoing_volume)
            except MpvIpcError:
                # The outgoing deck routinely dies at natural track end.
                pass
            _send_volume(incoming_client, incoming_volume)

        return apply_gains

    def _finalize_fade(self) -> None:
        fader = self.fader
        if fader is None:
            return
        if self.draining_deck is not None:
            self.reaper.retire(self.draining_deck)
        self.draining_deck = None
        self.fader = None
        if fader.failure_reason is not None:
            self.host.last_transition_error = fader.failure_reason
        # Always restore; a failed mid-ramp leaves the live deck near-silent.
        self._restore_live_volume()

    def _restore_live_volume(self) -> None:
        host = self.host
        if host.ipc_socket is None or not self._is_live_process_running():
            return
        client = MpvIpcClient(socket_path=host.ipc_socket)
        payload: dict[str, object] = {"command": ["set_property", "volume", host.master_volume]}
        try:
            client.send(payload, TICK_READ_DEADLINE_SECONDS)
        except MpvIpcError as exc:
            if host.last_transition_error is None:
                host.last_transition_error = str(exc)

    def _is_live_process_running(self) -> bool:
        return self.host.process is not None and self.host.process.poll() is None

    def _read_live_timing(self) -> tuple[float, float] | None:
        socket_path = self.host.ipc_socket
        if socket_path is None:
            return None
        client = MpvIpcClient(socket_path=socket_path)
        try:
            position = client.get_float("time-pos", TICK_READ_DEADLINE_SECONDS)
            duration = client.get_float("duration", TICK_READ_DEADLINE_SECONDS)
        except MpvIpcError:
            return None
        if duration is None or duration <= 0:
            return None
        return (position or 0.0, duration)

    def _read_live_muted(self) -> bool:
        socket_path = self.host.ipc_socket
        if socket_path is None:
            return False
        client = MpvIpcClient(socket_path=socket_path)
        try:
            return bool(client.get_property("mute", TICK_READ_DEADLINE_SECONDS))
        except MpvIpcError:
            return False

    def _other_deck_name(self) -> str:
        return "B" if self.host.active_deck == "A" else "A"


def _send_volume(client: MpvIpcClient, volume: float) -> None:
    clamped = max(0.0, min(100.0, volume))
    client.send({"command": ["set_property", "volume", clamped]}, FADE_SEND_DEADLINE_SECONDS)
