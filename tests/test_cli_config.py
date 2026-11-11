from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bester_ytm import config_writer
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


def test_config_show_defaults_are_complete_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox_config_file(tmp_path, monkeypatch)
    result = CliRunner().invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert tomllib.loads(result.output) == {
        "playback": {"transition": "crossfade", "fade_seconds": 6.0, "volume": 100.0},
        "ui": {"visualizer": "astra", "theme": "astra", "visual_fps": 20},
        "intelligence": {
            "provider": "auto",
            "model": "",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
        },
    }


def test_config_show_round_trips_settings_without_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True)
    source = """[playback]
transition = "cut"
fade_seconds = 4.5
volume = 42
[ui]
visualizer = "bars"
theme = "ember"
visual_fps = 12
left_width = 35
right_width = 45
[builder]
favorites_file = '/music/seed "mix".md'
[intelligence]
provider = "openai"
model = "chosen-model"
base_url = "https://example.test/api"
api_key_env = "MUSIC_API_KEY"
[radio.stations]
"a.b [radio]" = "https://example.test/live?x=1&y=2"
"""
    path.write_text(source, encoding="utf-8")
    monkeypatch.setenv("MUSIC_API_KEY", "private-test-value")
    result = CliRunner().invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "private-test-value" not in result.output
    assert tomllib.loads(result.output) == tomllib.loads(source)


def test_config_show_omits_empty_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True)
    path.write_text("[builder]\n[radio.stations]\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert "[builder]" not in result.output
    assert "[radio.stations]" not in result.output
    assert all(tomllib.loads(result.output).values())


@pytest.mark.parametrize("key", ["plain-key", "a.b [radio]", "Groove Salad"])
@pytest.mark.parametrize("value", [True, 42, 4.5, 'seed "mix"'])
def test_public_toml_helpers_round_trip(
    tmp_path: Path, key: str, value: bool | int | float | str
) -> None:
    scalar = config_writer.toml_scalar(tmp_path / "config.toml", key, value)
    text = f"{config_writer.toml_key(key)} = {scalar}"

    assert tomllib.loads(text) == {key: value}
