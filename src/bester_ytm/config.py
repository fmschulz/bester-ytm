from __future__ import annotations

import json
import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .intelligence.llm import KNOWN_PROVIDERS, IntelligenceSettings
from .transitions import (
    DEFAULT_APP_SETTINGS,
    MAX_FADE_SECONDS,
    MIN_FADE_SECONDS,
    TransitionSettings,
    TransitionStyle,
)

APP_NAME = "bester-ytm"


class ConfigError(RuntimeError):
    """Raised when local configuration or secret files are invalid."""


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    oauth_client: Path
    oauth_token: Path
    browser_auth: Path
    config_file: Path
    plans_dir: Path
    favorites_file: Path
    favorites_store_file: Path
    local_playlists_dir: Path


def _xdg_dir(env_name: str, fallback: str) -> Path:
    root = os.environ.get(env_name)
    if root:
        return Path(root).expanduser()
    return Path(fallback).expanduser()


def get_paths() -> AppPaths:
    config_dir = _xdg_dir("XDG_CONFIG_HOME", "~/.config") / APP_NAME
    data_dir = _xdg_dir("XDG_DATA_HOME", "~/.local/share") / APP_NAME
    return AppPaths(
        config_dir=config_dir,
        data_dir=data_dir,
        oauth_client=config_dir / "oauth-client.json",
        oauth_token=config_dir / "oauth.json",
        browser_auth=config_dir / "browser.json",
        config_file=config_dir / "config.toml",
        plans_dir=data_dir / "plans",
        favorites_file=data_dir / "favorites.md",
        favorites_store_file=data_dir / "favorites.json",
        local_playlists_dir=data_dir / "local-playlists",
    )


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except PermissionError as exc:
        raise ConfigError(f"Could not set private permissions on {path}") from exc
    return path


def ensure_parent_private(path: Path) -> None:
    ensure_private_dir(path.parent)


def write_private_text(path: Path, text: str) -> None:
    ensure_parent_private(path)
    path.write_text(text, encoding="utf-8")
    set_private_file(path)


def write_private_json(path: Path, payload: dict[str, Any]) -> None:
    write_private_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def set_private_file(path: Path) -> Path:
    if not path.exists():
        raise ConfigError(f"Expected file does not exist: {path}")
    try:
        path.chmod(0o600)
    except PermissionError as exc:
        raise ConfigError(f"Could not set private permissions on {path}") from exc
    return path


def file_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def require_private_file(path: Path) -> None:
    mode = file_mode(path)
    if mode & 0o077:
        raise ConfigError(
            f"{path} is too permissive ({mode:o}); run chmod 600 {path}"
        )


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc


def load_oauth_client(path: Path | None = None) -> tuple[str, str]:
    paths = get_paths()
    client_path = path or paths.oauth_client
    payload = load_json_file(client_path)

    if "installed" in payload and isinstance(payload["installed"], dict):
        payload = payload["installed"]
    elif "web" in payload and isinstance(payload["web"], dict):
        payload = payload["web"]

    client_id = str(payload.get("client_id") or "").strip()
    client_secret = str(payload.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise ConfigError(
            f"{client_path} must contain client_id and client_secret fields"
        )
    require_private_file(client_path)
    return client_id, client_secret


def resolve_existing_input(path: Path) -> Path:
    """Resolve CLI input paths against the home directory and current directory."""

    expanded = path.expanduser()
    candidates = [expanded]
    if not expanded.is_absolute():
        candidates.append((Path.cwd() / expanded).resolve())

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise ConfigError(f"Input file does not exist: {path}")


def load_transition_settings(path: Path | None = None) -> TransitionSettings:
    config_path = path or get_paths().config_file
    try:
        document = _parse_toml_file(config_path)
    except FileNotFoundError:
        return DEFAULT_APP_SETTINGS
    section = document.get("playback")
    if not isinstance(section, dict):
        section = {}
    return TransitionSettings(
        style=_parse_transition_style(config_path, section),
        fade_seconds=_parse_fade_seconds(config_path, section),
    )


def save_transition_settings(settings: TransitionSettings, path: Path | None = None) -> Path:
    return rewrite_config_sections(
        {
            "playback": {
                "transition": settings.style.value,
                "fade_seconds": float(settings.fade_seconds),
            }
        },
        path,
    )


# Sections this app may rewrite; anything else in config.toml is the user's.
_REWRITABLE_SECTIONS = ("playback", "intelligence", "ui", "builder")


def load_config_document(path: Path) -> dict[str, Any]:
    """The parsed config.toml, or an empty document when the file does not exist."""
    try:
        return _parse_toml_file(path)
    except FileNotFoundError:
        return {}


def rewrite_config_sections(
    updates: dict[str, dict[str, Any]], path: Path | None = None
) -> Path:
    """Merge updates into config.toml, preserving every other app section and key."""
    config_path = path or get_paths().config_file
    document = _existing_rewritable_document(config_path)
    for section, values in updates.items():
        document.setdefault(section, {}).update(values)
    lines: list[str] = []
    for section in _REWRITABLE_SECTIONS:
        entries = document.get(section)
        if not entries:
            continue
        if lines:
            lines.append("")
        lines.append(f"[{section}]")
        for key, value in entries.items():
            lines.append(f"{key} = {_toml_scalar(config_path, f'{section}.{key}', value)}")
    try:
        write_private_text(config_path, "\n".join(lines) + "\n")
    except OSError as exc:
        raise ConfigError(f"could not write {config_path}: {exc}") from exc
    return config_path


def _existing_rewritable_document(config_path: Path) -> dict[str, dict[str, Any]]:
    existing = load_config_document(config_path)
    unknown = set(existing) - set(_REWRITABLE_SECTIONS)
    if unknown:
        raise ConfigError(
            f"{config_path} contains sections this app cannot rewrite "
            f"({', '.join(sorted(unknown))}); edit the file manually"
        )
    return {
        section: dict(values)
        for section, values in existing.items()
        if isinstance(values, dict)
    }


def load_intelligence_settings(path: Path | None = None) -> IntelligenceSettings:
    config_path = path or get_paths().config_file
    try:
        document = _parse_toml_file(config_path)
    except FileNotFoundError:
        return IntelligenceSettings()
    section = document.get("intelligence")
    if not isinstance(section, dict):
        return IntelligenceSettings()
    defaults = IntelligenceSettings()
    provider = _parse_setting_string(config_path, section, "provider", defaults.provider)
    if provider.strip().lower() not in KNOWN_PROVIDERS:
        raise ConfigError(
            f"{config_path}: intelligence.provider must be one of "
            f"{', '.join(KNOWN_PROVIDERS)} (got {provider!r})"
        )
    return IntelligenceSettings(
        provider=provider.strip().lower(),
        model=_parse_setting_string(config_path, section, "model", defaults.model),
        base_url=_parse_setting_string(config_path, section, "base_url", defaults.base_url),
        api_key_env=_parse_setting_string(
            config_path, section, "api_key_env", defaults.api_key_env
        ),
    )


def _parse_setting_string(path: Path, section: dict[str, Any], key: str, default: str) -> str:
    value = section.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{path}: intelligence.{key} must be a string (got {value!r})")
    return value


def _toml_scalar(path: Path, dotted_key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    raise ConfigError(
        f"{path}: {dotted_key} has a value this app cannot rewrite; "
        "edit the file manually"
    )


def _parse_toml_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Callers rely on this to fall back to application defaults.
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path} could not be read: {exc}") from exc
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc


def _parse_transition_style(path: Path, section: dict[str, Any]) -> TransitionStyle:
    value = section.get("transition", DEFAULT_APP_SETTINGS.style.value)
    if isinstance(value, str):
        try:
            return TransitionStyle(value)
        except ValueError:
            pass
    raise ConfigError(
        f"{path}: playback.transition must be cut or crossfade (got {value!r})"
    )


def _parse_fade_seconds(path: Path, section: dict[str, Any]) -> float:
    value = section.get("fade_seconds", DEFAULT_APP_SETTINGS.fade_seconds)
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not is_number or not MIN_FADE_SECONDS <= float(value) <= MAX_FADE_SECONDS:
        raise ConfigError(
            f"{path}: playback.fade_seconds must be a number between 1 and 15 (got {value!r})"
        )
    return float(value)


def auth_setup_instructions() -> str:
    paths = get_paths()
    return (
        "YouTube Music login is not configured.\n\n"
        "Easiest (no Google Cloud setup): run `bester-ytm auth login` in an "
        "interactive terminal and paste the request headers copied from a "
        "logged-in https://music.youtube.com browser tab; they are stored at "
        f"{paths.browser_auth}.\n\n"
        "Alternative with a self-refreshing token: create Google Cloud OAuth "
        "credentials (enable 'YouTube Data API v3', OAuth client ID of type "
        "'TVs and Limited Input devices'), store them at "
        f"{paths.oauth_client}:\n\n"
        "{\n"
        '  "client_id": "YOUR_CLIENT_ID",\n'
        '  "client_secret": "YOUR_CLIENT_SECRET"\n'
        "}\n\n"
        "then run `bester-ytm auth login --oauth`.\n"
    )
