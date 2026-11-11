"""Run AI CLIs with bounded waits, pipe draining, and optional cancellation."""

from __future__ import annotations

import subprocess
from threading import Event
from time import monotonic


class CliCancelledError(RuntimeError):
    """The caller cancelled a CLI request."""


def run_cli(
    cmd: list[str], *, timeout: float, cancel: Event | None = None
) -> subprocess.CompletedProcess[str]:
    """Drain both pipes while checking cancellation and the total timeout."""
    if cancel is not None and cancel.is_set():
        raise CliCancelledError("Playlist build cancelled.")
    deadline = monotonic() + timeout
    process = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise CliCancelledError("Playlist build cancelled.")
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                continue
            return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    except BaseException:
        _stop_process(process)
        raise


def _stop_process(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.communicate(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
