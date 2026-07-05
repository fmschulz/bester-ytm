from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .auth import AuthManager
from .cli_config import config_app
from .cli_play import play_app
from .config import ConfigError
from .playlist_builder import PlaylistBuilder, PlaylistBuildError
from .playlist_create import PlaylistCreateError, create_or_update_playlist
from .stores import FavoritesStore, PlanStore
from .ytm_client import YTMClient, YTMClientError

console = Console()
app = typer.Typer(no_args_is_help=False, help="Local YouTube Music terminal companion.")
auth_app = typer.Typer(help="Authenticate with YouTube Music.")
playlist_app = typer.Typer(help="Build, create, and export playlist plans.")
favorites_app = typer.Typer(help="Manage local favorites.")

app.add_typer(auth_app, name="auth")
app.add_typer(play_app, name="play")
app.add_typer(playlist_app, name="playlist")
app.add_typer(favorites_app, name="favorites")
app.add_typer(config_app, name="config")


def _exit_error(message: str, code: int = 1) -> None:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(code)


def _print_candidates(query: str, candidates: Sequence[object]) -> None:
    table = Table(title=f"Search: {query}")
    table.add_column("#", justify="right")
    table.add_column("Video ID")
    table.add_column("Artist")
    table.add_column("Title")
    table.add_column("Duration", justify="right")
    for index, candidate in enumerate(candidates, start=1):
        duration = ""
        seconds = getattr(candidate, "duration_seconds", None)
        if seconds:
            duration = f"{seconds // 60}:{seconds % 60:02d}"
        table.add_row(
            str(index),
            getattr(candidate, "video_id", ""),
            getattr(candidate, "artist_text", ""),
            getattr(candidate, "title", ""),
            duration,
        )
    console.print(table)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from .tui import run_tui

        run_tui()


@auth_app.command("login")
def auth_login(
    browser: Annotated[
        str | None,
        typer.Option(
            "--browser",
            help="Read the login from this browser's cookies (e.g. firefox, "
            "chrome, chromium, brave, edge, vivaldi, opera, safari).",
        ),
    ] = None,
    paste: Annotated[
        bool,
        typer.Option(
            "--paste",
            help="Paste a DevTools 'Copy as cURL' command (or raw request "
            "headers) instead of reading browser cookies.",
        ),
    ] = False,
    cookies_file: Annotated[
        Path | None,
        typer.Option(
            "--cookies-file",
            help="Read the login from a Netscape cookies.txt export.",
        ),
    ] = None,
    oauth: Annotated[
        bool,
        typer.Option(
            "--oauth",
            help="Use Google Cloud OAuth credentials (self-refreshing token) "
            "instead of browser cookies.",
        ),
    ] = False,
    no_browser: Annotated[
        bool,
        typer.Option(
            "--no-browser",
            help="With --oauth: do not try to open the web browser automatically.",
        ),
    ] = False,
) -> None:
    sources = [flag for flag in (browser, paste or None, cookies_file, oauth or None) if flag]
    if len(sources) > 1:
        _exit_error("Use only one of --browser, --paste, --cookies-file, and --oauth.")
    manager = AuthManager()
    try:
        if oauth:
            token_path = manager.login(open_browser=not no_browser)
            console.print(f"[green]OAuth token saved:[/green] {token_path}")
        else:
            auth_path = manager.login_browser(
                browser=browser, cookies_file=cookies_file, paste=paste
            )
            console.print(f"[green]Browser login saved:[/green] {auth_path}")
            if manager.paths.oauth_token.exists():
                console.print(
                    f"Note: the OAuth token at {manager.paths.oauth_token} takes "
                    "precedence; delete it to use the browser login."
                )
    except ConfigError as exc:
        _exit_error(str(exc))
    console.print("Verify with: bester-ytm auth status")


@auth_app.command("status")
def auth_status() -> None:
    try:
        status = YTMClient(authenticated=True).auth_status()
    except ConfigError as exc:
        _exit_error(str(exc))
    console.print(status.message)
    console.print(f"backend: {status.backend or 'unknown'}")
    console.print(f"authenticated: {status.authenticated}")
    console.print(f"library playlists seen: {status.library_playlists_seen}")
    if status.sample_playlists:
        console.print("sample library playlist: " + ", ".join(status.sample_playlists))
    if not status.authenticated:
        raise typer.Exit(1)


@auth_app.command("logout")
def auth_logout(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    if not yes and not typer.confirm(
        "Delete the saved YouTube Music logins (oauth.json and browser.json)?"
    ):
        raise typer.Exit(1)
    removed = AuthManager().logout()
    console.print("Saved logins removed." if removed else "No saved logins were present.")


@app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Search query such as 'artist title'.")],
    limit: Annotated[int, typer.Option("--limit", "-l", min=1, max=25)] = 10,
) -> None:
    """Search YouTube Music for songs."""
    try:
        candidates = YTMClient(authenticated=False).search_songs(query, limit=limit)
    except YTMClientError as exc:
        _exit_error(str(exc))
    _print_candidates(query, candidates)


@playlist_app.command("build")
def playlist_build(
    source: Annotated[
        Path,
        typer.Option("--from", "-f", help="Favorites markdown or text input file."),
    ],
    name: Annotated[str, typer.Option("--name", "-n")],
    count: Annotated[int, typer.Option("--count", "-c", min=1, max=200)] = 30,
    brief: Annotated[
        str,
        typer.Option("--brief", help="Free-form playlist prompt or constraints."),
    ] = "",
    allow_variants: Annotated[
        bool,
        typer.Option("--allow-variants", help="Allow obvious live/remix/cover candidates."),
    ] = False,
) -> None:
    try:
        plan = PlaylistBuilder(allow_variants=allow_variants).build_from_favorites(
            source=source,
            name=name,
            count=count,
            brief=brief,
        )
    except PlaylistBuildError as exc:
        _exit_error(str(exc))
    json_path, md_path = PlanStore().save(plan)
    console.print(f"[green]Plan saved:[/green] {plan.id}")
    console.print(f"JSON: {json_path}")
    console.print(f"Markdown: {md_path}")
    console.print(f"Resolved: {plan.resolved_count}/{len(plan.planned_tracks)}")
    if plan.resolved_count < plan.target_count:
        console.print(
            "[yellow]Some tracks are unresolved; inspect the plan before creating.[/yellow]"
        )


@playlist_app.command("create")
def playlist_create(
    plan_id: Annotated[str, typer.Argument(help="Plan id, prefix, or JSON path.")],
    privacy: Annotated[
        str,
        typer.Option("--privacy", help="PRIVATE, UNLISTED, or PUBLIC."),
    ] = "PRIVATE",
) -> None:
    store = PlanStore()
    try:
        plan = store.load(plan_id)
    except (FileNotFoundError, FileExistsError) as exc:
        _exit_error(str(exc))
    try:
        client = YTMClient(authenticated=True)
        result = create_or_update_playlist(plan, client, store, privacy=privacy)
        if result.created:
            console.print(f"Created playlist: {result.playlist_id}")
        else:
            console.print(
                f"Updated {result.playlist_id}: "
                f"requested {len(result.requested_video_ids)} track(s)."
            )
    except (ConfigError, PlaylistCreateError, YTMClientError) as exc:
        _exit_error(str(exc))

    if not result.verified:
        _exit_error(
            "Playlist verification failed; missing "
            f"{len(result.missing_video_ids)} expected track(s)."
        )
    present = len(result.requested_video_ids) - len(result.missing_video_ids)
    console.print(
        f"[green]Verified playlist contains expected tracks:[/green] "
        f"{present}/{len(result.requested_video_ids)}"
    )


@playlist_app.command("export")
def playlist_export(
    plan_id: Annotated[str, typer.Argument(help="Plan id, prefix, or JSON path.")],
    fmt: Annotated[
        str,
        typer.Option("--format", help="Export format: md or json."),
    ] = "md",
) -> None:
    if fmt not in {"md", "json"}:
        _exit_error("--format must be md or json")
    try:
        sys.stdout.write(PlanStore().export(plan_id, fmt))
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        _exit_error(str(exc))


@favorites_app.command("import-tuiradio")
def favorites_import_tuiradio(
    source: Annotated[
        Path,
        typer.Argument(help="Path to tuiradio favs.md."),
    ],
) -> None:
    try:
        from .config import resolve_existing_input

        count = FavoritesStore().import_tuiradio(resolve_existing_input(source))
    except ConfigError as exc:
        _exit_error(str(exc))
    console.print(f"Imported {count} favorites.")
