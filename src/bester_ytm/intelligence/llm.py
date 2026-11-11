"""AI track suggestions from the codex or claude CLI, an OpenAI-compatible API, or Anthropic."""

from __future__ import annotations

import json
import os
import re
import shutil
from threading import Event

import requests
from pydantic import BaseModel, ValidationError

from . import cli_providers
from .settings import KNOWN_PROVIDERS, IntelligenceError, IntelligenceSettings

HTTP_TIMEOUT_SECONDS = 90.0
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"


class SuggestedTrack(BaseModel):
    artist: str
    title: str
    reason: str = ""


class SuggestedTracks(BaseModel):
    tracks: list[SuggestedTrack]
    name: str = ""


def resolve_provider(settings: IntelligenceSettings) -> str:
    provider = settings.provider.strip().lower() or "auto"
    if provider not in KNOWN_PROVIDERS:
        raise IntelligenceError(
            f"unknown intelligence provider {provider!r}; use one of {', '.join(KNOWN_PROVIDERS)}"
        )
    if provider != "auto":
        return provider
    if shutil.which("codex"):
        return "codex"
    if shutil.which("claude"):
        return "claude"
    return "heuristic"


def suggest_tracks(
    settings: IntelligenceSettings,
    context_lines: list[str],
    count: int,
    brief: str = "",
    *,
    cancel: Event | None = None,
) -> list[SuggestedTrack]:
    """Ask the configured AI provider for track suggestions; raises IntelligenceError."""
    return suggest_playlist(settings, context_lines, count, brief, cancel=cancel).tracks


def suggest_playlist(
    settings: IntelligenceSettings,
    context_lines: list[str],
    count: int,
    brief: str = "",
    *,
    cancel: Event | None = None,
) -> SuggestedTracks:
    """Ask the configured AI provider for a named track list; raises IntelligenceError."""
    provider = resolve_provider(settings)
    prompt = build_prompt(context_lines, count, brief)
    if provider == "codex":
        return _parse_playlist(
            cli_providers.codex_text(settings, prompt, cancel=cancel), source="codex"
        )
    if provider == "claude":
        return _parse_playlist(
            cli_providers.claude_text(settings, prompt, cancel=cancel), source="claude"
        )
    if provider == "openai":
        return _suggest_via_openai(settings, prompt)
    if provider == "anthropic":
        return _suggest_via_anthropic(settings, prompt)
    raise IntelligenceError(
        "the heuristic provider has no AI suggestions; configure [intelligence] "
        "in config.toml (provider = codex, claude, openai, or anthropic)"
    )


def build_prompt(context_lines: list[str], count: int, brief: str) -> str:
    parts = [
        f"You are selecting music. Suggest exactly {count} songs that plausibly "
        "exist on YouTube Music."
    ]
    if context_lines:
        queue = "\n".join(f"- {line}" for line in context_lines)
        parts.append(f"The listener's current queue:\n{queue}")
        parts.append(
            "Favor stylistic neighbors that fit the queue's mood and era; do not "
            "repeat queued songs and avoid suggesting only the same artists."
        )
    if brief:
        parts.append(f"Listener brief: {brief}")
    parts.append(
        "Prefer studio recordings over live, cover, karaoke, or remix versions. "
        "If the request says to save, name, or call the playlist something "
        "specific, use exactly that as the playlist name; otherwise invent a "
        "short fitting name of at most five words. "
        "Respond with ONLY a JSON object, no prose and no code fences, exactly: "
        '{"name": "...", "tracks": [{"artist": "...", "title": "...", "reason": "..."}]}'
    )
    return "\n\n".join(parts)


def _suggest_via_openai(settings: IntelligenceSettings, prompt: str) -> SuggestedTracks:
    return _parse_playlist(_openai_text(settings, prompt), source=settings.model)


def _openai_text(settings: IntelligenceSettings, prompt: str) -> str:
    """Raw chat-completion text for a prompt; raises IntelligenceError."""
    api_key = os.environ.get(settings.api_key_env, "")
    if not api_key:
        raise IntelligenceError(
            f"environment variable {settings.api_key_env} is not set; it must hold "
            f"the API key for {settings.base_url}"
        )
    if not settings.model:
        raise IntelligenceError(
            "[intelligence] model must be set for the openai provider "
            "(e.g. an OpenRouter slug or a local model name)"
        )
    url = settings.base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, object] = {
        "model": settings.model,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        response = requests.post(
            url,
            json=payload,  # type: ignore[arg-type]  # JsonType is stricter than needed
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])
    except requests.RequestException as exc:
        raise IntelligenceError(f"request to {url} failed: {exc}") from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise IntelligenceError(f"unexpected response shape from {url}: {exc}") from exc


def _suggest_via_anthropic(settings: IntelligenceSettings, prompt: str) -> SuggestedTracks:
    try:
        import anthropic
    except ImportError as exc:
        raise IntelligenceError("the anthropic package is not installed; run uv sync") from exc
    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=settings.model or DEFAULT_ANTHROPIC_MODEL,
            max_tokens=16000,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
            output_format=SuggestedTracks,
        )
    except anthropic.AnthropicError as exc:
        raise IntelligenceError(
            f"Anthropic API request failed: {exc}. Set ANTHROPIC_API_KEY to use "
            "the anthropic provider."
        ) from exc
    if response.stop_reason == "refusal":
        raise IntelligenceError("the Anthropic API declined this request")
    parsed = response.parsed_output
    if parsed is None or not parsed.tracks:
        raise IntelligenceError("the Anthropic API returned no track suggestions")
    return parsed


def _parse_playlist(raw_output: str, source: str) -> SuggestedTracks:
    payload = _extract_json_payload(raw_output)
    if payload is None:
        raise IntelligenceError(
            f"{source} returned no JSON track list (got: {raw_output.strip()[:160]!r})"
        )
    if isinstance(payload, dict):
        name = str(payload.get("name") or "").strip()
        raw_tracks = payload.get("tracks")
        items = raw_tracks if isinstance(raw_tracks, list) else []
    else:
        name = ""
        items = payload
    try:
        tracks = [SuggestedTrack.model_validate(item) for item in items]
    except ValidationError as exc:
        raise IntelligenceError(f"{source} returned malformed track entries: {exc}") from exc
    if not tracks:
        raise IntelligenceError(f"{source} returned an empty track list")
    return SuggestedTracks(name=name, tracks=tracks)


def _extract_json_payload(raw_output: str) -> dict[str, object] | list[object] | None:
    """The track payload: a {"name", "tracks"} object or a legacy bare array."""
    for line in reversed(raw_output.strip().splitlines()):
        candidate = _load_json_payload(line.strip())
        if candidate is not None:
            return candidate
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, raw_output, flags=re.DOTALL)
        if match:
            candidate = _load_json_payload(match.group(0))
            if candidate is not None:
                return candidate
    return None


def _load_json_payload(text: str) -> dict[str, object] | list[object] | None:
    if not text.startswith(("[", "{")):
        return None
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(loaded, dict):
        return loaded if isinstance(loaded.get("tracks"), list) else None
    return loaded if isinstance(loaded, list) else None
