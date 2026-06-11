import asyncio
from pathlib import Path

import pytest

from bester_ytm.tui import BesterYTMApp


def _mounted_statuses(app: BesterYTMApp, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    statuses: list[str] = []
    monkeypatch.setattr(app, "_set_status", statuses.append)

    async def run_flow() -> None:
        async with app.run_test(size=(100, 40)):
            pass

    asyncio.run(run_flow())
    return statuses


def test_startup_status_hints_login_without_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    statuses = _mounted_statuses(BesterYTMApp(), monkeypatch)

    assert any("bester-ytm auth login" in status for status in statuses)
    assert "Ready." not in statuses


def test_startup_status_ready_with_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config" / "bester-ytm"
    config_dir.mkdir(parents=True)
    (config_dir / "oauth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    statuses = _mounted_statuses(BesterYTMApp(), monkeypatch)

    assert "Ready." in statuses


def test_startup_status_prefers_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config" / "bester-ytm"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("not [valid toml", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    statuses = _mounted_statuses(BesterYTMApp(), monkeypatch)

    assert any("config.toml" in status for status in statuses)
    assert not any("auth login" in status for status in statuses)
