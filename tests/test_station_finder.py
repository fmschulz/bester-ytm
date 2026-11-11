from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import anthropic
import pytest

from bester_ytm.intelligence import cli_providers, llm
from bester_ytm.intelligence.settings import IntelligenceError, IntelligenceSettings
from bester_ytm.intelligence.station_finder import (
    SuggestedStation,
    find_station,
    station_prompt,
)
from bester_ytm.tui_radio import parse_add_station_request

STATION_JSON = (
    '{"key": "wfmu", "name": "WFMU", "stream_url": "https://stream.wfmu.org/freeform-128k"}'
)


def test_station_prompt_demands_direct_stream_json() -> None:
    prompt = station_prompt("WFMU")

    assert "WFMU" in prompt
    assert "DIRECT audio stream" in prompt
    assert '"stream_url"' in prompt


def test_find_station_via_codex_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        cli_providers,
        "run_cli",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout=f"thinking...\n{STATION_JSON}\n", stderr=""
        ),
    )

    station = find_station(IntelligenceSettings(provider="codex"), "WFMU")

    assert station == SuggestedStation(
        key="wfmu", name="WFMU", stream_url="https://stream.wfmu.org/freeform-128k"
    )


def test_find_station_rejects_non_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        cli_providers,
        "run_cli",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout="I could not find it, sorry.", stderr=""
        ),
    )

    with pytest.raises(IntelligenceError, match="no station JSON"):
        find_station(IntelligenceSettings(provider="codex"), "WFMU")


def test_find_station_heuristic_gives_manual_instructions() -> None:
    with pytest.raises(IntelligenceError, match=r"\[radio.stations\]"):
        find_station(IntelligenceSettings(provider="heuristic"), "WFMU")


def test_parse_add_station_request_variants() -> None:
    assert parse_add_station_request("add radio station WFMU") == "WFMU"
    assert parse_add_station_request("Add radiostation kexp!") == "kexp"
    assert parse_add_station_request("please add the web radio FIP") == "FIP"
    assert parse_add_station_request("add radio Radio Paradise") == "Radio Paradise"
    assert parse_add_station_request("10 songs like beach house") is None
    assert parse_add_station_request("add these songs to a playlist") is None


def test_find_station_via_claude_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(
        cli_providers,
        "run_cli",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout=STATION_JSON, stderr=""
        ),
    )

    station = find_station(IntelligenceSettings(provider="claude"), "WFMU")

    assert station.key == "wfmu"


@pytest.mark.parametrize("model", ["", "sonnet"])
def test_claude_station_lookup_allows_only_web_tools(
    monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=STATION_JSON, stderr=""))
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(cli_providers, "run_cli", run)

    find_station(IntelligenceSettings(provider="claude", model=model), "WFMU")

    expected = [
        "/usr/bin/claude",
        "-p",
        "--output-format",
        "text",
        "--setting-sources",
        "",
        "--tools",
        "WebSearch,WebFetch",
        "--allowedTools",
        "WebSearch,WebFetch",
        "--disable-slash-commands",
        "--strict-mcp-config",
    ]
    if model:
        expected += ["--model", model]
    assert run.call_args.args[0] == [*expected, station_prompt("WFMU")]


@pytest.mark.parametrize("model", ["", "chosen-model"])
def test_anthropic_station_request_uses_structured_output(
    monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    station = SuggestedStation.model_validate_json(STATION_JSON)
    parse = Mock(return_value=SimpleNamespace(stop_reason="end_turn", parsed_output=station))
    monkeypatch.setattr(
        anthropic, "Anthropic", lambda: SimpleNamespace(messages=SimpleNamespace(parse=parse))
    )

    assert find_station(IntelligenceSettings(provider="anthropic", model=model), "WFMU") == station
    assert parse.call_args.kwargs == {
        "model": model or "claude-opus-5-5",
        "max_tokens": 16000,
        "output_config": {"effort": "low"},
        "messages": [{"role": "user", "content": station_prompt("WFMU")}],
        "output_format": SuggestedStation,
    }


@pytest.mark.parametrize("station_request", [False, True])
def test_anthropic_refusal_is_reported_before_parsing(
    monkeypatch: pytest.MonkeyPatch, station_request: bool
) -> None:
    class Refusal:
        stop_reason = "refusal"

        @property
        def parsed_output(self) -> None:
            pytest.fail("Refusal must be checked before reading parsed_output")

    parse = Mock(return_value=Refusal())
    monkeypatch.setattr(
        anthropic, "Anthropic", lambda: SimpleNamespace(messages=SimpleNamespace(parse=parse))
    )
    settings = IntelligenceSettings(provider="anthropic")
    with pytest.raises(IntelligenceError, match="^the Anthropic API declined this request$"):
        if station_request:
            find_station(settings, "WFMU")
        else:
            llm.suggest_playlist(settings, [], 1)
