from __future__ import annotations

from pathlib import Path

import pytest

from bester_ytm.config import (
    ConfigError,
    load_intelligence_settings,
    load_transition_settings,
    save_transition_settings,
)
from bester_ytm.transitions import TransitionSettings, TransitionStyle


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    settings = load_intelligence_settings(tmp_path / "config.toml")

    assert settings.provider == "auto"
    assert settings.api_key_env == "OPENROUTER_API_KEY"


def test_loads_intelligence_section(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[intelligence]\nprovider = "openai"\nmodel = "llama3"\n'
        'base_url = "http://localhost:11434/v1"\napi_key_env = "OLLAMA_KEY"\n',
        encoding="utf-8",
    )

    settings = load_intelligence_settings(path)

    assert settings.provider == "openai"
    assert settings.model == "llama3"
    assert settings.base_url == "http://localhost:11434/v1"
    assert settings.api_key_env == "OLLAMA_KEY"


def test_rejects_unknown_provider_and_non_string_values(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[intelligence]\nprovider = "skynet"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="intelligence.provider must be one of"):
        load_intelligence_settings(path)

    path.write_text("[intelligence]\nmodel = 5\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="intelligence.model must be a string"):
        load_intelligence_settings(path)


def test_saving_transitions_preserves_intelligence_section(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[playback]\ntransition = "cut"\nfade_seconds = 3.0\n\n'
        '[intelligence]\nprovider = "codex"\nmodel = "gpt-5"\n',
        encoding="utf-8",
    )

    save_transition_settings(
        TransitionSettings(style=TransitionStyle.CROSSFADE, fade_seconds=8.0), path
    )

    transitions = load_transition_settings(path)
    intelligence = load_intelligence_settings(path)
    assert transitions.fade_seconds == 8.0
    assert intelligence.provider == "codex"
    assert intelligence.model == "gpt-5"


def test_saving_still_refuses_foreign_sections(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[playback]\n\n[custom]\nkey = 1\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="cannot rewrite"):
        save_transition_settings(TransitionSettings(), path)
