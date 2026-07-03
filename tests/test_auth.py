import io
import json
import stat
import sys
from pathlib import Path

import pytest

from bester_ytm.auth import AuthManager
from bester_ytm.config import ConfigError, load_oauth_client

VALID_BROWSER_HEADERS = """accept: */*
authorization: SAPISIDHASH 123_abc
cookie: VISITOR_INFO1_LIVE=x; SAPISID=y; __Secure-3PSID=z
x-goog-authuser: 0
user-agent: Mozilla/5.0"""


class FakeTtyStdin(io.StringIO):
    def isatty(self) -> bool:
        return True


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    manager = AuthManager()

    path = manager.login_browser(headers_raw=VALID_BROWSER_HEADERS)

    assert path == manager.paths.browser_auth
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(manager.paths.config_dir.stat().st_mode) == 0o700
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "SAPISID=y" in saved["cookie"]


def test_browser_login_reads_pasted_headers_interactively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(sys, "stdin", FakeTtyStdin(VALID_BROWSER_HEADERS))
    manager = AuthManager()

    path = manager.login_browser()

    assert path.exists()
    output = capsys.readouterr().out
    assert "music.youtube.com" in output
    assert "Paste the headers" in output


def test_browser_login_accepts_firefox_nel_separated_paste(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    pasted = "\x1b[200~" + VALID_BROWSER_HEADERS.replace("\n", "\u0085") + "\x1b[201~"
    monkeypatch.setattr(sys, "stdin", FakeTtyStdin(pasted))
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

    with pytest.raises(ConfigError, match="Could not use the pasted headers"):
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
