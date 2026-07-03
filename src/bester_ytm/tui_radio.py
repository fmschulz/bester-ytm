"""Radio now-playing polling, radio-song favoriting, and AI station adding."""

from __future__ import annotations

import re
import time
from functools import partial

from .config import ConfigError, get_paths
from .intelligence.llm import IntelligenceError, resolve_provider
from .intelligence.station_finder import find_station
from .local_files import is_local_video_id
from .playlist_plan import PlannedTrack, SongCandidate
from .radio import (
    RadioError,
    RadioNowPlaying,
    RadioStation,
    add_station,
    is_radio_video_id,
    now_playing,
    probe_stream,
    station_for,
)
from .resolver import Resolver
from .stores import FavoritesStore
from .ytm_client import YTMClient, YTMClientError

RADIO_POLL_SECONDS = 20.0
NO_TRACK_INFO_MESSAGE = "No radio track info yet; try again in a moment."
LOGIN_FIRST_MESSAGE = "Log in first: radio favorites are liked on YouTube Music."

# "add radio station WFMU", "add radiostation kexp", "add web radio FIP", ...
ADD_STATION_PATTERN = re.compile(
    r"^\s*(?:please\s+)?add\s+(?:the\s+)?(?:web\s+)?radio(?:\s*stations?)?\s+(.+?)\s*[.!]*\s*$",
    re.IGNORECASE,
)


def parse_add_station_request(text: str) -> str | None:
    """The station named in an 'add radio station ...' request, else None."""
    match = ADD_STATION_PATTERN.match(text or "")
    return match.group(1).strip() if match else None


def _has_login() -> bool:
    paths = get_paths()
    return paths.oauth_token.exists() or paths.browser_auth.exists()


class RadioActions:
    """Mixin for BesterYTMApp: live station track polling and f-on-radio likes."""

    radio_now_playing: RadioNowPlaying | None = None
    _radio_poll_video_id: str | None = None
    _radio_poll_due: float = 0.0
    _radio_poll_running: bool = False
    _radio_poll_failed: bool = False

    def _maybe_poll_radio(self, status) -> None:
        """Called from the refresh tick; fetches the live station's track periodically."""
        video_id = status.current_video_id if status.running else None
        if not video_id or not is_radio_video_id(video_id):
            self.radio_now_playing = None
            self._radio_poll_video_id = None
            return
        if video_id != self._radio_poll_video_id:
            self.radio_now_playing = None
            self._radio_poll_video_id = video_id
            self._radio_poll_due = 0.0
            self._radio_poll_failed = False
        if self._radio_poll_running or time.monotonic() < self._radio_poll_due:
            return
        self._radio_poll_running = True
        self.run_worker(
            partial(self._radio_poll_worker, video_id),
            name="radio-poll",
            group="radio-poll",
            thread=True,
        )

    def _radio_poll_worker(self, video_id: str) -> None:
        try:
            info = now_playing(station_for(video_id))
        except Exception as exc:  # network/parse failure: keep the station label
            self.call_from_thread(self._finish_radio_poll, video_id, None, str(exc))
            return
        self.call_from_thread(self._finish_radio_poll, video_id, info, None)

    def _finish_radio_poll(
        self, video_id: str, info: RadioNowPlaying | None, error: str | None
    ) -> None:
        self._radio_poll_running = False
        if video_id != self._radio_poll_video_id:
            # Stale fetch: the station changed; do not delay its first poll.
            return
        self._radio_poll_due = time.monotonic() + RADIO_POLL_SECONDS
        if info is None:
            if not self._radio_poll_failed:
                self._radio_poll_failed = True
                self._set_status(f"Radio track info unavailable: {error}")
            return
        self._radio_poll_failed = False
        if info != self.radio_now_playing:
            self.radio_now_playing = info
            self._update_track_label(f"{info.station} · {info.display}")

    def _favorite_radio_song(self) -> None:
        """f while radio plays: like the current song on YTM and fav it locally."""
        info = self.radio_now_playing
        if info is None or not (info.song or info.artist):
            self._set_status(NO_TRACK_INFO_MESSAGE)
            return
        if not _has_login():
            self._set_status(LOGIN_FIRST_MESSAGE)
            return
        query = " ".join(part for part in (info.artist, info.song) if part)
        self._set_status(f"Looking up {query!r} on YouTube Music...")
        self.run_worker(
            partial(self._radio_favorite_worker, info),
            name="radio-fav",
            group="radio-fav",
            thread=True,
        )

    def _radio_favorite_worker(self, info: RadioNowPlaying) -> None:
        try:
            candidate = _resolve_radio_song(info)
            YTMClient(authenticated=True).rate_song(candidate.video_id, "LIKE")
        except (YTMClientError, RadioError, ConfigError) as exc:
            self.call_from_thread(self._set_status, str(exc))
            return
        self.call_from_thread(self._finish_radio_favorite, candidate)

    def _finish_radio_favorite(self, candidate: SongCandidate) -> None:
        note = ""
        try:
            store = FavoritesStore()
            if candidate.video_id not in store.ids():
                store.toggle(candidate)
        except ConfigError as exc:
            note = f" (local favorite not saved: {exc})"
        self.candidates_by_video_id[candidate.video_id] = candidate
        self._refresh_favorite_markers(candidate.video_id, True)
        self._set_status(f"Liked on YouTube Music: {candidate.display_name}.{note}")

    def _start_add_radio_station(self, request: str) -> None:
        """Builder briefs like 'add radio station WFMU': the AI finds the stream
        URL, the app verifies it plays, and config.toml gets the station."""
        try:
            provider = resolve_provider(self.intelligence_settings)
        except IntelligenceError as exc:
            self._set_status(str(exc))
            return
        self._set_status(f"Finding a stream for {request!r} via {provider}...")
        self.run_worker(
            partial(self._add_station_worker, request),
            name="radio-add",
            group="radio-add",
            thread=True,
        )

    def _add_station_worker(self, request: str) -> None:
        try:
            suggestion = find_station(self.intelligence_settings, request)
            probe_stream(suggestion.stream_url)
            station = add_station(
                suggestion.name, suggestion.stream_url, key=suggestion.key
            )
        except (IntelligenceError, RadioError, ConfigError) as exc:
            self.call_from_thread(
                self._set_status,
                f"Could not add {request!r}: {exc} "
                "(you can add it manually under [radio.stations] in config.toml)",
            )
            return
        self.call_from_thread(self._finish_add_station, station)

    def _finish_add_station(self, station: RadioStation) -> None:
        self._set_status(
            f"Added radio station {station.name} ({station.stream_url}); "
            "type radio: to play it."
        )

    def _sync_ytm_like(self, video_id: str, faved: bool) -> None:
        """Mirror a local fav/unfav to a YTM like, best-effort, when logged in."""
        if is_radio_video_id(video_id) or is_local_video_id(video_id):
            return
        if not _has_login():
            return
        self.run_worker(
            partial(self._ytm_like_worker, video_id, "LIKE" if faved else "INDIFFERENT"),
            name="ytm-like",
            group="ytm-like",
            thread=True,
        )

    def _ytm_like_worker(self, video_id: str, rating: str) -> None:
        try:
            YTMClient(authenticated=True).rate_song(video_id, rating)
        except YTMClientError as exc:
            self.call_from_thread(self._set_status, f"YTM like not synced: {exc}")


def _resolve_radio_song(info: RadioNowPlaying) -> SongCandidate:
    """The most confident YTM match for a radio track, or a YTMClientError."""
    query = " ".join(part for part in (info.artist, info.song) if part)
    candidates = YTMClient(authenticated=False).search_songs(query, limit=5)
    target = PlannedTrack(
        artist=info.artist or info.station,
        title=info.song or query,
        reason="radio favorite",
        query=query,
    )
    best = Resolver().select_best(target, candidates)
    if best is None:
        raise YTMClientError(f"No confident YouTube Music match for {query!r}.")
    return best.candidate
