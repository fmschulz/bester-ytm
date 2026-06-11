"""Equal-power volume ramp between two mpv decks on a short-lived thread."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .mpv_ipc import MpvIpcError

FADE_STEP_SECONDS = 0.1


def equal_power_gains(progress: float) -> tuple[float, float]:
    """Return (outgoing, incoming) gains in 0..1 for a clamped progress."""
    clamped = max(0.0, min(1.0, progress))
    angle = clamped * math.pi / 2
    return (math.cos(angle), math.sin(angle))


@dataclass
class Fader:
    """Ramps two absolute mpv volumes from master/0 to 0/master.

    The fader never mutates controller state and never forces final volumes;
    finalization happens in the engine tick on the polling thread.
    """

    duration_seconds: float
    apply_gains: Callable[[float, float], None]
    get_master_volume: Callable[[], float]
    step_seconds: float = FADE_STEP_SECONDS
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    failure_reason: str | None = field(default=None, init=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _cancel_event: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _progress: float = field(default=0.0, init=False)
    _done: bool = field(default=False, init=False)

    @property
    def is_active(self) -> bool:
        return not self._done

    @property
    def progress(self) -> float:
        return self._progress

    def start(self) -> None:
        thread = threading.Thread(target=self.run, name="bester-ytm-fader", daemon=True)
        self._thread = thread
        thread.start()

    def run(self) -> None:
        started_at = self.clock()
        try:
            while not self._cancel_event.is_set():
                self._progress = self._progress_at(self.clock() - started_at)
                outgoing_gain, incoming_gain = equal_power_gains(self._progress)
                master = self.get_master_volume()
                try:
                    self.apply_gains(master * outgoing_gain, master * incoming_gain)
                except MpvIpcError as exc:
                    self.failure_reason = str(exc)
                    return
                if self._progress >= 1.0:
                    return
                self.sleep(self.step_seconds)
        finally:
            self._done = True

    def cancel(self, join_timeout_seconds: float = 1.0) -> None:
        self._cancel_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(join_timeout_seconds)

    def _progress_at(self, elapsed_seconds: float) -> float:
        if self.duration_seconds <= 0:
            return 1.0
        return min(1.0, elapsed_seconds / self.duration_seconds)
