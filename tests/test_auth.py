import io
import json
import stat
import sys
from pathlib import Path

import pytest

import bester_ytm.auth as auth_module
from bester_ytm.auth import AuthManager
from bester_ytm.config import ConfigError, load_oauth_client

VALID_BROWSER_HEADERS = """accept: */*
authorization: SAPISIDHASH 123_abc
cookie: VISITOR_INFO1_LIVE=x; SAPISID=y; __Secure-3PAPISID=y; __Secure-3PSID=z
x-goog-authuser: 0
user-agent: Mozilla/5.0"""

NETSCAPE_COOKIES = """\
# Netscape HTTP Cookie File
.youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\tsap-value
.youtube.com\tTRUE\t/\tTRUE\t0\t__Secure-3PAPISID\tsap-value
"""


class FakeTtyStdin(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def stub_verify(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    verified: list[str] = []

    def fake_verify(headers_json: str) -> int:
        verified.append(headers_json)
        return 1

    monkeypatch.setattr(auth_module, "verify_browser_auth", fake_verify)
    return verified


def test_first_time_oauth_prompt_writes_private_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "client-id")
    monkeypatch.setattr("bester_ytm.auth.getpass", lambda prompt: "client-secret")

    manager = AuthManager()

    assert manager._load_or_prompt_oauth_client() == ("client-id", "client-secret")
    assert load_oauth_client(manager.paths.oauth_client) == (
        "client-id",
        "client-secret",
    )
    assert stat.S_IMODE(manager.paths.config_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(manager.paths.oauth_client.stat().st_mode) == 0o600


def test_missing_oauth_client_noninteractive_raises_setup_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with pytest.raises(ConfigError, match="YouTube Music login is not configured"):
        AuthManager()._load_or_prompt_oauth_client()


def test_first_time_prompt_prints_setup_guide(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        "builtins.input", lambda prompt: "my-app.apps.googleusercontent.com"
    )
    monkeypatch.setattr("bester_ytm.auth.getpass", lambda prompt: "client-secret")

    AuthManager()._load_or_prompt_oauth_client()

    output = capsys.readouterr().out
    assert "https://console.cloud.google.com/apis/credentials" in output
    assert "TVs and Limited Input devices" in output
    assert "does not look like" not in output


def test_first_time_prompt_warns_on_unusual_client_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "AIzaSyNotAClientId")
    monkeypatch.setattr("bester_ytm.auth.getpass", lambda prompt: "client-secret")

    AuthManager()._load_or_prompt_oauth_client()

    output = capsys.readouterr().out
    assert "does not look like a Google OAuth client ID" in output


def test_browser_login_writes_private_auth_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_verify: list[str]
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    manager = AuthManager()

    path = manager.login_browser(headers_raw=VALID_BROWSER_HEADERS)

    assert path == manager.paths.browser_auth
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(manager.paths.config_dir.stat().st_mode) == 0o700
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "SAPISID=y" in saved["cookie"]
    assert len(stub_verify) == 1


def test_browser_login_verifies_before_saving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def failing_verify(headers_json: str) -> int:
        raise RuntimeError("401 unauthorized")

    monkeypatch.setattr(auth_module, "verify_browser_auth", failing_verify)
    manager = AuthManager()

    with pytest.raises(ConfigError, match="did not work against YouTube Music"):
        manager.login_browser(headers_raw=VALID_BROWSER_HEADERS)
    assert not manager.paths.browser_auth.exists()


def test_browser_login_from_browser_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_verify: list[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    exported: list[str] = []

    def fake_export(browser: str, private_dir: Path) -> str:
        exported.append(browser)
        return "SAPISID=sap; __Secure-3PAPISID=sap; __Secure-3PSID=sid"

    monkeypatch.setattr(auth_module, "export_browser_cookie_header", fake_export)
    manager = AuthManager()

    path = manager.login_browser(browser="firefox")

    assert exported == ["firefox"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["cookie"] == "SAPISID=sap; __Secure-3PAPISID=sap; __Secure-3PSID=sid"
    assert saved["x-goog-authuser"] == "0"
    assert "SAPISIDHASH" in saved["authorization"]


def test_browser_login_from_cookies_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_verify: list[str]
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text(NETSCAPE_COOKIES, encoding="utf-8")
    manager = AuthManager()

    path = manager.login_browser(cookies_file=cookies_file)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "SAPISID=sap-value" in saved["cookie"]


def test_browser_login_default_tty_picks_detected_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_verify: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(sys, "stdin", FakeTtyStdin("\n"))
    monkeypatch.setattr(auth_module, "detect_browsers", lambda: ["firefox", "chromium"])
    monkeypatch.setattr(
        auth_module,
        "export_browser_cookie_header",
        lambda browser, private_dir: f"__Secure-3PAPISID=from-{browser}",
    )
    manager = AuthManager()

    path = manager.login_browser()

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["cookie"] == "__Secure-3PAPISID=from-firefox"
    output = capsys.readouterr().out
    assert "1. firefox" in output
    assert "2. chromium" in output


def test_browser_login_default_tty_without_browsers_suggests_paste(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(sys, "stdin", FakeTtyStdin(""))
    monkeypatch.setattr(auth_module, "detect_browsers", lambda: [])

    with pytest.raises(ConfigError, match="--paste"):
        AuthManager().login_browser()


def test_browser_login_paste_ends_on_blank_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_verify: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    pasted = VALID_BROWSER_HEADERS + "\n\nleftover: ignored\n"
    monkeypatch.setattr(sys, "stdin", FakeTtyStdin(pasted))
    manager = AuthManager()

    path = manager.login_browser(paste=True)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "SAPISID=y" in saved["cookie"]
    assert "leftover" not in saved
    output = capsys.readouterr().out
    assert "Copy as cURL" in output
    assert "Ctrl" not in output


def test_browser_login_paste_accepts_curl_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_verify: list[str]
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    pasted = (
        "curl 'https://music.youtube.com/youtubei/v1/browse' "
        "-H 'cookie: __Secure-3PAPISID=sap; __Secure-3PSID=sid' "
        "-H 'x-goog-authuser: 0'\n\n"
    )
    monkeypatch.setattr(sys, "stdin", FakeTtyStdin(pasted))
    manager = AuthManager()

    path = manager.login_browser(paste=True)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["cookie"] == "__Secure-3PAPISID=sap; __Secure-3PSID=sid"


def test_browser_login_piped_stdin_reads_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_verify: list[str]
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(VALID_BROWSER_HEADERS))
    manager = AuthManager()

    path = manager.login_browser()

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "SAPISID=y" in saved["cookie"]


def test_browser_login_without_headers_noninteractive_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    with pytest.raises(ConfigError, match="YouTube Music login is not configured"):
        AuthManager().login_browser()


def test_browser_login_rejects_unusable_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    with pytest.raises(ConfigError, match="Could not use the captured login data"):
        AuthManager().login_browser(headers_raw="accept: */*")


def test_logout_removes_oauth_token_and_browser_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    manager = AuthManager()
    manager.paths.config_dir.mkdir(parents=True)
    manager.paths.oauth_token.write_text("{}", encoding="utf-8")
    manager.paths.browser_auth.write_text("{}", encoding="utf-8")

    assert manager.logout() is True

    assert not manager.paths.oauth_token.exists()
    assert not manager.paths.browser_auth.exists()
    assert manager.logout() is False
