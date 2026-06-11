"""Playback subcommands: play video, search, and playlist through mpv."""

from __future__ import annotations

import time
from typing import Annotated, NoReturn

import typer
from rich.console import Console

from .config import ConfigError, load_transition_settings
from .playback import PlaybackController, PlaybackError
from .playlist_plan import PlannedTrack
from .resolver import Resolver
from .transitions import TransitionSettings, TransitionStyle
from .ytm_client import YTMClient, YTMClientError

console = Console()
play_app = typer.Typer(help="Play YouTube Music audio through mpv.")


def _exit_error(message: str, code: int = 1) -> NoReturn:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(code)


def _effective_transition_settings(
    transition: TransitionStyle | None, fade: float | None
) -> TransitionSettings:
    try:
        settings = load_transition_settings()
    except ConfigError as exc:
        _exit_error(str(exc))
    if transition is not None:
        settings = TransitionSettings(style=transition, fade_seconds=settings.fade_seconds)
    if fade is not None:
        settings = TransitionSettings(style=settings.style, fade_seconds=fade)
    return settings.clamped()


def _play_and_wait(controller: PlaybackController, seconds: int | None) -> None:
    if seconds:
        return
    try:
        if controller.transition.style is TransitionStyle.CUT:
            _wait_until_queue_done(controller)
        else:
            _tick_until_done(controller)
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    finally:
        # Always reap mpv decks and their sockets, however the wait ended.
        controller.stop()


def _wait_until_queue_done(controller: PlaybackController) -> None:
    while controller.process:
        controller.process.wait()
        if controller.queue:
            controller.next()
        else:
            break


def _tick_until_done(controller: PlaybackController) -> None:
    while True:
        controller.tick()
        _report_transition_error(controller)
        process = controller.process
        if process is None:
            return
        if process.poll() is not None:
            # Dead live deck: cut fallback; the engine never advances on death.
            if controller.queue:
                controller.next()
            else:
                return
        time.sleep(0.5)


def _report_transition_error(controller: PlaybackController) -> None:
    error = controller.consume_transition_error()
    if error:
        console.print(f"[yellow]Mix failed; using cut: {error}[/yellow]")


@play_app.command("video")
def play_video(
    video_id: Annotated[str, typer.Argument(help="YouTube Music videoId.")],
    seconds: Annotated[int | None, typer.Option("--seconds", min=1)] = None,
) -> None:
    controller = PlaybackController()
    try:
        controller.play_video(video_id, seconds=seconds)
        console.print(f"Playing {video_id} through mpv.")
        _play_and_wait(controller, seconds)
    except PlaybackError as exc:
        _exit_error(str(exc))


@play_app.command("search")
def play_search(
    query: Annotated[str, typer.Argument(help="Search query such as 'artist title'.")],
    seconds: Annotated[int | None, typer.Option("--seconds", min=1)] = None,
) -> None:
    try:
        candidates = YTMClient(authenticated=False).search_songs(query, limit=8)
    except YTMClientError as exc:
        _exit_error(str(exc))
    target = PlannedTrack(
        artist="",
        title=query,
        reason="Playback search target.",
        role="search",
        query=query,
    )
    best = Resolver().select_best(target, candidates)
    if best is None:
        _exit_error(f"No playable YouTube Music result found for {query!r}")
    console.print(
        f"Selected {best.candidate.display_name} "
        f"({best.candidate.video_id}, confidence {best.score:.2f})."
    )
    controller = PlaybackController()
    try:
        controller.play_video(best.candidate.video_id, seconds=seconds)
        _play_and_wait(controller, seconds)
    except PlaybackError as exc:
        _exit_error(str(exc))


@play_app.command("playlist")
def play_playlist(
    playlist_id: Annotated[str, typer.Argument(help="YouTube Music playlist id.")],
    seconds: Annotated[int | None, typer.Option("--seconds", min=1)] = None,
    transition: Annotated[
        TransitionStyle | None,
        typer.Option("--transition", help="Transition style: cut or crossfade."),
    ] = None,
    fade: Annotated[
        float | None,
        typer.Option("--fade", min=1.0, max=15.0, help="Crossfade length in seconds."),
    ] = None,
) -> None:
    settings = _effective_transition_settings(transition, fade)
    try:
        snapshot = YTMClient(authenticated=True).get_playlist(playlist_id)
    except (ConfigError, YTMClientError) as exc:
        _exit_error(str(exc))
    if not snapshot.video_ids:
        _exit_error(f"Playlist {playlist_id} has no playable tracks.")
    controller = PlaybackController(transition=settings)
    try:
        if seconds:
            controller.play_video(snapshot.video_ids[0], seconds=seconds)
        else:
            controller.enqueue(snapshot.video_ids)
            controller.play_queue()
        console.print(f"Playing playlist {playlist_id} ({len(snapshot.video_ids)} tracks).")
        _play_and_wait(controller, seconds)
    except PlaybackError as exc:
        _exit_error(str(exc))
