"""Shared intelligence provider settings and errors."""

from __future__ import annotations

from dataclasses import dataclass

KNOWN_PROVIDERS = ("auto", "heuristic", "codex", "claude", "openai", "anthropic")


class IntelligenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class IntelligenceSettings:
    provider: str = "auto"
    model: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    api_key_env: str = "OPENROUTER_API_KEY"
