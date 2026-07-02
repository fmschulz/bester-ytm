"""Shared YouTube Music models and raw-payload normalizers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .playlist_plan import SongCandidate
from .search_query import SearchItem


class YTMClientError(RuntimeError):
    """Raised when YouTube Music requests fail."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthStatus(BaseModel):
    authenticated: bool
    backend: str | None = None
    message: str
    library_playlists_seen: int = 0
    sample_playlists: list[str] = Field(default_factory=list)


class PlaylistSnapshot(BaseModel):
    playlist_id: str
    title: str | None = None
    track_count: int = 0
    video_ids: list[str] = Field(default_factory=list)
    tracks: list[SongCandidate] = Field(default_factory=list)


class AddResult(BaseModel):
    playlist_id: str
    requested: int
    added: int
    duplicate_or_existing: int = 0
    raw_status: str | None = None


def _duration_to_seconds(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.split(":")
    try:
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return seconds
    except ValueError:
        return None


def _artist_names(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name")
            if name:
                names.append(str(name))
        elif item:
            names.append(str(item))
    return names


def normalize_song(raw: dict[str, Any], source: str = "ytmusic") -> SongCandidate | None:
    video_id = raw.get("videoId") or raw.get("video_id")
    if not video_id:
        return None
    album = raw.get("album")
    album_name = album.get("name") if isinstance(album, dict) else album
    return SongCandidate(
        video_id=str(video_id),
        title=str(raw.get("title") or raw.get("name") or "Unknown title"),
        artists=_artist_names(raw.get("artists") or raw.get("artist")),
        album=str(album_name) if album_name else None,
        year=str(raw.get("year")) if raw.get("year") else None,
        duration_seconds=_duration_to_seconds(raw.get("duration")),
        result_type=raw.get("resultType") or raw.get("category"),
        is_explicit=raw.get("isExplicit"),
        source=source,
    )


def normalize_album(raw: dict[str, Any], source: str = "search") -> SearchItem | None:
    browse_id = raw.get("browseId") or raw.get("browse_id")
    if not browse_id:
        return None
    artists = _artist_names(raw.get("artists") or raw.get("artist"))
    playlist_id = raw.get("playlistId") or raw.get("audioPlaylistId")
    return SearchItem(
        item_type="album",
        title=str(raw.get("title") or raw.get("name") or "Untitled album"),
        subtitle=", ".join(artists),
        source=source,
        browse_id=str(browse_id),
        playlist_id=str(playlist_id) if playlist_id else None,
        year=str(raw.get("year")) if raw.get("year") else None,
    )


def normalize_playlist_result(
    raw: dict[str, Any],
    source: str = "community",
) -> SearchItem | None:
    playlist_id = raw.get("playlistId") or raw.get("playlist_id") or raw.get("browseId")
    if not playlist_id:
        return None
    author = raw.get("author") or raw.get("owner") or raw.get("channelTitle")
    item_count = raw.get("itemCount") or raw.get("count") or raw.get("track_count")
    try:
        parsed_count = int(item_count) if item_count is not None else None
    except (TypeError, ValueError):
        parsed_count = None
    return SearchItem(
        item_type="playlist",
        title=str(raw.get("title") or "Untitled playlist"),
        subtitle=str(author) if author else "",
        source=source,
        playlist_id=str(playlist_id),
        track_count=parsed_count,
    )


def playlist_item_to_candidate(
    raw: dict[str, Any],
    playlist_id: str,
) -> SongCandidate | None:
    snippet = raw.get("snippet", {})
    if not isinstance(snippet, dict):
        return None
    resource_id = snippet.get("resourceId", {})
    if not isinstance(resource_id, dict) or not resource_id.get("videoId"):
        return None

    channel_title = snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle")
    artists = [str(channel_title)] if channel_title else []
    return SongCandidate(
        video_id=str(resource_id["videoId"]),
        title=str(snippet.get("title") or "Unknown title"),
        artists=artists,
        source=f"playlist:{playlist_id}",
    )
