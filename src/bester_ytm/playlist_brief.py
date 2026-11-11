"""Parse track counts, names, and seed subjects from playlist briefs."""

from __future__ import annotations

import re

BRIEF_SUBJECT_PATTERN = re.compile(r"(?:similar to|like|inspired by)\s+(.{2,80})", re.IGNORECASE)

BRIEF_COUNT_PATTERN = re.compile(r"\b(\d{1,3})\s*(?:songs?|tracks?)\b", re.IGNORECASE)

BRIEF_FAVORITES_PATTERN = re.compile(r"\bfavou?rites\b", re.IGNORECASE)

BRIEF_EXPLICIT_NAME_PATTERN = re.compile(
    r"\b(?:save|name|call)\s+(?:(?:it|this|that|the\s+playlist|playlist)\s+)?as\s+"
    r"[\"']?([A-Za-z0-9][\w /&+.'-]*)"
    r"|\b(?:name|call)\s+(?:it|this|that|the\s+playlist|playlist)\s+"
    r"[\"']?([A-Za-z0-9][\w /&+.'-]*)",
    re.IGNORECASE,
)

BRIEF_ESSENCE_PATTERN = re.compile(
    r"\b(?:similar to|in the style of|style of|inspired by|"
    r"(?:songs?|tracks?|music|artists?|bands?)\s+like)\s+(.+)$",
    re.IGNORECASE,
)

BRIEF_BOILERPLATE_PATTERN = re.compile(
    r"^(?:create|make|build|generate|give me|i(?:'d| would)? (?:want|like)|play)\b[\s,:]*"
    r"(?:me\s+)?(?:a|an|the)?\s*(?:new\s+)?(?:playlist\s*)?(?:with|of|from)?\s*",
    re.IGNORECASE,
)


def count_from_brief(brief: str, default: int = 30) -> int:
    """Honor an explicit track count in the brief, e.g. 'playlist with 10 songs'."""
    match = BRIEF_COUNT_PATTERN.search(brief)
    if not match:
        return default
    return max(1, min(200, int(match.group(1))))


def name_from_brief(brief: str, default: str = "AI Mix") -> str:
    """A short playlist name from a prose brief, e.g. '... similar to X' -> 'X'."""
    text = " ".join(brief.split())
    explicit = _explicit_name(text)
    if explicit:
        return explicit[:48]
    match = BRIEF_ESSENCE_PATTERN.search(text)
    if match:
        text = match.group(1)
    else:
        text = BRIEF_BOILERPLATE_PATTERN.sub("", text)
    text = re.sub(r"\b\d{1,3}\b", "", text)
    text = re.sub(r"\b(?:songs?|tracks?|music)\b", "", text, flags=re.IGNORECASE)
    text = " ".join(text.split()).strip(" -,.!?;:")
    text = re.sub(r"^(?:of|with|from)\s+", "", text, flags=re.IGNORECASE)
    text = " ".join(text.split()[:6])
    if not text:
        return default
    return (text.title() if text == text.lower() else text)[:48]


def _explicit_name(text: str) -> str:
    """A name the brief states outright, e.g. 'save the playlist as X' -> 'X'."""
    match = BRIEF_EXPLICIT_NAME_PATTERN.search(text)
    if not match:
        return ""
    stops = {"and", "with", "then", "that", "which", "so", "also", "please"}
    kept: list[str] = []
    for word in (match.group(1) or match.group(2) or "").split():
        if word.lower() in stops or len(kept) == 4:
            break
        kept.append(word.strip("\"'"))
    return " ".join(kept)
