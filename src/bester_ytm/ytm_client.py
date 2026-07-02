"""Facade for YouTube Music access.

The implementation lives in focused modules; this module composes them into
the public `YTMClient` and re-exports every name external code imports.
Outside the ytm_* modules, only auth.py (login setup) touches ytmusicapi.
"""

from __future__ import annotations

from .ytm_library import VALID_PRIVACY, YTMLibraryMixin
from .ytm_models import (
    AddResult,
    AuthStatus,
    PlaylistSnapshot,
    YTMClientError,
    _artist_names,
    _duration_to_seconds,
    normalize_album,
    normalize_playlist_result,
    normalize_song,
    playlist_item_to_candidate,
)
from .ytm_search import YTMSearchMixin
from .ytm_session import YOUTUBE_API_BASE, _SerializedYTMusic


class YTMClient(YTMSearchMixin, YTMLibraryMixin):
    """Authenticated (or anonymous) YouTube Music client."""


__all__ = [
    "AddResult",
    "AuthStatus",
    "PlaylistSnapshot",
    "VALID_PRIVACY",
    "YOUTUBE_API_BASE",
    "YTMClient",
    "YTMClientError",
    "_SerializedYTMusic",
    "_artist_names",
    "_duration_to_seconds",
    "normalize_album",
    "normalize_playlist_result",
    "normalize_song",
    "playlist_item_to_candidate",
]
