import subprocess

import pytest

from bester_ytm.intelligence import llm
from bester_ytm.intelligence.llm import IntelligenceError, IntelligenceSettings
from bester_ytm.intelligence.station_finder import (
    SuggestedStation,
    find_station,
    station_prompt,
)
from bester_ytm.tui_radio import parse_add_station_request

STATION_JSON = '{"key": "wfmu", "name": "WFMU", "stream_url": "https://stream.wfmu.org/freeform-128k"}'


def test_station_prompt_demands_direct_stream_json() -> None:
    prompt = station_prompt("WFMU")

    assert "WFMU" in prompt
    assert "DIRECT audio stream" in prompt
    assert '"stream_url"' in prompt


def test_find_station_via_codex_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        llm.subprocess,
        "run",
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
        llm.subprocess,
        "run",
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
