from __future__ import annotations

import threading
from typing import Any

from bester_ytm.ytm_client import YTMClient

SONG_RAW = {"videoId": "v1", "title": "Myth", "artists": [{"name": "Beach House"}]}


class LockObservingFake:
    """Fake ytmusicapi client that records whether the client lock is held.

    Each search call tries a non-blocking acquire of the client's lock; if the
    acquire succeeds the call was NOT serialized and we record a violation.
    """

    def __init__(self, lock: threading.Lock) -> None:
        self._lock = lock
        self.calls = 0
        self.violations = 0
        self.label = "fake"

    def search(
        self,
        query: str,
        filter: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self.calls += 1
        if self._lock.acquire(blocking=False):
            self.violations += 1
            self._lock.release()
        return [SONG_RAW]


def _client(fake_factory: Any = LockObservingFake) -> tuple[YTMClient, Any]:
    client = YTMClient(authenticated=False)
    fake = fake_factory(client._lock)
    client._ytmusic = fake
    client._backend = "fake"
    return client, fake


def test_ytmusic_calls_run_under_client_lock() -> None:
    client, fake = _client()

    client.search_songs("myth")

    assert fake.calls >= 1
    assert fake.violations == 0
    # The lock is released again once the call returns.
    assert client._lock.acquire(blocking=False)
    client._lock.release()


def test_overlapping_worker_calls_are_serialized() -> None:
    client, fake = _client()

    thread_count = 4
    calls_per_thread = 25
    barrier = threading.Barrier(thread_count)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait()
            for _ in range(calls_per_thread):
                assert client.search_songs("myth")[0].video_id == "v1"
        except BaseException as exc:  # noqa: BLE001 - surface thread failures
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert fake.calls >= thread_count * calls_per_thread
    assert fake.violations == 0


def test_lazy_ytmusic_init_builds_exactly_one_instance() -> None:
    client = YTMClient(authenticated=False)
    built: list[object] = []
    build_lock = threading.Lock()

    def fake_new_ytmusic() -> Any:
        with build_lock:
            built.append(object())
        return LockObservingFake(client._lock)

    client._new_ytmusic = fake_new_ytmusic  # type: ignore[method-assign]

    thread_count = 4
    barrier = threading.Barrier(thread_count)
    seen: list[Any] = []
    seen_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        proxy = client.ytmusic
        with seen_lock:
            seen.append(proxy._target)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(built) == 1
    assert len({id(target) for target in seen}) == 1


def test_proxy_passes_through_non_callable_attributes() -> None:
    client, _ = _client()

    assert client.ytmusic.label == "fake"
