from __future__ import annotations

import time
from typing import Any

import requests
from pydantic import BaseModel, Field

from .config import ConfigError, get_paths, load_oauth_client, require_private_file
from .playlist_plan import SongCandidate
from .search_query import ParsedSearch, SearchItem, search_item_from_song

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
VALID_PRIVACY = {"PRIVATE", "UNLISTED", "PUBLIC"}


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


class YTMClient:
    def __init__(self, authenticated: bool = True) -> None:
        self.paths = get_paths()
        self.authenticated = authenticated
        self._ytmusic: Any | None = None
        self._backend: str | None = None

    @property
    def ytmusic(self) -> Any:
        if self._ytmusic is None:
            self._ytmusic = self._new_ytmusic()
        return self._ytmusic

    @property
    def backend(self) -> str | None:
        if self._backend is None:
            _ = self.ytmusic
        return self._backend

    @property
    def has_oauth_token(self) -> bool:
        return self.authenticated and self.paths.oauth_token.exists()

    def _new_ytmusic(self) -> Any:
        try:
            from ytmusicapi import OAuthCredentials, YTMusic
        except ImportError as exc:
            raise YTMClientError("ytmusicapi is not installed") from exc

        if self.authenticated:
            if self.paths.oauth_token.exists():
                require_private_file(self.paths.oauth_token)
                client_id, client_secret = load_oauth_client(self.paths.oauth_client)
                self._backend = "oauth"
                return YTMusic(
                    str(self.paths.oauth_token),
                    oauth_credentials=OAuthCredentials(
                        client_id=client_id,
                        client_secret=client_secret,
                    ),
                )
            if self.paths.browser_auth.exists():
                require_private_file(self.paths.browser_auth)
                self._backend = "browser"
                return YTMusic(str(self.paths.browser_auth))
            raise ConfigError(
                "No YouTube Music auth file found. Run `bester-ytm auth login`."
            )

        self._backend = "unauthenticated"
        return YTMusic()

    def auth_status(self) -> AuthStatus:
        if self.has_oauth_token:
            try:
                channel_payload = self._youtube_data_request(
                    "GET",
                    "channels",
                    params={"part": "id,snippet", "mine": "true", "maxResults": 1},
                )
                playlist_payload = self._youtube_data_request(
                    "GET",
                    "playlists",
                    params={"part": "snippet", "mine": "true", "maxResults": 1},
                )
            except Exception as exc:
                return AuthStatus(
                    authenticated=False,
                    backend=self.backend,
                    message=f"Authenticated YouTube Data API request failed: {exc}",
                )
            channels = channel_payload.get("items", [])
            channel_title = None
            if channels:
                snippet = channels[0].get("snippet", {})
                channel_title = snippet.get("title")
            sample_playlists = [
                str(item.get("snippet", {}).get("title"))
                for item in playlist_payload.get("items", [])
                if item.get("snippet", {}).get("title")
            ]
            message = "Authenticated YouTube Data API request succeeded."
            if channel_title:
                message += f" Channel: {channel_title}."
            return AuthStatus(
                authenticated=True,
                backend=self.backend,
                message=message,
                library_playlists_seen=len(playlist_payload.get("items", [])),
                sample_playlists=sample_playlists,
            )

        try:
            playlists = self.ytmusic.get_library_playlists(limit=1)
        except Exception as exc:  # ytmusicapi raises multiple request/auth types
            return AuthStatus(
                authenticated=False,
                backend=self.backend,
                message=f"Authenticated library request failed: {exc}",
            )
        names = [
            str(item.get("title"))
            for item in playlists
            if isinstance(item, dict) and item.get("title")
        ]
        return AuthStatus(
            authenticated=True,
            backend=self.backend,
            message="Authenticated YouTube Music library request succeeded.",
            library_playlists_seen=len(playlists),
            sample_playlists=names,
        )

    def _oauth_access_token(self) -> str:
        _ = self.ytmusic
        token = getattr(self._ytmusic, "_token", None)
        access_token = getattr(token, "access_token", None)
        if not access_token:
            raise YTMClientError("OAuth token is missing an access token")
        return str(access_token)

    def _youtube_data_request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.has_oauth_token:
            raise ConfigError("YouTube Data API requests require OAuth login.")
        token = self._oauth_access_token()
        url = f"{YOUTUBE_API_BASE}/{endpoint}"
        try:
            response = requests.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise YTMClientError(f"YouTube Data API request failed: {exc}") from exc
        if response.ok:
            if not response.content:
                return {}
            payload = response.json()
            return payload if isinstance(payload, dict) else {}

        message = f"{response.status_code} {response.reason}"
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        if isinstance(error, dict):
            detail = error.get("message")
            if detail:
                message = f"{message}: {detail}"
        raise YTMClientError(
            f"YouTube Data API returned {message}",
            status_code=response.status_code,
        )

    def _youtube_playlist_items(self, playlist_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "part": "snippet",
                "playlistId": playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            for attempt in range(5):
                try:
                    payload = self._youtube_data_request(
                        "GET",
                        "playlistItems",
                        params=params,
                    )
                    break
                except YTMClientError as exc:
                    if attempt < 4 and exc.status_code == 404:
                        time.sleep(1)
                        continue
                    raise
            items.extend(item for item in payload.get("items", []) if isinstance(item, dict))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return items

    def _playlist_contains_video(self, playlist_id: str, video_id: str) -> bool:
        return video_id in set(self.get_playlist(playlist_id).video_ids)

    def search_songs(self, query: str, limit: int = 5) -> list[SongCandidate]:
        try:
            try:
                raw_results = self.ytmusic.search(query, filter="songs", limit=limit)
            except Exception:
                raw_results = self.ytmusic.search(query, limit=limit)
            if not raw_results:
                raw_results = self.ytmusic.search(query, limit=limit)
        except Exception as exc:
            raise YTMClientError(f"YouTube Music search failed for {query!r}: {exc}") from exc
        candidates: list[SongCandidate] = []
        for raw in raw_results:
            if isinstance(raw, dict):
                candidate = normalize_song(raw, source="search")
                if candidate:
                    candidates.append(candidate)
        return candidates[:limit]

    def search_song_items(self, query: str, limit: int = 20) -> list[SearchItem]:
        return [
            search_item_from_song(candidate, source="song")
            for candidate in self.search_songs(query, limit=limit)
            if query.casefold() in candidate.title.casefold()
        ][:limit]

    def search_albums(self, query: str, limit: int = 20) -> list[SearchItem]:
        try:
            raw_results = self.ytmusic.search(query, filter="albums", limit=limit)
        except Exception as exc:
            raise YTMClientError(f"YouTube Music album search failed for {query!r}: {exc}") from exc
        return [
            item
            for raw in raw_results
            if isinstance(raw, dict)
            if (item := normalize_album(raw, source="album-search"))
        ][:limit]

    def search_community_playlists(self, query: str, limit: int = 20) -> list[SearchItem]:
        try:
            raw_results = self.ytmusic.search(
                query,
                filter="community_playlists",
                limit=limit,
            )
        except Exception as exc:
            raise YTMClientError(
                f"YouTube Music community playlist search failed for {query!r}: {exc}"
            ) from exc
        return [
            item
            for raw in raw_results
            if isinstance(raw, dict)
            if (item := normalize_playlist_result(raw, source="community"))
        ][:limit]

    def _first_artist(self, query: str) -> dict[str, Any]:
        try:
            raw_results = self.ytmusic.search(query, filter="artists", limit=8)
        except Exception as exc:
            raise YTMClientError(
                f"YouTube Music artist search failed for {query!r}: {exc}"
            ) from exc
        artists = [raw for raw in raw_results if isinstance(raw, dict) and raw.get("browseId")]
        if not artists:
            raise YTMClientError(f"No artist found for {query!r}")
        exact = [
            raw
            for raw in artists
            if str(raw.get("artist") or raw.get("title") or "").casefold() == query.casefold()
        ]
        return exact[0] if exact else artists[0]

    def _artist_payload(self, query: str) -> dict[str, Any]:
        artist = self._first_artist(query)
        try:
            payload = self.ytmusic.get_artist(str(artist["browseId"]))
        except Exception as exc:
            raise YTMClientError(
                f"YouTube Music artist lookup failed for {query!r}: {exc}"
            ) from exc
        return payload if isinstance(payload, dict) else {}

    def _artist_releases(
        self,
        artist_payload: dict[str, Any],
        release_key: str,
        limit: int | None = 100,
    ) -> list[dict[str, Any]]:
        release_group = artist_payload.get(release_key)
        if not isinstance(release_group, dict):
            return []
        results = [
            raw for raw in release_group.get("results", []) if isinstance(raw, dict)
        ]
        browse_id = release_group.get("browseId")
        params = release_group.get("params")
        if browse_id and params:
            try:
                full_results = self.ytmusic.get_artist_albums(
                    str(browse_id),
                    str(params),
                    limit=limit,
                )
                if full_results:
                    results = [raw for raw in full_results if isinstance(raw, dict)]
            except Exception:
                pass
        return results

    def search_artist_albums(
        self,
        artist_query: str,
        *,
        year: int | None = None,
        limit: int = 50,
    ) -> list[SearchItem]:
        artist = self._artist_payload(artist_query)
        releases = self._artist_releases(artist, "albums", limit=limit)
        items = [
            item
            for raw in releases
            if (item := normalize_album(raw, source=f"artist:{artist_query}"))
        ]
        if year is not None:
            items = [item for item in items if item.year == str(year)]
        return items[:limit]

    def search_artist_songs(
        self,
        artist_query: str,
        *,
        year: int | None = None,
        limit: int = 50,
    ) -> list[SearchItem]:
        artist = self._artist_payload(artist_query)
        if year is not None:
            releases = [
                *self._artist_releases(artist, "albums", limit=100),
                *self._artist_releases(artist, "singles", limit=100),
            ]
            songs: list[SearchItem] = []
            for release in releases:
                if str(release.get("year") or "") != str(year):
                    continue
                browse_id = release.get("browseId")
                if not browse_id:
                    continue
                try:
                    album = self.get_album(str(browse_id))
                except YTMClientError:
                    continue
                songs.extend(
                    search_item_from_song(track, source=f"artist-year:{year}")
                    for track in album.tracks
                )
                if len(songs) >= limit:
                    break
            return songs[:limit]

        song_group = artist.get("songs")
        results = []
        if isinstance(song_group, dict):
            results = [raw for raw in song_group.get("results", []) if isinstance(raw, dict)]
        return [
            search_item_from_song(candidate, source=f"artist:{artist_query}")
            for raw in results
            if (candidate := normalize_song(raw, source=f"artist:{artist_query}"))
        ][:limit]

    def structured_search(self, parsed: ParsedSearch, limit: int = 20) -> list[SearchItem]:
        if parsed.kind == "playlist":
            if not parsed.text:
                return []
            return self.search_community_playlists(parsed.text, limit=limit)
        if parsed.kind == "artist":
            if parsed.view == "albums":
                return self.search_artist_albums(parsed.text, year=parsed.year, limit=limit)
            return self.search_artist_songs(parsed.text, year=parsed.year, limit=limit)
        if parsed.kind == "song":
            return self.search_song_items(parsed.text, limit=limit)
        return [
            search_item_from_song(candidate, source="free")
            for candidate in self.search_songs(parsed.text, limit=limit)
        ]

    def get_related_candidates(self, video_id: str, limit: int = 10) -> list[SongCandidate]:
        try:
            raw = self.ytmusic.get_watch_playlist(videoId=video_id, limit=limit)
        except Exception as exc:
            raise YTMClientError(
                f"YouTube Music related lookup failed for {video_id}: {exc}"
            ) from exc
        tracks = raw.get("tracks", []) if isinstance(raw, dict) else []
        candidates: list[SongCandidate] = []
        for track in tracks:
            if isinstance(track, dict):
                candidate = normalize_song(track, source=f"related:{video_id}")
                if candidate and candidate.video_id != video_id:
                    candidates.append(candidate)
        return candidates[:limit]

    def get_playlist(self, playlist_id: str) -> PlaylistSnapshot:
        if self.has_oauth_token:
            playlist_payload = self._youtube_data_request(
                "GET",
                "playlists",
                params={"part": "snippet", "id": playlist_id, "maxResults": 1},
            )
            title = None
            playlist_items = playlist_payload.get("items", [])
            if playlist_items:
                title = playlist_items[0].get("snippet", {}).get("title")
            item_payloads = self._youtube_playlist_items(playlist_id)
            tracks = [
                candidate
                for item in item_payloads
                if (candidate := playlist_item_to_candidate(item, playlist_id))
            ]
            return PlaylistSnapshot(
                playlist_id=playlist_id,
                title=title,
                track_count=len(tracks),
                video_ids=[track.video_id for track in tracks],
                tracks=tracks,
            )

        try:
            raw = self.ytmusic.get_playlist(playlist_id, limit=None)
        except Exception as exc:
            raise YTMClientError(f"Could not fetch playlist {playlist_id}: {exc}") from exc
        tracks = raw.get("tracks", []) if isinstance(raw, dict) else []
        candidates = [
            candidate
            for track in tracks
            if isinstance(track, dict)
            if (candidate := normalize_song(track, source=f"playlist:{playlist_id}"))
        ]
        return PlaylistSnapshot(
            playlist_id=playlist_id,
            title=raw.get("title") if isinstance(raw, dict) else None,
            track_count=len(candidates),
            video_ids=[candidate.video_id for candidate in candidates],
            tracks=candidates,
        )

    def get_album(self, browse_id: str) -> PlaylistSnapshot:
        try:
            raw = self.ytmusic.get_album(browse_id)
        except Exception as exc:
            raise YTMClientError(f"Could not fetch album {browse_id}: {exc}") from exc
        tracks = raw.get("tracks", []) if isinstance(raw, dict) else []
        title = raw.get("title") if isinstance(raw, dict) else browse_id
        year = raw.get("year") if isinstance(raw, dict) else None
        candidates = [
            candidate
            for track in tracks
            if isinstance(track, dict)
            if (candidate := normalize_song(track, source=f"album:{browse_id}"))
        ]
        for candidate in candidates:
            candidate.album = candidate.album or str(title)
            candidate.year = candidate.year or (str(year) if year else None)
        return PlaylistSnapshot(
            playlist_id=(
                str(raw.get("audioPlaylistId") or browse_id) if isinstance(raw, dict) else browse_id
            ),
            title=str(title or "Untitled album"),
            track_count=len(candidates),
            video_ids=[candidate.video_id for candidate in candidates],
            tracks=candidates,
        )

    def list_playlists(self, limit: int = 20) -> list[PlaylistSnapshot]:
        if limit <= 0:
            return []

        if self.has_oauth_token:
            playlists: list[PlaylistSnapshot] = []
            page_token: str | None = None
            while len(playlists) < limit:
                params: dict[str, Any] = {
                    "part": "snippet,contentDetails",
                    "mine": "true",
                    "maxResults": min(50, limit - len(playlists)),
                }
                if page_token:
                    params["pageToken"] = page_token
                payload = self._youtube_data_request("GET", "playlists", params=params)
                for item in payload.get("items", []):
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    snippet = item.get("snippet", {})
                    content_details = item.get("contentDetails", {})
                    playlists.append(
                        PlaylistSnapshot(
                            playlist_id=str(item["id"]),
                            title=str(snippet.get("title") or "Untitled playlist"),
                            track_count=int(content_details.get("itemCount") or 0),
                        )
                    )
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
            return playlists[:limit]

        try:
            raw_playlists = self.ytmusic.get_library_playlists(limit=limit)
        except Exception as exc:
            raise YTMClientError(f"Could not list playlists: {exc}") from exc
        playlists = []
        for raw in raw_playlists:
            if not isinstance(raw, dict):
                continue
            playlist_id = raw.get("playlistId") or raw.get("playlist_id") or raw.get("browseId")
            if not playlist_id:
                continue
            track_count = raw.get("count") or raw.get("track_count") or 0
            try:
                parsed_track_count = int(track_count)
            except (TypeError, ValueError):
                parsed_track_count = 0
            playlists.append(
                PlaylistSnapshot(
                    playlist_id=str(playlist_id),
                    title=str(raw.get("title") or "Untitled playlist"),
                    track_count=parsed_track_count,
                )
            )
        return playlists[:limit]

    def create_playlist(
        self,
        title: str,
        description: str,
        privacy: str,
        video_ids: list[str],
    ) -> str:
        normalized_privacy = privacy.upper()
        if normalized_privacy not in VALID_PRIVACY:
            raise YTMClientError(
                "Privacy must be one of PRIVATE, UNLISTED, or PUBLIC."
            )
        if self.has_oauth_token:
            playlist_payload = self._youtube_data_request(
                "POST",
                "playlists",
                params={"part": "snippet,status"},
                json_body={
                    "snippet": {"title": title, "description": description},
                    "status": {"privacyStatus": normalized_privacy.lower()},
                },
            )
            playlist_id = playlist_payload.get("id")
            if not playlist_id:
                raise YTMClientError("YouTube Data API did not return a playlist id")
            if video_ids:
                self.add_playlist_items(str(playlist_id), video_ids)
            return str(playlist_id)

        try:
            playlist_id = self.ytmusic.create_playlist(
                title,
                description,
                privacy_status=normalized_privacy,
                video_ids=video_ids,
            )
        except Exception as exc:
            raise YTMClientError(f"Could not create playlist {title!r}: {exc}") from exc
        if isinstance(playlist_id, dict):
            playlist_id = playlist_id.get("playlistId") or playlist_id.get("id")
        if not playlist_id:
            raise YTMClientError("YouTube Music did not return a playlist id")
        return str(playlist_id)

    def delete_playlist(self, playlist_id: str) -> None:
        """Permanently delete a playlist from the user's YouTube account."""
        if self.has_oauth_token:
            self._youtube_data_request(
                "DELETE", "playlists", params={"id": playlist_id}
            )
            return
        try:
            self.ytmusic.delete_playlist(playlist_id)
        except Exception as exc:
            raise YTMClientError(
                f"Could not delete playlist {playlist_id!r}: {exc}"
            ) from exc

    def remove_playlist_item(self, playlist_id: str, video_id: str) -> int:
        """Remove every occurrence of a video from a playlist; returns the count removed."""
        if self.has_oauth_token:
            item_ids = [
                str(item["id"])
                for item in self._youtube_playlist_items(playlist_id)
                if item.get("id")
                and (candidate := playlist_item_to_candidate(item, playlist_id))
                and candidate.video_id == video_id
            ]
            for item_id in item_ids:
                self._youtube_data_request(
                    "DELETE", "playlistItems", params={"id": item_id}
                )
            return len(item_ids)

        try:
            raw = self.ytmusic.get_playlist(playlist_id, limit=None)
        except Exception as exc:
            raise YTMClientError(f"Could not fetch playlist {playlist_id}: {exc}") from exc
        tracks = raw.get("tracks", []) if isinstance(raw, dict) else []
        targets = [
            {"videoId": video_id, "setVideoId": str(track["setVideoId"])}
            for track in tracks
            if isinstance(track, dict)
            and track.get("videoId") == video_id
            and track.get("setVideoId")
        ]
        if not targets:
            return 0
        try:
            self.ytmusic.remove_playlist_items(playlist_id, targets)
        except Exception as exc:
            raise YTMClientError(
                f"Could not remove track from playlist {playlist_id}: {exc}"
            ) from exc
        return len(targets)

    def add_playlist_items(self, playlist_id: str, video_ids: list[str]) -> AddResult:
        if not video_ids:
            return AddResult(playlist_id=playlist_id, requested=0, added=0)
        before = self.get_playlist(playlist_id)
        existing = set(before.video_ids)
        missing = [
            video_id
            for video_id in dict.fromkeys(video_ids)
            if video_id not in existing
        ]
        if self.has_oauth_token:
            for video_id in missing:
                for attempt in range(5):
                    try:
                        self._youtube_data_request(
                            "POST",
                            "playlistItems",
                            params={"part": "snippet"},
                            json_body={
                                "snippet": {
                                    "playlistId": playlist_id,
                                    "resourceId": {
                                        "kind": "youtube#video",
                                        "videoId": video_id,
                                    },
                                }
                            },
                        )
                        break
                    except YTMClientError as exc:
                        if exc.status_code == 409:
                            # This avoids duplicate retries when a 409 response still landed.
                            # YouTube can lag on read-after-write visibility, so final
                            # verification remains the source of truth.
                            try:
                                landed = self._playlist_contains_video(playlist_id, video_id)
                            except YTMClientError:
                                landed = False
                            if landed:
                                break
                            if attempt >= 4:
                                raise YTMClientError(
                                    f"Could not add {video_id} to playlist {playlist_id}: {exc}"
                                ) from exc
                            time.sleep(1)
                            continue
                        try:
                            landed = self._playlist_contains_video(playlist_id, video_id)
                        except YTMClientError:
                            landed = False
                        if landed:
                            break
                        raise YTMClientError(
                            f"Could not add {video_id} to playlist {playlist_id}: {exc}"
                        ) from exc
            after = self.get_playlist(playlist_id)
            added = len(set(after.video_ids) - existing)
            return AddResult(
                playlist_id=playlist_id,
                requested=len(video_ids),
                added=added,
                duplicate_or_existing=len(video_ids) - len(missing),
                raw_status="added through YouTube Data API",
            )

        if missing:
            try:
                raw = self.ytmusic.add_playlist_items(playlist_id, missing)
            except Exception as exc:
                raise YTMClientError(
                    f"Could not add tracks to playlist {playlist_id}: {exc}"
                ) from exc
            raw_status = str(raw)[:160]
        else:
            raw_status = "all requested tracks already present"
        after = self.get_playlist(playlist_id)
        added = len(set(after.video_ids) - existing)
        return AddResult(
            playlist_id=playlist_id,
            requested=len(video_ids),
            added=added,
            duplicate_or_existing=len(video_ids) - len(missing),
            raw_status=raw_status,
        )
