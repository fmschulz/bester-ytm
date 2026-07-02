"""Auth, session, and transport layer for YouTube Music access."""

from __future__ import annotations

import threading
import time
from typing import Any

import requests

from .config import ConfigError, get_paths, load_oauth_client, require_private_file
from .ytm_models import AuthStatus, YTMClientError

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class _SerializedYTMusic:
    """Proxy that runs every method call on the wrapped client under a lock.

    ytmusicapi holds a single requests.Session, which is not thread-safe;
    the TUI issues overlapping calls from background worker threads.
    """

    def __init__(self, target: Any, lock: threading.Lock) -> None:
        self._target = target
        self._lock = lock

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._target, name)
        if not callable(attribute):
            return attribute

        def call_locked(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                return attribute(*args, **kwargs)

        return call_locked


class YTMSessionBase:
    def __init__(self, authenticated: bool = True) -> None:
        self.paths = get_paths()
        self.authenticated = authenticated
        self._ytmusic: Any | None = None
        self._backend: str | None = None
        self._lock = threading.Lock()

    @property
    def ytmusic(self) -> Any:
        with self._lock:
            if self._ytmusic is None:
                self._ytmusic = self._new_ytmusic()
            target = self._ytmusic
        return _SerializedYTMusic(target, self._lock)

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
