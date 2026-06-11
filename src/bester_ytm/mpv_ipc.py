"""Low-level JSON IPC transport for talking to mpv over a unix socket."""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from pathlib import Path


class MpvIpcError(RuntimeError):
    pass


def request_ipc(
    socket_path: Path,
    payload: dict[str, object],
    request_id: int,
    deadline_seconds: float = 2.0,
) -> dict[str, object]:
    """Send one mpv IPC request and return the matching response.

    Opens a fresh unix connection per request, frames messages by newline,
    matches responses on request_id, and retries until the deadline.
    Raises MpvIpcError on timeout, socket failure, or an mpv error response.
    """
    request_payload = dict(payload)
    request_payload["request_id"] = request_id
    deadline = time.time() + deadline_seconds
    last_error: Exception | None = None
    encoded = json.dumps(request_payload).encode("utf-8") + b"\n"
    while time.time() < deadline:
        try:
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(deadline_seconds)
                sock.connect(str(socket_path))
                sock.sendall(encoded)
                buffer = b""
                while time.time() < deadline:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        data, buffer = buffer.split(b"\n", 1)
                        if not data:
                            continue
                        response = json.loads(data.decode("utf-8"))
                        if not isinstance(response, dict):
                            continue
                        if response.get("request_id") != request_id:
                            continue
                        error = response.get("error")
                        if error and error != "success":
                            raise MpvIpcError(f"mpv IPC command failed: {error}")
                        return response
        except (OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.05)
    raise MpvIpcError(f"mpv IPC command failed: {last_error or 'timed out'}")


@dataclass
class MpvIpcClient:
    """Per-socket request helper; never share an instance across threads."""

    socket_path: Path
    request_id: int = 0

    def request(
        self, payload: dict[str, object], deadline_seconds: float = 2.0
    ) -> dict[str, object]:
        self.request_id += 1
        return request_ipc(self.socket_path, payload, self.request_id, deadline_seconds)

    def send(self, payload: dict[str, object], deadline_seconds: float = 2.0) -> None:
        self.request(payload, deadline_seconds)

    def get_property(self, name: str, deadline_seconds: float = 2.0) -> object | None:
        response = self.request({"command": ["get_property", name]}, deadline_seconds)
        return response.get("data")

    def get_float(self, name: str, deadline_seconds: float = 2.0) -> float | None:
        value = self.get_property(name, deadline_seconds)
        if value is None:
            return None
        try:
            return float(value)  # type: ignore[arg-type]  # except clause guards bad types
        except (TypeError, ValueError):
            return None


def rms_db_from_astats(metadata: object) -> float | None:
    """Extract the overall RMS level in dB from an af-metadata/astats payload."""
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("lavfi.astats.Overall.RMS_level")
    try:
        return float(value)  # type: ignore[arg-type]  # except clause guards bad types
    except (TypeError, ValueError):
        return None
