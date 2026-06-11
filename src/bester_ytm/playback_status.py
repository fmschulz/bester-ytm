"""Snapshot DTO that PlaybackController.status() reports to the frontends."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlaybackStatus:
    running: bool
    current_video_id: str | None = None
    queue_size: int = 0
    paused: bool = False
    position_seconds: float | None = None
    duration_seconds: float | None = None
    volume: float | None = None
    muted: bool = False
    transition_style: str = "cut"
    fade_seconds: float = 6.0
    mix_progress: float | None = None
    active_deck: str = "A"
    transition_error: str | None = None
