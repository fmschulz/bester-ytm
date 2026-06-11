from __future__ import annotations

import typer
from rich.console import Console

from .config import ConfigError, get_paths, load_transition_settings

console = Console(soft_wrap=True)
config_app = typer.Typer(help="Inspect bester-ytm configuration.")


@config_app.command("show")
def config_show() -> None:
    """Print the effective playback configuration as a paste-ready TOML snippet."""

    config_path = get_paths().config_file
    try:
        settings = load_transition_settings()
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    state = "(loaded)" if config_path.exists() else "(missing; defaults in effect)"
    snippet = (
        f"config file: {config_path} {state}\n"
        "\n"
        "[playback]\n"
        f'transition = "{settings.style.value}"\n'
        f"fade_seconds = {float(settings.fade_seconds)!r}"
    )
    console.print(snippet, markup=False)
