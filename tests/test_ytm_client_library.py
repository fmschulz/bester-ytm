from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from bester_ytm.config import ConfigError, write_private_json
from bester_ytm.ytm_client import YTMClient, YTMClientError


def _client(fake: Any = None) -> YTMClient:
    client = YTMClient(authenticated=False)
    client._ytmusic = fake if fake is not None else object()
    client._backend = "fake"
    return client


@pytest.fixture
def oauth_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> YTMClient:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config_dir = tmp_path / "config" / "bester-ytm"
    write_private_json(config_dir / "oauth.json", {"access_token": "token"})
    client = YTMClient(authenticated=True)
    monkeypatch.setattr(client, "_oauth_access_token", lambda: "token")
    return client


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: Any = None,
        content: bytes = b"{}",
        reason: str = "OK",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.reason = reason
        self.ok = 200 <= status_code < 300

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_auth_status_reports_library_success() -> None:
    class Library:
        def get_library_playlists(self, limit: int):
            return [{"title": "Mix"}, "junk", {"untitled": True}]

    status = _client(Library()).auth_status()

    assert status.authenticated is True
    assert status.library_playlists_seen == 3
    assert status.sample_playlists == ["Mix"]


def test_auth_status_reports_library_failure() -> None:
    class Failing:
        def get_library_playlists(self, limit: int):
            raise RuntimeError("denied")

    status = _client(Failing()).auth_status()

    assert status.authenticated is False
    assert "denied" in status.message


def test_oauth_access_token_requires_token() -> None:
    client = _client(SimpleNamespace(_token=SimpleNamespace(access_token="tok")))
    assert client._oauth_access_token() == "tok"

    missing = _client(SimpleNamespace(_token=None))
    with pytest.raises(YTMClientError, match="missing an access token"):
        missing._oauth_access_token()


def test_youtube_data_request_requires_oauth() -> None:
    with pytest.raises(ConfigError, match="require OAuth login"):
        _client()._youtube_data_request("GET", "playlists")


def test_youtube_data_request_wraps_network_errors(
    oauth_client: YTMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_request(*args: Any, **kwargs: Any) -> FakeResponse:
        raise requests.RequestException("connection reset")

    monkeypatch.setattr("bester_ytm.ytm_client.requests.request", fail_request)

    with pytest.raises(YTMClientError, match="connection reset"):
        oauth_client._youtube_data_request("GET", "playlists")


def test_youtube_data_request_handles_empty_and_unparsable_bodies(
    oauth_client: YTMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = [
        FakeResponse(content=b""),
        FakeResponse(status_code=500, payload=ValueError("no json"), reason="Server Error"),
    ]
    monkeypatch.setattr(
        "bester_ytm.ytm_client.requests.request",
        lambda *args, **kwargs: responses.pop(0),
    )

    assert oauth_client._youtube_data_request("GET", "playlists") == {}
    with pytest.raises(YTMClientError, match="500 Server Error"):
        oauth_client._youtube_data_request("GET", "playlists")


def test_youtube_playlist_items_paginates_and_retries_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    sleeps: list[float] = []
    page_params: list[dict[str, Any]] = []
    responses: list[Any] = [
        YTMClientError("missing", status_code=404),
        {"items": [{"id": "i1"}], "nextPageToken": "t2"},
        {"items": [{"id": "i2"}, "junk"]},
    ]

    def fake_request(method: str, endpoint: str, *, params: dict[str, Any]) -> Any:
        page_params.append(dict(params))
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(client, "_youtube_data_request", fake_request)
    monkeypatch.setattr("bester_ytm.ytm_client.time.sleep", sleeps.append)

    items = client._youtube_playlist_items("PL1")

    assert [item["id"] for item in items] == ["i1", "i2"]
    assert sleeps == [1]
    assert page_params[2]["pageToken"] == "t2"


def test_get_playlist_without_oauth_normalizes_tracks() -> None:
    class Playlists:
        def get_playlist(self, playlist_id: str, limit: int | None):
            return {
                "title": "Mix",
                "tracks": [{"videoId": "v1", "title": "One"}, "junk", {"title": "no id"}],
            }

    snapshot = _client(Playlists()).get_playlist("PL1")

    assert snapshot.title == "Mix"
    assert snapshot.video_ids == ["v1"]
    assert snapshot.track_count == 1


def test_get_playlist_and_album_wrap_errors() -> None:
    class Failing:
        def get_playlist(self, playlist_id: str, limit: int | None):
            raise RuntimeError("offline")

        def get_album(self, browse_id: str):
            raise RuntimeError("offline")

    client = _client(Failing())
    with pytest.raises(YTMClientError, match="Could not fetch playlist PL1"):
        client.get_playlist("PL1")
    with pytest.raises(YTMClientError, match="Could not fetch album b1"):
        client.get_album("b1")


def test_list_playlists_without_oauth_skips_invalid_entries() -> None:
    class Library:
        def get_library_playlists(self, limit: int):
            return [
                {"playlistId": "PL1", "title": "Mix", "count": "5"},
                "junk",
                {"title": "no id"},
                {"browseId": "B2", "count": "many"},
            ]

    assert _client(Library()).list_playlists(limit=0) == []

    playlists = _client(Library()).list_playlists(limit=10)

    assert [(p.playlist_id, p.track_count) for p in playlists] == [("PL1", 5), ("B2", 0)]


def test_list_playlists_without_oauth_wraps_errors() -> None:
    class Failing:
        def get_library_playlists(self, limit: int):
            raise RuntimeError("offline")

    with pytest.raises(YTMClientError, match="Could not list playlists"):
        _client(Failing()).list_playlists()


def test_list_playlists_with_oauth_paginates(
    oauth_client: YTMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = [
        {
            "items": [
                {"id": "PL1", "snippet": {"title": "A"}, "contentDetails": {"itemCount": 2}},
                {"snippet": {"title": "missing id"}},
            ],
            "nextPageToken": "t2",
        },
        {"items": [{"id": "PL2", "snippet": {}, "contentDetails": {}}]},
    ]
    monkeypatch.setattr(
        oauth_client,
        "_youtube_data_request",
        lambda method, endpoint, params: responses.pop(0),
    )

    playlists = oauth_client.list_playlists(limit=3)

    assert [(p.playlist_id, p.title, p.track_count) for p in playlists] == [
        ("PL1", "A", 2),
        ("PL2", "Untitled playlist", 0),
    ]


def test_create_playlist_validates_privacy() -> None:
    with pytest.raises(YTMClientError, match="Privacy must be one of"):
        _client().create_playlist("Mix", "", "SECRET", [])


def test_create_playlist_without_oauth_handles_dict_and_failures() -> None:
    class Creator:
        def __init__(self, result: Any) -> None:
            self.result = result

        def create_playlist(self, title, description, privacy_status, video_ids):
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    created = _client(Creator({"playlistId": "PL9"})).create_playlist(
        "Mix", "", "private", ["v1"]
    )
    assert created == "PL9"

    with pytest.raises(YTMClientError, match="did not return a playlist id"):
        _client(Creator(None)).create_playlist("Mix", "", "PUBLIC", [])

    with pytest.raises(YTMClientError, match="Could not create playlist 'Mix'"):
        _client(Creator(RuntimeError("offline"))).create_playlist("Mix", "", "PUBLIC", [])


def test_create_playlist_with_oauth_requires_playlist_id(
    oauth_client: YTMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        oauth_client,
        "_youtube_data_request",
        lambda method, endpoint, *, params=None, json_body=None: {},
    )

    with pytest.raises(YTMClientError, match="did not return a playlist id"):
        oauth_client.create_playlist("Mix", "", "PRIVATE", [])


def test_delete_playlist_without_oauth_uses_ytmusic_and_wraps_errors() -> None:
    class Deleter:
        def __init__(self, error: Exception | None = None) -> None:
            self.error = error
            self.deleted: list[str] = []

        def delete_playlist(self, playlist_id: str) -> None:
            if self.error is not None:
                raise self.error
            self.deleted.append(playlist_id)

    deleter = Deleter()
    _client(deleter).delete_playlist("PL7")
    assert deleter.deleted == ["PL7"]

    with pytest.raises(YTMClientError, match="Could not delete playlist 'PL7'"):
        _client(Deleter(RuntimeError("offline"))).delete_playlist("PL7")


def test_delete_playlist_with_oauth_uses_data_api(
    oauth_client: YTMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_request(method, endpoint, *, params=None, json_body=None):
        calls.append((method, endpoint, params))
        return {}

    monkeypatch.setattr(oauth_client, "_youtube_data_request", fake_request)

    oauth_client.delete_playlist("PL7")

    assert calls == [("DELETE", "playlists", {"id": "PL7"})]


def test_remove_playlist_item_without_oauth_uses_set_video_ids() -> None:
    class Remover:
        def __init__(self) -> None:
            self.removed: list[tuple[str, list[dict[str, str]]]] = []

        def get_playlist(self, playlist_id: str, limit: int | None = None) -> dict[str, Any]:
            return {
                "tracks": [
                    {"videoId": "v1", "setVideoId": "s1"},
                    {"videoId": "v2", "setVideoId": "s2"},
                    {"videoId": "v1", "setVideoId": "s3"},
                    {"videoId": "v1"},
                ]
            }

        def remove_playlist_items(self, playlist_id: str, videos: list[dict[str, str]]) -> None:
            self.removed.append((playlist_id, videos))

    remover = Remover()

    removed = _client(remover).remove_playlist_item("PL1", "v1")

    assert removed == 2
    assert remover.removed == [
        (
            "PL1",
            [
                {"videoId": "v1", "setVideoId": "s1"},
                {"videoId": "v1", "setVideoId": "s3"},
            ],
        )
    ]


def test_remove_playlist_item_without_oauth_returns_zero_when_absent() -> None:
    class Empty:
        def get_playlist(self, playlist_id: str, limit: int | None = None) -> dict[str, Any]:
            return {"tracks": [{"videoId": "v2", "setVideoId": "s2"}]}

        def remove_playlist_items(self, playlist_id: str, videos: list[dict[str, str]]) -> None:
            raise AssertionError("must not remove when the video is absent")

    assert _client(Empty()).remove_playlist_item("PL1", "v1") == 0


def test_remove_playlist_item_without_oauth_wraps_errors() -> None:
    class Failing:
        def get_playlist(self, playlist_id: str, limit: int | None = None) -> dict[str, Any]:
            return {"tracks": [{"videoId": "v1", "setVideoId": "s1"}]}

        def remove_playlist_items(self, playlist_id: str, videos: list[dict[str, str]]) -> None:
            raise RuntimeError("offline")

    with pytest.raises(YTMClientError, match="Could not remove track from playlist PL1"):
        _client(Failing()).remove_playlist_item("PL1", "v1")


def test_remove_playlist_item_with_oauth_deletes_matching_items(
    oauth_client: YTMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    deletes: list[dict[str, Any] | None] = []

    def fake_request(method, endpoint, *, params=None, json_body=None):
        if method == "GET" and endpoint == "playlistItems":
            return {
                "items": [
                    {"id": "item-1", "snippet": {"resourceId": {"videoId": "v1"}}},
                    {"id": "item-2", "snippet": {"resourceId": {"videoId": "v2"}}},
                    {"snippet": {"resourceId": {"videoId": "v1"}}},
                ]
            }
        deletes.append(params)
        return {}

    monkeypatch.setattr(oauth_client, "_youtube_data_request", fake_request)

    removed = oauth_client.remove_playlist_item("PL1", "v1")

    assert removed == 1
    assert deletes == [{"id": "item-1"}]


def test_add_playlist_items_with_no_videos_short_circuits() -> None:
    result = _client().add_playlist_items("PL1", [])

    assert result.requested == 0
    assert result.added == 0


def _snapshot_client(fake: Any, before: list[str], after: list[str]) -> YTMClient:
    from bester_ytm.ytm_client import PlaylistSnapshot

    client = _client(fake)
    snapshots = [
        PlaylistSnapshot(playlist_id="PL1", video_ids=list(before)),
        PlaylistSnapshot(playlist_id="PL1", video_ids=list(after)),
    ]
    client.get_playlist = lambda playlist_id: snapshots.pop(0)  # type: ignore[method-assign]
    return client


def test_add_playlist_items_without_oauth_deduplicates() -> None:
    class Adder:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def add_playlist_items(self, playlist_id: str, video_ids: list[str]):
            self.calls.append(video_ids)
            return {"status": "STATUS_SUCCEEDED"}

    adder = Adder()
    client = _snapshot_client(adder, before=["v0"], after=["v0", "v1"])

    result = client.add_playlist_items("PL1", ["v0", "v1", "v1"])

    assert adder.calls == [["v1"]]
    assert result.added == 1
    assert result.duplicate_or_existing == 2
    assert "STATUS_SUCCEEDED" in (result.raw_status or "")


def test_add_playlist_items_without_oauth_skips_when_all_present() -> None:
    class Adder:
        def add_playlist_items(self, playlist_id: str, video_ids: list[str]):
            raise AssertionError("must not add already-present tracks")

    client = _snapshot_client(Adder(), before=["v1"], after=["v1"])

    result = client.add_playlist_items("PL1", ["v1"])

    assert result.added == 0
    assert result.raw_status == "all requested tracks already present"


def test_add_playlist_items_without_oauth_wraps_errors() -> None:
    class Adder:
        def add_playlist_items(self, playlist_id: str, video_ids: list[str]):
            raise RuntimeError("offline")

    client = _snapshot_client(Adder(), before=[], after=[])

    with pytest.raises(YTMClientError, match="Could not add tracks to playlist PL1"):
        client.add_playlist_items("PL1", ["v1"])
