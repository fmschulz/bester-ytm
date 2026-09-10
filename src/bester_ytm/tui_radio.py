"""Radio now-playing polling, radio-song favoriting, and AI station adding."""

from __future__ import annotations

import re
import time
from functools import partial

from .config import ConfigError
from .intelligence.llm import IntelligenceError, resolve_provider
from .intelligence.station_finder import find_station
from .playback import PlaybackError
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

# "add radio station WFMU", "add radiostation kexp", "add web radio FIP", ...
ADD_STATION_PATTERN = re.compile(
    r"^\s*(?:please\s+)?add\s+(?:the\s+)?(?:web\s+)?radio(?:\s*stations?)?\s+(.+?)\s*[.!]*\s*$",
    re.IGNORECASE,
)


def parse_add_station_request(text: str) -> str | None:
    """The station named in an 'add radio station ...' request, else None."""
    match = ADD_STATION_PATTERN.match(text or "")
    return match.group(1).strip() if match else None


class RadioActions:
    """Mixin for BesterYTMApp: live station track polling and local radio-song favorites."""

    current_candidate: SongCandidate | None
    playlist_video_ids: list[str]
    playlist_title: str
    active_local_playlist_id: str | None
    active_youtube_playlist_id: str | None
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
        """Resolve the current radio song and save it to local favorites."""
        info = self.radio_now_playing
        if info is None or not (info.song or info.artist):
            self._set_status(NO_TRACK_INFO_MESSAGE)
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
        except (YTMClientError, RadioError, ConfigError) as exc:
            self.call_from_thread(self._set_status, str(exc))
            return
        self.call_from_thread(self._finish_radio_favorite, candidate)

    def _finish_radio_favorite(self, candidate: SongCandidate) -> None:
        try:
            store = FavoritesStore()
            faved = store.toggle(candidate)
        except ConfigError as exc:
            self._set_status(str(exc))
            return
        self.candidates_by_video_id[candidate.video_id] = candidate
        self._refresh_favorite_markers(candidate.video_id, faved)
        self._set_status(
            f"Favorited {candidate.display_name}."
            if faved
            else f"Removed {candidate.display_name} from favorites."
        )

    def _drop_queued_radio(self, video_ids: list[str]) -> list[str]:
        """A radio station may appear once in the queue: drop ids that are
        already playing, already queued or listed, or repeated in this batch."""
        present = {
            self.playback.current_video_id,
            *self.playback.queue,
            *(self.playlist_video_ids or []),
        }
        kept: list[str] = []
        for video_id in video_ids:
            if is_radio_video_id(video_id):
                if video_id in present:
                    continue
                present.add(video_id)
            kept.append(video_id)
        return kept

    async def _tune_radio(self, candidate: SongCandidate) -> None:
        """Enter on a station tunes to it: the current track or station stops
        with a hard cut and the station becomes the queue's only entry."""
        self.candidates_by_video_id[candidate.video_id] = candidate
        status = self.playback.status()
        if status.running and status.current_video_id == candidate.video_id:
            self._set_status(f"{candidate.title} is already playing.")
            return
        self._supersede_queue_load()
        try:
            self.playback.replace_queue([candidate.video_id])
            status = self.playback.play_queue()
            self.playback_was_active = True
        except PlaybackError as exc:
            await self._report_playback_error(exc)
            return
        self.playlist_video_ids = [candidate.video_id]
        self.playlist_title = candidate.title
        self.active_local_playlist_id = None
        self.active_youtube_playlist_id = None
        self.current_candidate = candidate
        self._update_track_label(candidate.title)
        await self._render_queue()
        self._refresh_playback(status)
        self._set_status(f"Tuned to {candidate.title}.")

    def _radio_track_seed(self, video_id: str) -> SongCandidate | None:
        """The playing station's live track as a similar-songs seed; a station
        name itself is not a musical seed."""
        info = self.radio_now_playing
        if video_id != self.playback.current_video_id or info is None:
            return None
        if not (info.artist or info.song):
            return None
        return SongCandidate(
            video_id=video_id,
            title=info.song or info.display,
            artists=[info.artist] if info.artist else [],
            source="radio",
        )

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
