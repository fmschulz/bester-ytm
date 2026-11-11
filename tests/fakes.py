"""Shared widget and playback doubles for tests that do not boot the TUI."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Generic, TypeVar

from bester_ytm.playback import PlaybackError, PlaybackStatus
from bester_ytm.transitions import TransitionSettings, TransitionStyle

Item = TypeVar("Item")


class FakeListView(Generic[Item]):
    """Keep rows and a cursor, and record focus without mounting widgets."""

    def __init__(self, items: Iterable[Item] = ()) -> None:
        self.items = list(items)
        self.index: int | None = 0
        self.focus_calls = 0

    @property
    def children(self) -> list[Item]:
        return self.items

    @property
    def highlighted_child(self) -> Item | None:
        if self.index is None or not self.items:
            return None
        return self.items[self.index]

    @highlighted_child.setter
    def highlighted_child(self, item: Item | None) -> None:
        if item is None:
            self.index = None
            return
        if item not in self.items:
            self.items.append(item)
        self.index = self.items.index(item)

    async def clear(self) -> None:
        self.items.clear()
        self.index = 0

    async def append(self, item: Item) -> None:
        self.items.append(item)

    async def extend(self, items: Iterable[Item]) -> None:
        self.items.extend(items)

    def focus(self) -> None:
        self.focus_calls += 1


class FakeStatic:
    """Keep the last text value and count updates."""

    def __init__(self, value: object = "") -> None:
        self.value = value
        self.update_count = 0

    def update(self, value: object) -> None:
        self.value = value
        self.update_count += 1


class FakeInput:
    """Hold an editable input value without Textual's reactive state."""

    def __init__(self, value: str = "") -> None:
        self.value = value


class FakePlayback:
    """Keep playback state and record queue and transport commands."""

    def __init__(
        self,
        current: str | None = None,
        queue: Iterable[str] = (),
        *,
        running: bool | None = None,
    ) -> None:
        self.current_video_id = current
        self.queue = list(queue)
        self._running = running
        self.current: PlaybackStatus | None = None
        self.history: list[str] = []
        self.replaced: list[str] | None = None
        self.enqueued: list[str] = []
        self.seeks: list[float] = []
        self.paused = False
        self.volume = 100.0
        self.muted = False
        self.stopped = False
        self.error: PlaybackError | None = None

    @property
    def running(self) -> bool:
        return self.current_video_id is not None if self._running is None else self._running

    @running.setter
    def running(self, value: bool) -> None:
        self._running = value

    def status(self) -> PlaybackStatus:
        if self.current is not None:
            return self.current
        return PlaybackStatus(
            running=self.running,
            current_video_id=self.current_video_id,
            queue_size=len(self.queue),
            paused=self.paused,
            volume=self.volume,
            muted=self.muted,
        )

    def enqueue(self, video_ids: list[str]) -> None:
        self.enqueued.extend(video_ids)
        self.queue.extend(video_ids)

    def replace_queue(self, video_ids: list[str]) -> None:
        self.replaced = list(video_ids)
        self.queue = list(video_ids)
        self.current_video_id = None
        self._running = None

    def play_queue(self) -> PlaybackStatus:
        self._check_error()
        self.current_video_id = self.queue.pop(0)
        self._running = None
        return self.status()

    def next(self) -> PlaybackStatus:
        return self.play_queue()

    def previous(self) -> PlaybackStatus:
        self._check_error()
        self.current_video_id = "prev"
        self._running = None
        return self.status()

    def pause_resume(self) -> PlaybackStatus:
        self._check_error()
        self.paused = not self.paused
        return self.status()

    def seek_relative(self, seconds: float) -> PlaybackStatus:
        self._check_error()
        self.seeks.append(seconds)
        return self.status()

    def seek_absolute(self, seconds: float) -> PlaybackStatus:
        return self.seek_relative(seconds)

    def change_volume(self, delta: float) -> PlaybackStatus:
        self._check_error()
        self.volume += delta
        return self.status()

    def toggle_mute(self) -> PlaybackStatus:
        self._check_error()
        self.muted = not self.muted
        return self.status()

    def stop(self) -> None:
        self.stopped = True
        self.current_video_id = None
        self._running = None

    def consume_transition_error(self) -> str | None:
        if self.current is None:
            return None
        error = self.current.transition_error
        self.current = replace(self.current, transition_error=None)
        return error

    def _check_error(self) -> None:
        if self.error is not None:
            raise self.error


class FakeTransitionPlayback(FakePlayback):
    """Add editable transition settings to the playback double."""

    def __init__(
        self,
        style: TransitionStyle = TransitionStyle.CUT,
        fade_seconds: float = 6.0,
    ) -> None:
        super().__init__()
        self.transition = TransitionSettings(style=style, fade_seconds=fade_seconds)
        self.current = PlaybackStatus(running=False)

    def cycle_transition_style(self) -> TransitionSettings:
        next_style = (
            TransitionStyle.CROSSFADE
            if self.transition.style is TransitionStyle.CUT
            else TransitionStyle.CUT
        )
        self.transition = replace(self.transition, style=next_style)
        return self.transition

    def adjust_fade_seconds(self, delta: float) -> TransitionSettings:
        self.transition = replace(
            self.transition, fade_seconds=self.transition.fade_seconds + delta
        ).clamped()
        return self.transition
