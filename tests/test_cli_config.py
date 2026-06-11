from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from bester_ytm.cli import app
from bester_ytm.config import get_paths


def sandbox_config_file(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return get_paths().config_file


def test_config_show_with_missing_file(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)

    result = CliRunner().invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert f"config file: {path} (missing; defaults in effect)" in result.output
    assert "[playback]" in result.output
    assert 'transition = "crossfade"' in result.output
    assert "fade_seconds = 6.0" in result.output


def test_config_show_with_loaded_file(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[playback]\ntransition = "cut"\nfade_seconds = 4.5\n', encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert f"config file: {path} (loaded)" in result.output
    assert 'transition = "cut"' in result.output
    assert "fade_seconds = 4.5" in result.output


def test_config_show_reports_invalid_file(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[broken\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "show"])

    assert result.exit_code == 1
    assert "is not valid TOML" in result.output
    assert "Traceback" not in result.output
