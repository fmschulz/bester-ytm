from __future__ import annotations

import json
import sys
from getpass import getpass
from pathlib import Path

from .auth_capture import (
    build_headers_raw,
    cookie_header_from_netscape,
    detect_browsers,
    ensure_required_headers,
    export_browser_cookie_header,
    headers_from_paste,
)
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


def verify_browser_auth(headers_json: str) -> int:
    """Check credentials against the live API; return visible playlist count."""
    try:
        from ytmusicapi import YTMusic
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("ytmusicapi is not installed") from exc
    return len(YTMusic(auth=headers_json).get_library_playlists(limit=1))


def _print_paste_guide() -> None:
    print("Manual browser login:")
    print("  1. Open https://music.youtube.com and make sure you are logged in.")
    print("  2. Open developer tools (F12) -> Network tab and filter for '/browse'.")
    print("  3. Click a song so a 'browse' request appears, then right-click it")
    print("     -> Copy -> 'Copy as cURL'.")
    print("  4. Paste below and press Enter twice.")


def _read_paste_interactive() -> str:
    print("Paste here, then press Enter on an empty line to finish:")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line)
    return "\n".join(lines)


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

    def login_browser(
        self,
        headers_raw: str | None = None,
        *,
        browser: str | None = None,
        cookies_file: Path | None = None,
        paste: bool = False,
    ) -> Path:
        """Capture, verify, and store browser credentials for YouTube Music."""
        headers_raw = self._capture_headers(headers_raw, browser, cookies_file, paste)
        if not headers_raw:
            raise ConfigError(auth_setup_instructions())
        headers_raw = ensure_required_headers(headers_raw)

        try:
            from ytmusicapi import setup as ytmusicapi_setup
        except ImportError as exc:
            raise ConfigError("ytmusicapi is not installed") from exc
        try:
            headers_json = ytmusicapi_setup(headers_raw=headers_raw)
        except Exception as exc:
            raise ConfigError(
                f"Could not use the captured login data: {exc}\n"
                "Make sure the browser is logged in at https://music.youtube.com, "
                "or retry with `bester-ytm auth login --paste`."
            ) from exc

        try:
            playlist_count = verify_browser_auth(headers_json)
        except Exception as exc:
            raise ConfigError(
                f"The captured login did not work against YouTube Music: {exc}\n"
                "Log in at https://music.youtube.com in that browser and retry, "
                "or try another browser or `bester-ytm auth login --paste`."
            ) from exc
        print(f"Login verified ({playlist_count}+ library playlists visible).")

        write_private_json(self.paths.browser_auth, json.loads(headers_json))
        return set_private_file(self.paths.browser_auth)

    def _capture_headers(
        self,
        headers_raw: str | None,
        browser: str | None,
        cookies_file: Path | None,
        paste: bool,
    ) -> str:
        if headers_raw is not None:
            return headers_from_paste(headers_raw)
        if browser:
            return build_headers_raw(
                export_browser_cookie_header(browser, self.paths.config_dir)
            )
        if cookies_file:
            return build_headers_raw(cookie_header_from_netscape(cookies_file))
        if paste and sys.stdin.isatty():
            _print_paste_guide()
            return headers_from_paste(_read_paste_interactive())
        if not sys.stdin.isatty():
            return headers_from_paste(sys.stdin.read())
        picked = self._pick_browser()
        if picked is None:
            raise ConfigError(
                "No browser profiles found. Use `bester-ytm auth login --paste` "
                "or `--cookies-file` instead."
            )
        return build_headers_raw(
            export_browser_cookie_header(picked, self.paths.config_dir)
        )

    def _pick_browser(self) -> str | None:
        browsers = detect_browsers()
        if not browsers:
            return None
        print("Reading your YouTube Music login from a browser you use.")
        print("Found browser profiles:")
        for index, name in enumerate(browsers, start=1):
            print(f"  {index}. {name}")
        while True:
            choice = input(
                f"Which browser is logged in? [1-{len(browsers)}, Enter = 1]: "
            ).strip()
            if not choice:
                choice = "1"
            if choice.isdigit() and 1 <= int(choice) <= len(browsers):
                picked = browsers[int(choice) - 1]
                break
            if choice in browsers:
                picked = choice
                break
            print("Please enter one of the listed numbers.")
        if picked != "firefox":
            print("If the OS asks for keychain or keyring access, allow it.")
        return picked

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
