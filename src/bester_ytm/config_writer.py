"""Write app-owned TOML sections through private file helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import ConfigError, get_paths, load_config_document, write_private_text
from .transitions import TransitionSettings

_REWRITABLE_SECTIONS = ("playback", "intelligence", "ui", "builder", "radio")


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


def rewrite_config_sections(updates: dict[str, dict[str, Any]], path: Path | None = None) -> Path:
    """Merge updates into config.toml, preserving every other app section and key."""
    config_path = path or get_paths().config_file
    document = _existing_rewritable_document(config_path)
    for section, values in updates.items():
        document.setdefault(section, {}).update(values)
    lines: list[str] = []

    def emit_table(header: str, entries: dict[str, Any]) -> None:
        if lines:
            lines.append("")
        lines.append(f"[{header}]")
        for key, value in entries.items():
            scalar = toml_scalar(config_path, f"{header}.{key}", value)
            lines.append(f"{toml_key(key)} = {scalar}")

    for section in _REWRITABLE_SECTIONS:
        entries = document.get(section)
        if not entries:
            continue
        scalars = {k: v for k, v in entries.items() if not isinstance(v, dict)}
        subtables = {k: v for k, v in entries.items() if isinstance(v, dict)}
        if scalars:
            emit_table(section, scalars)
        for name, table in subtables.items():
            emit_table(f"{section}.{name}", table)
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
        section: dict(values) for section, values in existing.items() if isinstance(values, dict)
    }


def toml_key(key: str) -> str:
    """A bare key when TOML allows it, else a quoted key ("Groove Salad")."""
    if key and key.isascii() and all(ch.isalnum() or ch in "-_" for ch in key):
        return key
    return json.dumps(key)


def toml_scalar(path: Path, dotted_key: str, value: Any) -> str:
    """Encode a TOML scalar, or raise ConfigError for an unsupported value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    raise ConfigError(
        f"{path}: {dotted_key} has a value this app cannot rewrite; edit the file manually"
    )
