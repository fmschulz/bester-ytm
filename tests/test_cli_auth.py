from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from bester_ytm.auth import AuthManager
from bester_ytm.cli import app
from bester_ytm.config import ConfigError


def test_auth_login_defaults_to_browser_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    saved = tmp_path / "config" / "bester-ytm" / "browser.json"

    def fake_login_browser(self, headers_raw=None) -> Path:
        return saved

    monkeypatch.setattr(AuthManager, "login_browser", fake_login_browser)

    result = CliRunner().invoke(app, ["auth", "login"])

    assert result.exit_code == 0
    assert "Browser login saved" in result.output
    assert "auth status" in result.output


def test_auth_login_oauth_flag_uses_oauth_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    calls: list[bool] = []

    def fake_login(self, open_browser: bool = True) -> Path:
        calls.append(open_browser)
        return tmp_path / "config" / "bester-ytm" / "oauth.json"

    monkeypatch.setattr(AuthManager, "login", fake_login)

    result = CliRunner().invoke(app, ["auth", "login", "--oauth", "--no-browser"])

    assert result.exit_code == 0
    assert calls == [False]
    assert "OAuth token saved" in result.output


def test_auth_login_browser_warns_when_oauth_token_takes_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config_dir = tmp_path / "config" / "bester-ytm"
    config_dir.mkdir(parents=True)
    (config_dir / "oauth.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        AuthManager, "login_browser", lambda self, headers_raw=None: config_dir / "browser.json"
    )

    result = CliRunner().invoke(app, ["auth", "login"])

    assert result.exit_code == 0
    assert "takes" in result.output and "precedence" in result.output


def test_auth_login_reports_config_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def failing(self, headers_raw=None) -> Path:
        raise ConfigError("YouTube Music login is not configured.")

    monkeypatch.setattr(AuthManager, "login_browser", failing)

    result = CliRunner().invoke(app, ["auth", "login"])

    assert result.exit_code == 1
    assert "not configured" in result.output
