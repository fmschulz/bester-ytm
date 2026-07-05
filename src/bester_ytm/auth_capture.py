"""Acquire YouTube Music browser credentials from cookies, files, or pastes.

Three sources all converge on a ytmusicapi ``headers_raw`` block:
installed-browser cookie stores (read via the yt-dlp binary), Netscape
cookies.txt exports, and pasted DevTools output (raw headers or Copy as cURL).
"""

from __future__ import annotations

import http.cookiejar
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import ConfigError

MUSIC_ORIGIN = "https://music.youtube.com"

# Table order sets the preference order: Firefox first because its cookie
# store is plain SQLite (no macOS keychain or Linux keyring prompts).
_BROWSER_PROFILE_HINTS: tuple[tuple[str, str, str], ...] = (
    ("firefox", "linux", ".mozilla/firefox"),
    ("firefox", "linux", "snap/firefox/common/.mozilla/firefox"),
    ("firefox", "darwin", "Library/Application Support/Firefox"),
    ("chrome", "linux", ".config/google-chrome"),
    ("chrome", "darwin", "Library/Application Support/Google/Chrome"),
    ("chromium", "linux", ".config/chromium"),
    ("chromium", "darwin", "Library/Application Support/Chromium"),
    ("brave", "linux", ".config/BraveSoftware/Brave-Browser"),
    ("brave", "darwin", "Library/Application Support/BraveSoftware/Brave-Browser"),
    ("edge", "linux", ".config/microsoft-edge"),
    ("edge", "darwin", "Library/Application Support/Microsoft Edge"),
    ("vivaldi", "linux", ".config/vivaldi"),
    ("vivaldi", "darwin", "Library/Application Support/Vivaldi"),
    ("opera", "linux", ".config/opera"),
    ("opera", "darwin", "Library/Application Support/com.operasoftware.Opera"),
    ("safari", "darwin", "Library/Containers/com.apple.Safari"),
)

# Line separators seen in pasted text: CRLF/CR, NEL (U+0085, which Firefox's
# "Copy Request Headers" uses), its 7-bit form ESC E, and U+2028; plus
# bracketed-paste markers.
_PASTE_MARKERS = ("\x1b[200~", "\x1b[201~")
_PASTE_LINE_BREAKS = ("\r\n", "\r", "\x1bE", "\u0085", "\u2028")

_EXPORT_TIMEOUT_SECONDS = 180


def detect_browsers(home: Path | None = None, platform: str | None = None) -> list[str]:
    """Return supported browsers with a profile directory on this machine."""
    home = home or Path.home()
    platform = platform or sys.platform
    found: list[str] = []
    for browser, hint_platform, relative in _BROWSER_PROFILE_HINTS:
        if not platform.startswith(hint_platform) or browser in found:
            continue
        if (home / relative).exists():
            found.append(browser)
    return found


def export_browser_cookie_header(browser: str, private_dir: Path) -> str:
    """Read the YouTube Music cookies from a browser via the yt-dlp binary."""
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        raise ConfigError(
            "yt-dlp is not installed or not on PATH; it is needed to read "
            "browser cookies. Install it or use `auth login --paste`."
        )
    private_dir.mkdir(parents=True, exist_ok=True)
    private_dir.chmod(0o700)
    # The cookies file must not exist yet: yt-dlp loads an existing --cookies
    # file instead of overwriting it. A fresh 0700 directory keeps it private.
    tmp_dir = Path(tempfile.mkdtemp(prefix="cookies-", dir=private_dir))
    tmp_path = tmp_dir / "cookies.txt"
    try:
        # yt-dlp writes the extracted cookie jar during startup and only then
        # exits complaining about the missing URL; the file is all we need,
        # and no network access happens.
        completed = subprocess.run(
            [ytdlp, "--cookies-from-browser", browser, "--cookies", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=_EXPORT_TIMEOUT_SECONDS,
        )
        try:
            return cookie_header_from_netscape(tmp_path)
        except ConfigError as exc:
            raise ConfigError(
                f"Could not read a YouTube Music login from {browser}: {exc}"
                + _stderr_hint(completed.stderr)
            ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ConfigError(
            f"Reading cookies from {browser} timed out; if the OS asked for "
            "keychain or keyring access, approve it and retry."
        ) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
        tmp_dir.rmdir()


def _is_youtube_domain(domain: str) -> bool:
    """True only for youtube.com and its subdomains (not e.g. notyoutube.com)."""
    domain = domain.lstrip(".").lower()
    return domain == "youtube.com" or domain.endswith(".youtube.com")


def cookie_header_from_netscape(path: Path) -> str:
    """Build a Cookie header value from a Netscape cookies.txt file."""
    jar = http.cookiejar.MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except OSError as exc:
        raise ConfigError(f"not a readable Netscape cookies.txt file ({exc})") from exc
    pairs = {
        cookie.name: cookie.value
        for cookie in jar
        if _is_youtube_domain(cookie.domain) and cookie.value is not None
    }
    if "SAPISID" not in pairs and "__Secure-3PAPISID" not in pairs:
        raise ConfigError(
            "no logged-in YouTube session found (SAPISID cookie missing); "
            "make sure that browser is logged in at https://music.youtube.com"
        )
    return "; ".join(f"{name}={value}" for name, value in pairs.items())


def normalize_pasted_text(raw: str) -> str:
    for marker in _PASTE_MARKERS:
        raw = raw.replace(marker, "")
    for separator in _PASTE_LINE_BREAKS:
        raw = raw.replace(separator, "\n")
    return raw.strip()


def headers_from_paste(text: str) -> str:
    """Turn pasted DevTools output into a ytmusicapi headers_raw block.

    Accepts a "Copy as cURL" command or a raw request-headers block.
    """
    text = normalize_pasted_text(text)
    if not text:
        return ""
    if text.startswith("fetch("):
        raise ConfigError(
            "This looks like 'Copy as fetch', which omits the login cookie. "
            "Right-click the request again and pick Copy -> 'Copy as cURL'."
        )
    if text.startswith("curl "):
        return _headers_raw_from_curl(text)
    return text


def build_headers_raw(cookie_header: str) -> str:
    """Build a minimal headers_raw block from a Cookie header value."""
    return ensure_required_headers(f"cookie: {cookie_header}")


def ensure_required_headers(headers_raw: str) -> str:
    """Add x-goog-authuser, authorization, and origin lines when missing.

    ytmusicapi requires x-goog-authuser to accept the headers and an
    authorization value containing SAPISIDHASH to detect browser credentials;
    the hash itself is recomputed from the SAPISID cookie on every request.
    """
    names = {
        line.split(":", 1)[0].strip().lower()
        for line in headers_raw.splitlines()
        if ":" in line
    }
    extra: list[str] = []
    if "x-goog-authuser" not in names:
        extra.append("x-goog-authuser: 0")
    if "origin" not in names and "x-origin" not in names:
        extra.append(f"origin: {MUSIC_ORIGIN}")
    if "authorization" not in names:
        cookie_header = _cookie_value(headers_raw)
        if cookie_header:
            extra.append(f"authorization: {_sapisid_authorization(cookie_header)}")
    if not extra:
        return headers_raw
    return headers_raw + "\n" + "\n".join(extra)


def _cookie_value(headers_raw: str) -> str | None:
    for line in headers_raw.splitlines():
        name, _, value = line.partition(":")
        if name.strip().lower() == "cookie":
            return value.strip()
    return None


def _sapisid_authorization(cookie_header: str) -> str:
    try:
        from ytmusicapi.helpers import get_authorization, sapisid_from_cookie
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("ytmusicapi is not installed") from exc
    try:
        sapisid = sapisid_from_cookie(cookie_header)
    except Exception as exc:
        raise ConfigError(
            "the cookie has no SAPISID value; make sure you are logged in "
            "at https://music.youtube.com and copy the request again"
        ) from exc
    return get_authorization(sapisid + " " + MUSIC_ORIGIN)


def _headers_raw_from_curl(text: str) -> str:
    joined = text.replace("\\\n", " ").replace("^\n", " ").replace("\n", " ")
    try:
        tokens = shlex.split(joined)
    except ValueError as exc:
        raise ConfigError(f"Could not parse the pasted cURL command: {exc}") from exc

    headers: list[str] = []
    cookie_flag: str | None = None
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in ("-H", "--header") and index + 1 < len(tokens):
            headers.append(tokens[index + 1])
            index += 2
            continue
        if token in ("-b", "--cookie") and index + 1 < len(tokens):
            cookie_flag = tokens[index + 1]
            index += 2
            continue
        index += 1

    has_cookie = any(header.lower().startswith("cookie:") for header in headers)
    if cookie_flag and not has_cookie:
        headers.append(f"cookie: {cookie_flag}")
        has_cookie = True
    if not has_cookie:
        raise ConfigError(
            "The pasted cURL command has no cookie header; make sure you are "
            "logged in at https://music.youtube.com and copy a /browse request."
        )
    return "\n".join(headers)


def _stderr_hint(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    relevant = [line for line in lines if "You must provide at least one URL" not in line]
    if not relevant:
        return ""
    return "\nyt-dlp said: " + relevant[-1]
