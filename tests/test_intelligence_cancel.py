"""CLI cancellation and timeout cleanup with a fake process and clock."""

from __future__ import annotations

import subprocess
from threading import Event
from unittest.mock import Mock

import pytest

from bester_ytm.intelligence import cli_process, llm
from bester_ytm.intelligence.settings import IntelligenceError, IntelligenceSettings


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_cancelled_cli_terminates_and_reaps_process(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    cancel = Event()
    process = Mock(returncode=-15)

    def communicate(*, timeout: float) -> tuple[str, str]:
        if not cancel.is_set():
            cancel.set()
            raise subprocess.TimeoutExpired(provider, timeout)
        return "", ""

    process.communicate.side_effect = communicate
    monkeypatch.setattr(llm.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    with pytest.raises(IntelligenceError, match="cancelled"):
        llm.suggest_playlist(IntelligenceSettings(provider=provider), [], 1, cancel=cancel)
    process.terminate.assert_called_once()
    assert process.communicate.call_count == 2


def test_pre_cancelled_cli_does_not_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = Event()
    cancel.set()
    popen = Mock()
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(llm.shutil, "which", lambda name: f"/bin/{name}")
    with pytest.raises(IntelligenceError, match="cancelled"):
        llm.suggest_playlist(IntelligenceSettings(provider="codex"), [], 1, cancel=cancel)
    popen.assert_not_called()


def test_cli_timeout_stops_and_reaps_process(monkeypatch: pytest.MonkeyPatch) -> None:
    process = Mock(returncode=-15)
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(cli_process, "monotonic", Mock(side_effect=[0.0, 180.0]))
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        cli_process.run_cli(["codex"], timeout=180.0)
    assert raised.value.timeout == 180.0
    process.terminate.assert_called_once()
    process.communicate.assert_called_once_with(timeout=1.0)


def test_cancel_kills_process_that_ignores_terminate(monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = Event()
    process = Mock(returncode=-9)

    def communicate(**kwargs: float) -> tuple[str, str]:
        if "timeout" in kwargs:
            cancel.set()
            raise subprocess.TimeoutExpired("claude", kwargs["timeout"])
        return "", ""

    process.communicate.side_effect = communicate
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    with pytest.raises(cli_process.CliCancelledError):
        cli_process.run_cli(["claude"], timeout=180.0, cancel=cancel)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.communicate.call_count == 3
