"""Web radio stations as playable queue entries (video_id = "radio:<key>").

ByteFM and KALX ship built in with their rich now-playing sources (ported
from the user's radio-tui); more stations come from config.toml:

    [radio.stations]
    fip = "https://icecast.radiofrance.fr/fip-midfi.mp3"

Config stations read song names from standard ICY stream metadata.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.request
from typing import Any, Literal

from pydantic import BaseModel

from .playlist_plan import SongCandidate
from .search_query import SearchItem

RADIO_VIDEO_ID_PREFIX = "radio:"
USER_AGENT = "bester-ytm-radio/1.0"
FETCH_TIMEOUT_SECONDS = 8.0

BYTEFM_API = "https://www.byte.fm/api/v1/player/live/?client=player"
BYTEFM_STREAM = "https://bytefm.cast.addradio.de/bytefm/main/high/stream"
KALX_STREAM = "https://stream.kalx.berkeley.edu:8443/kalx-128.mp3"
KALX_NOW_PLAYING = "https://www.kalx.berkeley.edu/"

_SSL_CONTEXT = ssl.create_default_context()


class RadioError(RuntimeError):
    """Raised when a radio station is unknown or its metadata is unreadable."""


class RadioStation(BaseModel):
    key: str
    name: str
    stream_url: str
    kind: Literal["bytefm", "kalx", "icy"] = "icy"

    @property
    def video_id(self) -> str:
        return f"{RADIO_VIDEO_ID_PREFIX}{self.key}"


class RadioNowPlaying(BaseModel):
    station: str
    artist: str = ""
    song: str = ""
    show: str = ""
    host: str = ""

    @property
    def display(self) -> str:
        track = " - ".join(part for part in (self.artist, self.song) if part)
        if track and self.show:
            return f"{track} ({self.show})"
        return track or self.show or "Live radio"


BUILTIN_STATIONS = (
    RadioStation(key="bytefm", name="ByteFM", stream_url=BYTEFM_STREAM, kind="bytefm"),
    RadioStation(key="kalx", name="KALX 90.7FM", stream_url=KALX_STREAM, kind="kalx"),
)


def is_radio_video_id(video_id: str) -> bool:
    return video_id.startswith(RADIO_VIDEO_ID_PREFIX)


def stations() -> list[RadioStation]:
    """Built-in stations plus [radio.stations] entries from config.toml."""
    # Imported here: config -> transitions -> deck -> radio at module load.
    from .config import get_paths, load_config_document

    result = list(BUILTIN_STATIONS)
    known = {station.key for station in result}
    section = load_config_document(get_paths().config_file).get("radio", {})
    extras = section.get("stations", {}) if isinstance(section, dict) else {}
    if isinstance(extras, dict):
        for key, url in sorted(extras.items(), key=lambda item: str(item[0]).casefold()):
            slug = str(key).strip().casefold()
            if slug and slug not in known and isinstance(url, str) and url.strip():
                result.append(RadioStation(key=slug, name=str(key), stream_url=url.strip()))
    return result


def station_for(video_id: str) -> RadioStation:
    key = video_id[len(RADIO_VIDEO_ID_PREFIX) :]
    for station in stations():
        if station.key == key:
            return station
    raise RadioError(f"Unknown radio station: {key}")


def stream_url_for(video_id: str) -> str:
    return station_for(video_id).stream_url


def station_candidate(station: RadioStation) -> SongCandidate:
    return SongCandidate(
        video_id=station.video_id,
        title=station.name,
        album="web radio",
        source="radio",
    )


def station_search_items() -> list[SearchItem]:
    return [
        SearchItem(
            item_type="radio",
            title=station.name,
            source="radio",
            video_id=station.video_id,
            candidate=station_candidate(station),
        )
        for station in stations()
    ]


def add_station(name: str, stream_url: str, key: str = "") -> RadioStation:
    """Persist a station under [radio.stations] in config.toml; returns it.

    Rejects stations whose name or slug (key) matches an existing one, so an
    AI suggestion like key="kalx", name="KALX 90.7FM" cannot duplicate a
    built-in under a different display name.
    """
    # Imported here: config -> transitions -> deck -> radio at module load.
    from .config import get_paths, load_config_document, rewrite_config_sections

    display = name.strip()
    url = stream_url.strip()
    if not display or not url:
        raise RadioError("A station needs a name and a stream URL.")
    existing = stations()
    known = {station.key for station in existing}
    known |= {station.name.casefold() for station in existing}
    if {display.casefold(), key.strip().casefold()} & known:
        raise RadioError(f"{display!r} matches an existing station.")
    config_file = get_paths().config_file
    section = load_config_document(config_file).get("radio", {})
    extras = dict(section.get("stations", {})) if isinstance(section, dict) else {}
    extras[display] = url
    rewrite_config_sections({"radio": {"stations": extras}}, config_file)
    return RadioStation(key=display.casefold(), name=display, stream_url=url)


def probe_stream(stream_url: str) -> None:
    """Confirm the URL serves a DIRECT audio stream; raises RadioError otherwise."""
    path = stream_url.split("?", 1)[0].casefold()
    if path.endswith((".m3u", ".m3u8", ".pls", ".asx", ".xspf")):
        raise RadioError(f"{stream_url} is a playlist file, not a direct audio stream")
    try:
        with _open_url(stream_url, {"Icy-MetaData": "1"}) as response:
            content_type = str(response.headers.get("content-type") or "").casefold()
            # Playlist MIME types would pass the audio/ check but break playback
            # metadata; they signal the AI returned an indirection, not a stream.
            if "mpegurl" in content_type or "scpls" in content_type:
                raise RadioError(
                    f"{stream_url} serves a playlist ({content_type}), "
                    "not a direct audio stream"
                )
            is_audio = (
                content_type.startswith("audio/")
                or content_type.startswith("application/ogg")
                or "mpeg" in content_type
                or response.headers.get("icy-metaint") is not None
                or response.headers.get("icy-name") is not None
            )
            if not is_audio:
                raise RadioError(
                    f"{stream_url} answered with {content_type or 'no content type'}, "
                    "not an audio stream"
                )
            if not response.read(1024):
                raise RadioError(f"{stream_url} sent no audio data")
    except OSError as exc:
        raise RadioError(f"could not reach {stream_url}: {exc}") from exc


def _open_url(url: str, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(
        request, timeout=FETCH_TIMEOUT_SECONDS, context=_SSL_CONTEXT
    )


def _fetch_icy_title(stream_url: str) -> str:
    """One metadata block from an ICY stream; empty when the stream sends none."""
    with _open_url(stream_url, {"Icy-MetaData": "1"}) as response:
        metaint = response.headers.get("icy-metaint")
        if not metaint:
            return ""
        response.read(int(metaint))
        length_chunk = response.read(1)
        if not length_chunk:
            return ""
        metadata = response.read(length_chunk[0] * 16)
        match = re.search(rb"StreamTitle='([^']*)';", metadata)
        return match.group(1).decode("utf-8", "ignore").strip() if match else ""


def _split_track(track: str) -> tuple[str, str]:
    if " - " in track:
        artist, song = track.split(" - ", 1)
        return artist.strip(), song.strip()
    return "", track.strip()


def _strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def _fetch_bytefm(station: RadioStation) -> RadioNowPlaying:
    with _open_url(BYTEFM_API) as response:
        data = json.loads(response.read().decode("utf-8"))
    show_bits = [str(data.get("broadcast_title") or ""), str(data.get("show_subtitle") or "")]
    artist, song = _split_track(_fetch_icy_title(station.stream_url))
    return RadioNowPlaying(
        station=station.name,
        artist=artist,
        song=song,
        show=" / ".join(bit.strip() for bit in show_bits if bit.strip()),
        host=str(data.get("moderator") or "").strip(),
    )


def _fetch_kalx(station: RadioStation) -> RadioNowPlaying:
    """The newest entry of the KALX homepage playlist is the playing track."""
    with _open_url(KALX_NOW_PLAYING) as response:
        text = response.read().decode("utf-8", "ignore")
    artist_match = re.search(r'<p class="artist[^"]*">(.*?)</p>', text, re.S)
    song_match = re.search(r'<p class="song[^"]*">(.*?)</p>', text, re.S)
    # The song <p> nests a <span> holding "from <release>"; keep the song only.
    song_html = (song_match.group(1) if song_match else "").split("<span", 1)[0]
    return RadioNowPlaying(
        station=station.name,
        artist=_strip_tags(artist_match.group(1)) if artist_match else "",
        song=_strip_tags(song_html),
    )


def now_playing(station: RadioStation) -> RadioNowPlaying:
    """Fetch the station's current track; network-bound, call from a worker."""
    if station.kind == "bytefm":
        return _fetch_bytefm(station)
    if station.kind == "kalx":
        return _fetch_kalx(station)
    artist, song = _split_track(_fetch_icy_title(station.stream_url))
    return RadioNowPlaying(station=station.name, artist=artist, song=song)
