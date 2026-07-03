"""Ask the configured AI provider for a web radio station's stream URL."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ValidationError

from .llm import (
    DEFAULT_ANTHROPIC_MODEL,
    IntelligenceError,
    IntelligenceSettings,
    _codex_text,
    _openai_text,
    resolve_provider,
)

MANUAL_ADD_HINT = (
    "add it manually to ~/.config/bester-ytm/config.toml:\n"
    '[radio.stations]\nname = "https://direct-audio-stream-url"'
)


class SuggestedStation(BaseModel):
    key: str
    name: str
    stream_url: str


def station_prompt(request: str) -> str:
    return (
        "You are configuring a terminal music player. Find the publicly "
        f"documented live audio stream URL for the radio station: {request}\n\n"
        "Requirements:\n"
        "- stream_url must be the DIRECT audio stream endpoint (Icecast/"
        "SHOUTcast, .mp3/.aac/.ogg), playable by mpv; never a homepage, "
        "embedded player page, or .m3u/.pls playlist file.\n"
        "- Prefer https and a mid-or-high bitrate public stream.\n"
        "- key is a short lowercase slug for the station (letters/digits).\n"
        "- name is the station's proper name.\n\n"
        "Respond with ONLY a JSON object, no prose and no code fences, exactly: "
        '{"key": "...", "name": "...", "stream_url": "https://..."}'
    )


def find_station(settings: IntelligenceSettings, request: str) -> SuggestedStation:
    """The AI provider's best stream candidate; raises IntelligenceError."""
    provider = resolve_provider(settings)
    prompt = station_prompt(request)
    if provider == "codex":
        return _parse_station(_codex_text(settings, prompt), source="codex")
    if provider == "openai":
        return _parse_station(_openai_text(settings, prompt), source=settings.model)
    if provider == "anthropic":
        return _find_via_anthropic(settings, prompt)
    raise IntelligenceError(
        "the heuristic provider cannot look up stream URLs; configure "
        f"[intelligence] in config.toml, or {MANUAL_ADD_HINT}"
    )


def _find_via_anthropic(settings: IntelligenceSettings, prompt: str) -> SuggestedStation:
    try:
        import anthropic
    except ImportError as exc:
        raise IntelligenceError("the anthropic package is not installed; run uv sync") from exc
    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=settings.model or DEFAULT_ANTHROPIC_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            output_format=SuggestedStation,
        )
    except anthropic.AnthropicError as exc:
        raise IntelligenceError(f"Anthropic API request failed: {exc}") from exc
    if response.parsed_output is None:
        raise IntelligenceError("the Anthropic API returned no station suggestion")
    return response.parsed_output


def _parse_station(raw_output: str, source: str) -> SuggestedStation:
    for line in reversed(raw_output.strip().splitlines()):
        station = _load_station(line.strip())
        if station is not None:
            return station
    match = re.search(r"\{.*\}", raw_output, flags=re.DOTALL)
    if match:
        station = _load_station(match.group(0))
        if station is not None:
            return station
    raise IntelligenceError(
        f"{source} returned no station JSON (got: {raw_output.strip()[:160]!r})"
    )


def _load_station(text: str) -> SuggestedStation | None:
    if not text.startswith("{"):
        return None
    try:
        return SuggestedStation.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError):
        return None
