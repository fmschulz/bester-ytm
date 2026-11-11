"""Playlist and library reads and mutations for YouTube Music."""

from __future__ import annotations

import time
from typing import Any

from .ytm_models import (
    AddResult,
    PlaylistSnapshot,
    YTMClientError,
    normalize_song,
    playlist_item_to_candidate,
)
from .ytm_session import YTMSessionBase

VALID_PRIVACY = {"PRIVATE", "UNLISTED", "PUBLIC"}


class YTMLibraryMixin(YTMSessionBase):
    def _playlist_contains_video(self, playlist_id: str, video_id: str) -> bool:
        return video_id in set(self.get_playlist(playlist_id).video_ids)

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
                self._add_video_with_retries(playlist_id, video_id)
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

    def _add_video_with_retries(self, playlist_id: str, video_id: str) -> None:
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
                return
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
                        return
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
                    return
                raise YTMClientError(
                    f"Could not add {video_id} to playlist {playlist_id}: {exc}"
                ) from exc
