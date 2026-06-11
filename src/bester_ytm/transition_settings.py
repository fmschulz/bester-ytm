"""User-facing transition settings shared by the engine, config, and frontends."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

MIN_FADE_SECONDS = 1.0
MAX_FADE_SECONDS = 15.0
MANUAL_MIX_MAX_SECONDS = 2.0


class TransitionStyle(StrEnum):
    CUT = "cut"
    CROSSFADE = "crossfade"


@dataclass(frozen=True)
class TransitionSettings:
    style: TransitionStyle = TransitionStyle.CUT
    fade_seconds: float = 6.0

    def clamped(self) -> TransitionSettings:
        bounded = max(MIN_FADE_SECONDS, min(MAX_FADE_SECONDS, self.fade_seconds))
        return TransitionSettings(style=self.style, fade_seconds=bounded)


DEFAULT_APP_SETTINGS = TransitionSettings(style=TransitionStyle.CROSSFADE, fade_seconds=6.0)
