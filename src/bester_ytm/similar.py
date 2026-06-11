"""Find tracks similar to the current queue and resolve them to playable candidates."""

from __future__ import annotations

from .intelligence.llm import (
    IntelligenceError,
    IntelligenceSettings,
    resolve_provider,
    suggest_tracks,
)
from .playlist_plan import SongCandidate
from .resolver import variant_term
from .ytm_client import YTMClient, YTMClientError

SIMILAR_COUNT = 5
CONTEXT_LIMIT = 15
SEARCH_LIMIT = 4
RELATED_LIMIT = 10


def find_similar_candidates(
    client: YTMClient,
    seeds: list[SongCandidate],
    count: int,
    settings: IntelligenceSettings,
) -> tuple[list[SongCandidate], str]:
    """Return up to count playable candidates similar to seeds plus the provider used."""
    if not seeds:
        raise IntelligenceError("nothing is playing or queued; queue tracks first")
    provider = resolve_provider(settings)
    exclude_ids = {seed.video_id for seed in seeds}
    if provider == "heuristic":
        return _related_via_ytm(client, seeds, count, exclude_ids), provider
    context = [seed.display_name for seed in seeds[:CONTEXT_LIMIT]]
    suggestions = suggest_tracks(settings, context, count)
    exclude_names = {seed.display_name.casefold() for seed in seeds}
    found = _resolve_suggestions(client, suggestions, count, exclude_ids, exclude_names)
    return found, provider


def _resolve_suggestions(
    client: YTMClient,
    suggestions: list,
    count: int,
    exclude_ids: set[str],
    exclude_names: set[str],
) -> list[SongCandidate]:
    found: list[SongCandidate] = []
    for track in suggestions:
        if len(found) >= count:
            break
        try:
            candidates = client.search_songs(f"{track.artist} {track.title}", limit=SEARCH_LIMIT)
        except YTMClientError:
            continue
        match = _first_usable(candidates, exclude_ids, exclude_names)
        if match is not None:
            found.append(match)
            exclude_ids.add(match.video_id)
    if not found:
        raise IntelligenceError(
            "none of the suggested tracks could be resolved on YouTube Music"
        )
    return found


def _first_usable(
    candidates: list[SongCandidate],
    exclude_ids: set[str],
    exclude_names: set[str],
) -> SongCandidate | None:
    for candidate in candidates:
        if candidate.video_id in exclude_ids:
            continue
        if candidate.display_name.casefold() in exclude_names:
            continue
        if variant_term(candidate.title):
            continue
        return candidate
    return None


def _related_via_ytm(
    client: YTMClient,
    seeds: list[SongCandidate],
    count: int,
    exclude_ids: set[str],
) -> list[SongCandidate]:
    found: list[SongCandidate] = []
    for seed in seeds:
        if len(found) >= count:
            break
        try:
            related = client.get_related_candidates(seed.video_id, limit=RELATED_LIMIT)
        except YTMClientError:
            continue
        for candidate in related:
            if len(found) >= count:
                break
            if candidate.video_id in exclude_ids or variant_term(candidate.title):
                continue
            found.append(candidate)
            exclude_ids.add(candidate.video_id)
    if not found:
        raise IntelligenceError("could not find related tracks on YouTube Music")
    return found
