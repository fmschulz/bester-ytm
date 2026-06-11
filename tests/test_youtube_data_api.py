from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bester_ytm.config import write_private_json
from bester_ytm.ytm_client import YTMClient


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: dict[str, Any] | None = None,
        reason: str = "OK",
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.reason = reason
        self.content = b"{}"
        self.ok = 200 <= status_code < 300

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture
def oauth_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> YTMClient:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config_dir = tmp_path / "config" / "bester-ytm"
    write_private_json(
        config_dir / "oauth-client.json",
        {"client_id": "client-id", "client_secret": "client-secret"},
    )
    write_private_json(
        config_dir / "oauth.json",
        {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": "https://www.googleapis.com/auth/youtube",
            "token_type": "Bearer",
            "expires_at": 4_102_444_800,
            "expires_in": 3600,
        },
    )
    client = YTMClient(authenticated=True)
    monkeypatch.setattr(client, "_oauth_access_token", lambda: "access-token")
    return client


def test_youtube_data_api_creates_adds_and_reads_playlist(
    oauth_client: YTMClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playlist_items: list[str] = []

    def fake_request(
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        assert headers == {"Authorization": "Bearer access-token"}
        assert timeout == 20
        endpoint = url.rsplit("/", 1)[-1]
        if method == "POST" and endpoint == "playlists":
            assert json == {
                "snippet": {"title": "Mix", "description": "Description"},
                "status": {"privacyStatus": "private"},
            }
            return FakeResponse(payload={"id": "PL1"})
        if method == "GET" and endpoint == "playlists":
            assert params and params["id"] == "PL1"
            return FakeResponse(
                payload={"items": [{"snippet": {"title": "Mix"}}]},
            )
        if method == "GET" and endpoint == "playlistItems":
            return FakeResponse(
                payload={
                    "items": [
                        {
                            "snippet": {
                                "title": f"Song {video_id}",
                                "videoOwnerChannelTitle": "Artist Channel",
                                "resourceId": {"kind": "youtube#video", "videoId": video_id},
                            }
                        }
                        for video_id in playlist_items
                    ]
                }
            )
        if method == "POST" and endpoint == "playlistItems":
            assert json is not None
            playlist_items.append(json["snippet"]["resourceId"]["videoId"])
            return FakeResponse(payload={"id": f"item-{len(playlist_items)}"})
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("bester_ytm.ytm_client.requests.request", fake_request)

    playlist_id = oauth_client.create_playlist("Mix", "Description", "PRIVATE", ["v1"])
    result = oauth_client.add_playlist_items(playlist_id, ["v1", "v2", "v2"])
    snapshot = oauth_client.get_playlist(playlist_id)

    assert playlist_id == "PL1"
    assert result.added == 1
    assert result.duplicate_or_existing == 2
    assert snapshot.video_ids == ["v1", "v2"]
    assert [track.display_name for track in snapshot.tracks] == [
        "Artist Channel - Song v1",
        "Artist Channel - Song v2",
    ]


def test_youtube_data_api_retries_transient_playlist_item_conflict(
    oauth_client: YTMClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_attempts = 0
    playlist_items: list[str] = []

    def fake_request(
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        nonlocal post_attempts
        endpoint = url.rsplit("/", 1)[-1]
        if method == "GET" and endpoint == "playlists":
            return FakeResponse(payload={"items": [{"snippet": {"title": "Mix"}}]})
        if method == "GET" and endpoint == "playlistItems":
            return FakeResponse(
                payload={
                    "items": [
                        {"snippet": {"resourceId": {"videoId": video_id}}}
                        for video_id in playlist_items
                    ]
                }
            )
        if method == "POST" and endpoint == "playlistItems":
            post_attempts += 1
            if post_attempts == 1:
                return FakeResponse(
                    status_code=409,
                    reason="Conflict",
                    payload={"error": {"message": "The operation was aborted."}},
                )
            assert json is not None
            playlist_items.append(json["snippet"]["resourceId"]["videoId"])
            return FakeResponse(payload={"id": "item-1"})
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("bester_ytm.ytm_client.requests.request", fake_request)
    monkeypatch.setattr("bester_ytm.ytm_client.time.sleep", lambda seconds: None)

    result = oauth_client.add_playlist_items("PL1", ["v1"])

    assert post_attempts == 2
    assert result.added == 1


def test_youtube_data_api_treats_conflict_as_success_when_item_lands(
    oauth_client: YTMClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_attempts = 0
    playlist_items: list[str] = []

    def fake_request(
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        nonlocal post_attempts
        endpoint = url.rsplit("/", 1)[-1]
        if method == "GET" and endpoint == "playlists":
            return FakeResponse(payload={"items": [{"snippet": {"title": "Mix"}}]})
        if method == "GET" and endpoint == "playlistItems":
            return FakeResponse(
                payload={
                    "items": [
                        {"snippet": {"resourceId": {"videoId": video_id}}}
                        for video_id in playlist_items
                    ]
                }
            )
        if method == "POST" and endpoint == "playlistItems":
            post_attempts += 1
            if post_attempts == 5:
                playlist_items.append("v1")
            return FakeResponse(
                status_code=409,
                reason="Conflict",
                payload={"error": {"message": "The operation was aborted."}},
            )
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("bester_ytm.ytm_client.requests.request", fake_request)
    monkeypatch.setattr("bester_ytm.ytm_client.time.sleep", lambda seconds: None)

    result = oauth_client.add_playlist_items("PL1", ["v1"])

    assert post_attempts == 5
    assert result.added == 1


def test_youtube_data_api_does_not_retry_conflict_that_landed(
    oauth_client: YTMClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_attempts = 0
    playlist_items: list[str] = []

    def fake_request(
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        nonlocal post_attempts
        endpoint = url.rsplit("/", 1)[-1]
        if method == "GET" and endpoint == "playlists":
            return FakeResponse(payload={"items": [{"snippet": {"title": "Mix"}}]})
        if method == "GET" and endpoint == "playlistItems":
            return FakeResponse(
                payload={
                    "items": [
                        {"snippet": {"resourceId": {"videoId": video_id}}}
                        for video_id in playlist_items
                    ]
                }
            )
        if method == "POST" and endpoint == "playlistItems":
            post_attempts += 1
            playlist_items.append("v1")
            return FakeResponse(
                status_code=409,
                reason="Conflict",
                payload={"error": {"message": "The operation was aborted."}},
            )
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("bester_ytm.ytm_client.requests.request", fake_request)
    monkeypatch.setattr("bester_ytm.ytm_client.time.sleep", lambda seconds: None)

    result = oauth_client.add_playlist_items("PL1", ["v1"])

    assert post_attempts == 1
    assert result.added == 1
    assert playlist_items == ["v1"]


def test_youtube_data_api_auth_status_success(
    oauth_client: YTMClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request(
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        endpoint = url.rsplit("/", 1)[-1]
        if method == "GET" and endpoint == "channels":
            return FakeResponse(
                payload={"items": [{"snippet": {"title": "Frederik Schulz"}}]}
            )
        if method == "GET" and endpoint == "playlists":
            return FakeResponse(payload={"items": [{"snippet": {"title": "Mix"}}]})
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("bester_ytm.ytm_client.requests.request", fake_request)

    status = oauth_client.auth_status()

    assert status.authenticated is True
    assert "Frederik Schulz" in status.message
    assert status.sample_playlists == ["Mix"]


def test_youtube_data_api_auth_status_failure(
    oauth_client: YTMClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request(
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        return FakeResponse(
            status_code=403,
            reason="Forbidden",
            payload={"error": {"message": "insufficient permissions"}},
        )

    monkeypatch.setattr("bester_ytm.ytm_client.requests.request", fake_request)

    status = oauth_client.auth_status()

    assert status.authenticated is False
    assert "insufficient permissions" in status.message
