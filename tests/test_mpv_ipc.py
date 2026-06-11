from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest

from bester_ytm import mpv_ipc
from bester_ytm.mpv_ipc import MpvIpcClient, MpvIpcError, request_ipc


class ScriptedUnixServer:
    """Serves one canned reply per accepted connection on a unix socket."""

    def __init__(self, socket_path: Path, replies: list[bytes]) -> None:
        self.replies = replies
        self.received: list[bytes] = []
        self._server = socket.socket(socket.AF_UNIX)
        self._server.bind(str(socket_path))
        self._server.listen(len(replies))
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        for reply in self.replies:
            connection, _ = self._server.accept()
            with connection:
                self.received.append(connection.recv(4096))
                if reply:
                    connection.sendall(reply)
        self._server.close()

    def join(self) -> None:
        self._thread.join(timeout=2)


def test_request_ipc_skips_noise_and_matches_request_id(tmp_path: Path) -> None:
    socket_path = tmp_path / "mpv.sock"
    reply = (
        b"\n"
        b'"not a dict"\n'
        b'{"request_id": 99, "error": "success"}\n'
        b'{"request_id": 7, "error": "success", "data": 12.5}\n'
    )
    server = ScriptedUnixServer(socket_path, [reply])

    response = request_ipc(socket_path, {"command": ["get_property", "duration"]}, 7)
    server.join()

    assert response["data"] == 12.5
    assert b'"request_id": 7' in server.received[0]
    assert b"get_property" in server.received[0]


def test_request_ipc_raises_on_mpv_error_response(tmp_path: Path) -> None:
    socket_path = tmp_path / "mpv.sock"
    reply = b'{"request_id": 1, "error": "property unavailable"}\n'
    server = ScriptedUnixServer(socket_path, [reply])

    with pytest.raises(MpvIpcError, match="property unavailable"):
        request_ipc(socket_path, {"command": ["get_property", "volume"]}, 1)
    server.join()


def test_request_ipc_retries_after_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mpv_ipc.time, "sleep", lambda seconds: None)
    socket_path = tmp_path / "mpv.sock"
    replies = [b"not-json\n", b'{"request_id": 2, "error": "success"}\n']
    server = ScriptedUnixServer(socket_path, replies)

    response = request_ipc(socket_path, {"command": ["cycle", "pause"]}, 2)
    server.join()

    assert response["error"] == "success"
    assert len(server.received) == 2


def test_request_ipc_reconnects_after_empty_response(tmp_path: Path) -> None:
    socket_path = tmp_path / "mpv.sock"
    replies = [b"", b'{"request_id": 3, "error": "success", "data": true}\n']
    server = ScriptedUnixServer(socket_path, replies)

    response = request_ipc(socket_path, {"command": ["get_property", "mute"]}, 3)
    server.join()

    assert response["data"] is True


def test_request_ipc_times_out_without_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mpv_ipc.time, "sleep", lambda seconds: None)

    with pytest.raises(MpvIpcError, match="mpv IPC command failed"):
        request_ipc(tmp_path / "missing.sock", {"command": ["stop"]}, 1, 0.05)


class AlwaysInvalidJsonSocket:
    """Connects fine but only ever produces an undecodable reply line."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> AlwaysInvalidJsonSocket:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def settimeout(self, value: float) -> None:
        pass

    def connect(self, path: str) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        pass

    def recv(self, size: int) -> bytes:
        return b"not-json\n"


def test_request_ipc_reports_decode_error_after_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mpv_ipc.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(mpv_ipc.socket, "socket", AlwaysInvalidJsonSocket)

    with pytest.raises(MpvIpcError, match="Expecting value"):
        request_ipc(tmp_path / "mpv.sock", {"command": ["stop"]}, 1, 0.05)


def test_request_ipc_zero_deadline_reports_timeout(tmp_path: Path) -> None:
    with pytest.raises(MpvIpcError, match="timed out"):
        request_ipc(tmp_path / "mpv.sock", {"command": ["stop"]}, 1, 0.0)


def _patch_request_ipc(monkeypatch: pytest.MonkeyPatch, data: object) -> list[tuple]:
    calls: list[tuple] = []

    def fake_request_ipc(
        socket_path: Path,
        payload: dict[str, object],
        request_id: int,
        deadline_seconds: float = 2.0,
    ) -> dict[str, object]:
        calls.append((payload, request_id, deadline_seconds))
        return {"request_id": request_id, "error": "success", "data": data}

    monkeypatch.setattr(mpv_ipc, "request_ipc", fake_request_ipc)
    return calls


def test_client_increments_request_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_request_ipc(monkeypatch, data="120.5")
    client = MpvIpcClient(socket_path=Path("/tmp/unused.sock"))

    client.send({"command": ["cycle", "pause"]})
    value = client.get_float("duration", deadline_seconds=0.5)

    assert [request_id for _, request_id, _ in calls] == [1, 2]
    assert calls[1] == ({"command": ["get_property", "duration"]}, 2, 0.5)
    assert value == 120.5


def test_client_get_property_returns_raw_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_request_ipc(monkeypatch, data={"nested": 1})
    client = MpvIpcClient(socket_path=Path("/tmp/unused.sock"))

    assert client.get_property("metadata") == {"nested": 1}


def test_client_get_float_handles_missing_and_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MpvIpcClient(socket_path=Path("/tmp/unused.sock"))

    _patch_request_ipc(monkeypatch, data=None)
    assert client.get_float("time-pos") is None

    _patch_request_ipc(monkeypatch, data="not-a-number")
    assert client.get_float("time-pos") is None
