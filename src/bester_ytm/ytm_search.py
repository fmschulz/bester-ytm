"""Search, browse, and metadata lookups against YouTube Music."""

from __future__ import annotations

from typing import Any

from .playlist_plan import SongCandidate
from .search_query import ParsedSearch, SearchItem, search_item_from_song
from .ytm_models import (
    PlaylistSnapshot,
    YTMClientError,
    normalize_album,
    normalize_playlist_result,
    normalize_song,
)
from .ytm_session import YTMSessionBase


class YTMSearchMixin(YTMSessionBase):
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
        if parsed.kind == "album":
            items = self.search_albums(parsed.text, limit=limit)
            if parsed.year is not None:
                items = [item for item in items if item.year == str(parsed.year)]
            return items
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
