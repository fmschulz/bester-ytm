from __future__ import annotations

import sys
from getpass import getpass
from pathlib import Path

from .config import (
    ConfigError,
    auth_setup_instructions,
    get_paths,
    load_oauth_client,
    set_private_file,
    write_private_json,
)

GOOGLE_CREDENTIALS_URL = "https://console.cloud.google.com/apis/credentials"
OAUTH_CLIENT_ID_SUFFIX = ".apps.googleusercontent.com"


def _print_browser_login_guide() -> None:
    print("Browser login (no Google Cloud setup needed).")
    print("  1. Open https://music.youtube.com and make sure you are logged in.")
    print("  2. Open developer tools (F12) -> Network tab and filter for '/browse'.")
    print("  3. Click a song so a 'browse' request appears, then select it.")
    print("  4. Copy its request headers (Firefox: right-click -> Copy -> Copy Request")
    print("     Headers; Chrome: select and copy the whole Request Headers block).")


# Line separators seen in pasted headers: CRLF/CR, NEL (U+0085, which
# Firefox's "Copy Request Headers" uses, echoed by terminals as ESC E),
# its 7-bit form ESC E, and U+2028; plus bracketed-paste markers.
_PASTE_MARKERS = ("\x1b[200~", "\x1b[201~")
_PASTE_LINE_BREAKS = ("\r\n", "\r", "\x1bE", "\u0085", "\u2028")


def _normalize_pasted_headers(raw: str) -> str:
    for marker in _PASTE_MARKERS:
        raw = raw.replace(marker, "")
    for separator in _PASTE_LINE_BREAKS:
        raw = raw.replace(separator, "\n")
    return raw.strip()


def _read_headers_from_stdin() -> str:
    if sys.stdin.isatty():
        eof_hint = "Ctrl-D" if sys.platform != "win32" else "Ctrl-Z then Enter"
        print(f"Paste the headers below, then press Enter and {eof_hint}:")
    return sys.stdin.read()


def _print_first_time_setup_guide(config_dir: Path) -> None:
    print("First-time OAuth setup (one time only).")
    print(f"Get credentials at {GOOGLE_CREDENTIALS_URL}:")
    print("  1. Enable 'YouTube Data API v3' under APIs & Services -> Library.")
    print("  2. Create an OAuth client ID of type 'TVs and Limited Input devices'.")
    print("  3. Paste the client ID and client secret below.")
    print(f"They are stored privately in {config_dir} and never leave this machine.")


def _warn_if_unusual_client_id(client_id: str) -> None:
    if client_id.endswith(OAUTH_CLIENT_ID_SUFFIX):
        return
    print(
        "Warning: this does not look like a Google OAuth client ID "
        f"(expected a value ending in {OAUTH_CLIENT_ID_SUFFIX}); continuing anyway."
    )


class AuthManager:
    def __init__(self) -> None:
        self.paths = get_paths()

    def login(self, open_browser: bool = True) -> Path:
        client_id, client_secret = self._load_or_prompt_oauth_client()

        try:
            from ytmusicapi import OAuthCredentials
            from ytmusicapi.auth.oauth import RefreshingToken
        except ImportError as exc:
            raise ConfigError("ytmusicapi with OAuth support is not installed") from exc

        credentials = OAuthCredentials(client_id=client_id, client_secret=client_secret)
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.config_dir.chmod(0o700)
        RefreshingToken.prompt_for_token(
            credentials,
            open_browser=open_browser,
            to_file=str(self.paths.oauth_token),
        )
        return set_private_file(self.paths.oauth_token)

    def login_browser(self, headers_raw: str | None = None) -> Path:
        """Store pasted music.youtube.com request headers as browser credentials."""
        try:
            from ytmusicapi import setup as ytmusicapi_setup
        except ImportError as exc:
            raise ConfigError("ytmusicapi is not installed") from exc

        if headers_raw is None:
            if sys.stdin.isatty():
                _print_browser_login_guide()
            headers_raw = _read_headers_from_stdin()
        headers_raw = _normalize_pasted_headers(headers_raw)
        if not headers_raw:
            raise ConfigError(auth_setup_instructions())

        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.config_dir.chmod(0o700)
        try:
            ytmusicapi_setup(filepath=str(self.paths.browser_auth), headers_raw=headers_raw)
        except Exception as exc:
            raise ConfigError(
                f"Could not use the pasted headers: {exc}\n"
                "Copy the full request headers of a logged-in music.youtube.com "
                "request; they must include the cookie and x-goog-authuser lines."
            ) from exc
        return set_private_file(self.paths.browser_auth)

    def _load_or_prompt_oauth_client(self) -> tuple[str, str]:
        if self.paths.oauth_client.exists():
            return load_oauth_client(self.paths.oauth_client)
        if not sys.stdin.isatty():
            raise ConfigError(auth_setup_instructions())

        _print_first_time_setup_guide(self.paths.config_dir)
        client_id = input("OAuth client ID: ").strip()
        client_secret = getpass("OAuth client secret: ").strip()
        if not client_id or not client_secret:
            raise ConfigError("OAuth client ID and secret are required.")
        _warn_if_unusual_client_id(client_id)

        write_private_json(
            self.paths.oauth_client,
            {"client_id": client_id, "client_secret": client_secret},
        )
        print(f"OAuth client credentials saved: {self.paths.oauth_client}")
        return load_oauth_client(self.paths.oauth_client)

    def logout(self) -> bool:
        removed = False
        for path in (self.paths.oauth_token, self.paths.browser_auth):
            if path.exists():
                path.unlink()
                removed = True
        return removed
