"""A single mpv deck used for prebuffering and draining during transitions."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .local_files import is_local_video_id, local_path
from .mpv_ipc import MpvIpcClient, MpvIpcError

PROBE_DEADLINE_SECONDS = 0.15
KILL_ESCALATION_SECONDS = 5.0


class DeckState(StrEnum):
    LOADING = "loading"
    READY = "ready"
    LIVE = "live"
    DRAINING = "draining"
    STOPPED = "stopped"


def video_url(video_id: str) -> str:
    if is_local_video_id(video_id):
        return local_path(video_id)
    return f"https://music.youtube.com/watch?v={video_id}"


def terminate_process(process: subprocess.Popen[str]) -> None:
    """Terminate an mpv process, escalating to kill after a grace period."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def remove_socket_file(ipc_socket: Path) -> None:
    """Best-effort unlink of an IPC socket that may already be gone."""
    if not ipc_socket.exists():
        return
    try:
        ipc_socket.unlink()
    except OSError:
        pass


@dataclass
class Deck:
    name: str
    video_id: str
    process: subprocess.Popen[str]
    ipc_socket: Path
    client: MpvIpcClient = field(init=False)
    state: DeckState = DeckState.LOADING

    def __post_init__(self) -> None:
        self.client = MpvIpcClient(socket_path=self.ipc_socket)

    def is_process_running(self) -> bool:
        return self.process.poll() is None

    def refresh_readiness(self) -> bool:
        if self.state is not DeckState.LOADING:
            return self.state is DeckState.READY
        if not self.ipc_socket.exists():
            return False
        try:
            duration = self.client.get_float("duration", PROBE_DEADLINE_SECONDS)
        except MpvIpcError:
            return False
        if duration is None or duration <= 0:
            return False
        self.state = DeckState.READY
        return True

    def set_volume(self, volume: float, deadline_seconds: float = 2.0) -> None:
        clamped = max(0.0, min(100.0, volume))
        self.client.send(
            {"command": ["set_property", "volume", clamped]}, deadline_seconds
        )

    def set_paused(self, paused: bool, deadline_seconds: float = 2.0) -> None:
        self.client.send(
            {"command": ["set_property", "pause", paused]}, deadline_seconds
        )

    def set_muted(self, muted: bool, deadline_seconds: float = 2.0) -> None:
        self.client.send(
            {"command": ["set_property", "mute", muted]}, deadline_seconds
        )

    def stop(self) -> None:
        terminate_process(self.process)
        remove_socket_file(self.ipc_socket)
        self.state = DeckState.STOPPED


def deck_socket_path(name: str) -> Path:
    socket_name = f"bester-ytm-mpv-{os.getpid()}-deck-{name.lower()}.sock"
    return Path(tempfile.gettempdir()) / socket_name


def spawn_mpv(
    mpv_path: str,
    video_id: str,
    ipc_socket: Path,
    *,
    paused: bool,
    volume: float,
) -> subprocess.Popen[str]:
    """Launch a detached audio-only mpv playing one YouTube Music track."""
    cmd = [
        mpv_path,
        "--no-terminal",
        "--input-terminal=no",
        "--no-video",
        "--ytdl-format=bestaudio",
        # Exposes live loudness via the af-metadata/astats property for visuals.
        # asetnsamples widens each measurement to ~43ms so the visual-fps poll
        # hears nearly all of the audio; bare reset=1 reports one ~20ms decoder
        # frame per poll, which aliases against the beat.
        "--af=@astats:lavfi=[asetnsamples=n=2048,astats=metadata=1:reset=1]",
        f"--pause={'yes' if paused else 'no'}",
        f"--volume={volume:g}",
        f"--input-ipc-server={ipc_socket}",
        video_url(video_id),
    ]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def spawn_prebuffer_deck(name: str, video_id: str, mpv_path: str) -> Deck:
    """Spawn a paused, silent mpv for video_id; readiness is polled by tick()."""
    ipc_socket = deck_socket_path(name)
    if ipc_socket.exists():
        try:
            ipc_socket.unlink()
        except OSError as exc:
            raise MpvIpcError(
                f"could not remove stale deck socket {ipc_socket}: {exc}"
            ) from exc
    try:
        process = spawn_mpv(mpv_path, video_id, ipc_socket, paused=True, volume=0.0)
    except OSError as exc:
        raise MpvIpcError(f"failed to spawn mpv deck {name}: {exc}") from exc
    return Deck(name=name, video_id=video_id, process=process, ipc_socket=ipc_socket)


@dataclass
class DyingDeck:
    deck: Deck
    retired_at: float
    killed: bool = False


@dataclass
class DeckReaper:
    """Retires decks without ever blocking the caller.

    retire() sends SIGTERM and frees the socket path immediately (unlinking
    the file does not disturb the running mpv, and frees the deck name for
    reuse); reap() polls dying processes on subsequent ticks, escalating to
    SIGKILL after a grace period. flush() is the blocking final sweep for
    shutdown, preserving the both-decks-are-always-reaped invariant.
    """

    clock: Callable[[], float] = time.monotonic
    dying: list[DyingDeck] = field(default_factory=list)

    def retire(self, deck: Deck) -> None:
        deck.state = DeckState.STOPPED
        remove_socket_file(deck.ipc_socket)
        if deck.process.poll() is not None:
            return
        deck.process.terminate()
        self.dying.append(DyingDeck(deck=deck, retired_at=self.clock()))

    def reap(self) -> None:
        self.dying = [dying for dying in self.dying if self._still_dying(dying)]

    def flush(self) -> None:
        # Sockets were already unlinked in retire(); the path may since have
        # been reused by a newer deck, so only the processes are touched here.
        for dying in self.dying:
            terminate_process(dying.deck.process)
        self.dying = []

    def _still_dying(self, dying: DyingDeck) -> bool:
        if dying.deck.process.poll() is not None:
            return False
        if not dying.killed and self.clock() - dying.retired_at >= KILL_ESCALATION_SECONDS:
            dying.deck.process.kill()
            dying.killed = True
        return True
