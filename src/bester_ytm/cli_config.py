from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .config import (
    ConfigError,
    get_paths,
    load_config_document,
    load_intelligence_settings,
    load_transition_settings,
    toml_key,
    toml_scalar,
)
from .config_options import load_app_options

console = Console(soft_wrap=True)
config_app = typer.Typer(help="Inspect bester-ytm configuration.")


@config_app.command("show")
def config_show() -> None:
    """Print all effective settings as a paste-ready TOML document."""

    config_path = get_paths().config_file
    try:
        sections = _effective_settings(config_path)
        state = "(loaded)" if config_path.exists() else "(missing; defaults in effect)"
        lines = [f"# config file: {config_path} {state}"]
        for section, values in sections.items():
            if not values:
                continue
            lines.extend(["", f"[{section}]"])
            for key, value in values.items():
                scalar = toml_scalar(config_path, f"{section}.{key}", value)
                lines.append(f"{toml_key(key)} = {scalar}")
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print("\n".join(lines), markup=False, highlight=False)


def _effective_settings(path: Path) -> dict[str, dict[str, object]]:
    transition = load_transition_settings(path)
    options = load_app_options(path)
    intelligence = load_intelligence_settings(path)
    sections: dict[str, dict[str, object]] = {
        "playback": {
            "transition": transition.style.value,
            "fade_seconds": float(transition.fade_seconds),
            "volume": options.volume,
        },
        "ui": {
            "visualizer": options.visualizer,
            "theme": options.theme,
            "visual_fps": options.visual_fps,
        },
        "builder": {},
        "intelligence": {
            "provider": intelligence.provider,
            "model": intelligence.model,
            "base_url": intelligence.base_url,
            "api_key_env": intelligence.api_key_env,
        },
    }
    for name, width in (("left_width", options.left_width), ("right_width", options.right_width)):
        if width is not None:
            sections["ui"][name] = width
    if options.favorites_file is not None:
        sections["builder"]["favorites_file"] = str(options.favorites_file)
    radio = load_config_document(path).get("radio", {})
    if isinstance(radio, dict) and isinstance(radio.get("stations"), dict):
        sections["radio.stations"] = radio["stations"]
    return sections
