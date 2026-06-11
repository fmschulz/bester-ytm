from __future__ import annotations

import os
from pathlib import Path

import pytest

from bester_ytm.config import (
    ConfigError,
    get_paths,
    load_transition_settings,
    save_transition_settings,
)
from bester_ytm.transitions import (
    DEFAULT_APP_SETTINGS,
    TransitionSettings,
    TransitionStyle,
)


def sandbox_config_file(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return get_paths().config_file


def write_config(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_missing_file_returns_app_defaults(tmp_path: Path, monkeypatch) -> None:
    sandbox_config_file(tmp_path, monkeypatch)

    assert load_transition_settings() == DEFAULT_APP_SETTINGS


def test_load_valid_file(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    write_config(path, '[playback]\ntransition = "cut"\nfade_seconds = 9.5\n')

    settings = load_transition_settings()

    assert settings == TransitionSettings(style=TransitionStyle.CUT, fade_seconds=9.5)


def test_load_explicit_path(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    write_config(path, '[playback]\ntransition = "crossfade"\nfade_seconds = 3\n')

    settings = load_transition_settings(path)

    assert settings.style is TransitionStyle.CROSSFADE
    assert settings.fade_seconds == 3.0
    assert isinstance(settings.fade_seconds, float)


def test_load_missing_keys_fall_back_to_app_defaults(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    write_config(path, '[playback]\ntransition = "cut"\n')

    settings = load_transition_settings()

    assert settings == TransitionSettings(style=TransitionStyle.CUT, fade_seconds=6.0)


def test_load_ignores_unknown_keys_and_sections(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    write_config(
        path,
        '[playback]\nfade_seconds = 4.0\nfuture_key = "x"\n\n[future_section]\nother = 1\n',
    )

    settings = load_transition_settings()

    assert settings == TransitionSettings(style=TransitionStyle.CROSSFADE, fade_seconds=4.0)


def test_invalid_toml_raises_config_error(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    write_config(path, "[playback\ntransition =\n")

    with pytest.raises(ConfigError, match="is not valid TOML"):
        load_transition_settings()


def test_non_utf8_config_raises_config_error(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00broken")

    with pytest.raises(ConfigError, match="could not be read"):
        load_transition_settings()


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission checks")
def test_unreadable_config_raises_config_error(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    write_config(path, '[playback]\ntransition = "cut"\n')
    path.chmod(0o000)
    try:
        with pytest.raises(ConfigError, match="could not be read"):
            load_transition_settings()
    finally:
        path.chmod(0o600)


def test_invalid_transition_value_raises(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    write_config(path, '[playback]\ntransition = "fade"\n')

    with pytest.raises(
        ConfigError,
        match=r"playback\.transition must be cut or crossfade \(got 'fade'\)",
    ):
        load_transition_settings()


def test_invalid_transition_type_raises(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    write_config(path, "[playback]\ntransition = 3\n")

    with pytest.raises(
        ConfigError,
        match=r"playback\.transition must be cut or crossfade \(got 3\)",
    ):
        load_transition_settings()


@pytest.mark.parametrize("raw_value", ["0.5", "16", "true", '"6"'])
def test_invalid_fade_seconds_raises(tmp_path: Path, monkeypatch, raw_value: str) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    write_config(path, f"[playback]\nfade_seconds = {raw_value}\n")

    with pytest.raises(
        ConfigError,
        match=r"playback\.fade_seconds must be a number between 1 and 15",
    ):
        load_transition_settings()


def test_save_round_trip_and_exact_serialization(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    settings = TransitionSettings(style=TransitionStyle.CROSSFADE, fade_seconds=8.0)

    saved_path = save_transition_settings(settings)

    assert saved_path == path
    assert path.read_text(encoding="utf-8") == (
        '[playback]\ntransition = "crossfade"\nfade_seconds = 8.0\n'
    )
    assert load_transition_settings() == settings


def test_save_overwrites_playback_only_file(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    write_config(path, '[playback]\ntransition = "cut"\nfade_seconds = 2.0\n')
    settings = TransitionSettings(style=TransitionStyle.CUT, fade_seconds=11.0)

    save_transition_settings(settings)

    assert load_transition_settings() == settings


def test_save_refuses_files_with_foreign_sections(tmp_path: Path, monkeypatch) -> None:
    path = sandbox_config_file(tmp_path, monkeypatch)
    write_config(path, '[playback]\ntransition = "cut"\n\n[user_section]\nkey = 1\n')

    with pytest.raises(
        ConfigError,
        match=r"contains sections this app cannot rewrite \(user_section\)",
    ):
        save_transition_settings(DEFAULT_APP_SETTINGS)
    assert "user_section" in path.read_text(encoding="utf-8")


def test_save_refuses_invalid_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    write_config(path, "[broken\n")

    with pytest.raises(ConfigError, match="is not valid TOML"):
        save_transition_settings(DEFAULT_APP_SETTINGS, path)


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission checks")
def test_save_converts_write_failure_to_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    write_config(path, '[playback]\ntransition = "cut"\nfade_seconds = 2.0\n')
    path.chmod(0o400)
    try:
        with pytest.raises(ConfigError, match="could not write"):
            save_transition_settings(DEFAULT_APP_SETTINGS, path)
    finally:
        path.chmod(0o600)
