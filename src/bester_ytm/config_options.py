"""User options in config.toml beyond transitions: layout widths, visuals, volume, favorites.

`[ui]` is written by the app (splitter drags, visualizer changes); `[playback] volume`
and `[builder] favorites_file` are hand-edited and only read here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ConfigError, get_paths, load_config_document, rewrite_config_sections

DEFAULT_VISUALIZER = "mythos"
MIN_PANE_CELLS = 10
MAX_PANE_CELLS = 400


@dataclass(frozen=True)
class AppOptions:
    visualizer: str = DEFAULT_VISUALIZER
    left_width: int | None = None
    right_width: int | None = None
    volume: float = 100.0
    favorites_file: Path | None = None


def load_app_options(path: Path | None = None) -> AppOptions:
    config_path = path or get_paths().config_file
    document = load_config_document(config_path)
    ui = _section(document, "ui")
    playback = _section(document, "playback")
    builder = _section(document, "builder")
    return AppOptions(
        visualizer=_string(config_path, ui, "ui", "visualizer", DEFAULT_VISUALIZER),
        left_width=_optional_width(config_path, ui, "left_width"),
        right_width=_optional_width(config_path, ui, "right_width"),
        volume=_volume(config_path, playback),
        favorites_file=_optional_path(config_path, builder, "builder", "favorites_file"),
    )


def save_ui_options(
    visualizer: str,
    left_width: int | None = None,
    right_width: int | None = None,
    path: Path | None = None,
) -> Path:
    """Persist UI choices; a width of None keeps whatever the file already has."""
    values: dict[str, Any] = {"visualizer": visualizer}
    if left_width is not None:
        values["left_width"] = int(left_width)
    if right_width is not None:
        values["right_width"] = int(right_width)
    return rewrite_config_sections({"ui": values}, path)


def _section(document: dict[str, Any], name: str) -> dict[str, Any]:
    section = document.get(name)
    return section if isinstance(section, dict) else {}


def _string(
    path: Path, section: dict[str, Any], section_name: str, key: str, default: str
) -> str:
    value = section.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{path}: {section_name}.{key} must be a string (got {value!r})")
    return value


def _optional_width(path: Path, section: dict[str, Any], key: str) -> int | None:
    value = section.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{path}: ui.{key} must be a whole number of cells (got {value!r})")
    if not MIN_PANE_CELLS <= value <= MAX_PANE_CELLS:
        raise ConfigError(
            f"{path}: ui.{key} must be between {MIN_PANE_CELLS} and {MAX_PANE_CELLS} "
            f"(got {value})"
        )
    return value


def _volume(path: Path, section: dict[str, Any]) -> float:
    value = section.get("volume", 100.0)
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not is_number or not 0 <= float(value) <= 100:
        raise ConfigError(
            f"{path}: playback.volume must be a number between 0 and 100 (got {value!r})"
        )
    return float(value)


def _optional_path(
    path: Path, section: dict[str, Any], section_name: str, key: str
) -> Path | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"{path}: {section_name}.{key} must be a non-empty path string (got {value!r})"
        )
    return Path(value).expanduser()
