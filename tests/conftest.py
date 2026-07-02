"""Shared test configuration: make Textual pilot tests fast.

Three levers, all test-only and behavior-preserving:

1. Idle-poll granularity. Textual's ``wait_for_idle`` (used by ``pilot.pause``
   and ``pilot.press``) sleeps in ``SLEEP_GRANULARITY`` windows of 20 ms, so
   every pause/press costs several windows of wall time even though the real
   synchronization happens in ``Pilot._wait_for_screen`` (callback-counted, no
   sleeps). Shrinking the window keeps the same idle heuristic while cutting
   the fixed per-pause sleep tax. ``TEXTUAL_FPS`` is raised to match: deferred
   work (e.g. ``scroll_visible(immediate=False)``) runs on the screen update
   timer (period ``1 / TEXTUAL_FPS``) and must land within the shorter idle
   windows. That timer self-pauses when idle, so a high FPS cannot busy-loop.

2. Animations off. Headless pilot tests never assert on animation frames, but
   ``App._press_keys`` awaits ``animator.wait_until_complete`` after every
   key, so real-time animations (screen transitions, scrolls) add real waits.

3. Shared CSS parse cache. Textual's parse cache lives on the per-app
   ``Stylesheet`` instance, so every pilot boot re-parses the identical app
   and DEFAULT_CSS strings. One process-wide cache removes that; parsed rules
   are treated as immutable by Textual (it already reuses them across
   widgets), and theme variables affect parsing so they are part of the key.

GC is also disabled: mounting a Textual app allocates heavily and the default
generational thresholds trigger many full collections across ~40 app boots.
The suite is short-lived; peak RSS stays around 0.5 GB.
"""

from __future__ import annotations

import gc
import os

# Must be set before textual.constants is imported (conftest runs first).
os.environ.setdefault("TEXTUAL_ANIMATIONS", "NONE")
os.environ.setdefault("TEXTUAL_FPS", "500")

import textual._wait as _textual_wait
from textual.css.stylesheet import Stylesheet

_FAST_GRANULARITY = 0.002
_textual_wait.SLEEP_GRANULARITY = _FAST_GRANULARITY
_textual_wait.SLEEP_IDLE = _FAST_GRANULARITY / 20.0

_shared_parse_cache: dict[object, object] = {}
_original_parse_rules = Stylesheet._parse_rules


def _cached_parse_rules(self, css, read_from, is_default_rules=False, tie_breaker=0, scope=""):
    key = (
        css,
        read_from,
        is_default_rules,
        tie_breaker,
        scope,
        tuple(sorted(self._variables.items())),
    )
    try:
        return _shared_parse_cache[key]
    except KeyError:
        rules = _original_parse_rules(self, css, read_from, is_default_rules, tie_breaker, scope)
        _shared_parse_cache[key] = rules
        return rules


Stylesheet._parse_rules = _cached_parse_rules  # type: ignore[method-assign]

gc.disable()
gc.freeze()
