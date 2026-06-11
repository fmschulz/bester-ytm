from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from .config import ConfigError, load_intelligence_settings, resolve_existing_input
from .intelligence.heuristic import HeuristicProvider
from .intelligence.llm import (
    IntelligenceError,
    IntelligenceSettings,
    resolve_provider,
    suggest_playlist,
)
from .playlist_plan import (
    PlannedTrack,
    PlaylistPlan,
    SeedTrack,
    SongCandidate,
    parse_seed_file,
    parse_seed_text,
)
from .resolver import Resolver, variant_term
from .ytm_client import YTMClient, YTMClientError


class PlaylistBuildError(RuntimeError):
    pass


BRIEF_SUBJECT_PATTERN = re.compile(
    r"(?:similar to|like|inspired by)\s+(.{2,80})", re.IGNORECASE
)
BRIEF_COUNT_PATTERN = re.compile(r"\b(\d{1,3})\s*(?:songs?|tracks?)\b", re.IGNORECASE)
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


class PlaylistBuilder:
    def __init__(
        self,
        client: YTMClient | None = None,
        provider: HeuristicProvider | None = None,
        allow_variants: bool = False,
    ) -> None:
        self.client = client or YTMClient(authenticated=False)
        self.provider = provider or HeuristicProvider(allow_variants=allow_variants)
        self.resolver = Resolver(allow_variants=allow_variants)
        self.allow_variants = allow_variants

    def build_from_favorites(
        self,
        source: Path,
        name: str,
        count: int,
        brief: str = "",
    ) -> PlaylistPlan:
        if count < 1:
            raise PlaylistBuildError("count must be at least 1")
        try:
            resolved_source = resolve_existing_input(source)
        except ConfigError as exc:
            raise PlaylistBuildError(str(exc)) from exc
        seeds = parse_seed_file(resolved_source)
        if not seeds:
            raise PlaylistBuildError(f"No seed tracks found in {resolved_source}")

        return self.build_from_seeds(seeds, name=name, count=count, brief=brief)

    def build_from_text(
        self,
        text: str,
        source: str,
        name: str,
        count: int,
        brief: str = "",
    ) -> PlaylistPlan:
        if count < 1:
            raise PlaylistBuildError("count must be at least 1")
        seeds = parse_seed_text(text, source)
        if not seeds:
            raise PlaylistBuildError(f"No seed tracks found in {source}")
        return self.build_from_seeds(seeds, name=name, count=count, brief=brief)

    def build_from_brief(
        self,
        brief: str,
        name: str,
        count: int,
        settings: IntelligenceSettings | None = None,
    ) -> PlaylistPlan:
        """Build a plan from a free-form brief alone, via the configured AI provider."""
        if count < 1:
            raise PlaylistBuildError("count must be at least 1")
        cleaned = brief.strip()
        if not cleaned:
            raise PlaylistBuildError("The playlist brief is empty.")
        settings = settings or load_intelligence_settings()
        try:
            provider = resolve_provider(settings)
            if provider == "heuristic":
                seeds = self._seeds_from_brief(cleaned)
            else:
                suggestion = suggest_playlist(settings, [], count, cleaned)
                seeds = [
                    SeedTrack(artist=track.artist, title=track.title, source=f"ai:{provider}")
                    for track in suggestion.tracks
                ]
                if suggestion.name.strip():
                    name = suggestion.name.strip()[:48]
        except IntelligenceError as exc:
            raise PlaylistBuildError(str(exc)) from exc
        if not seeds:
            raise PlaylistBuildError(
                f"No songs found for brief {cleaned!r}; try naming an artist or song."
            )
        return self.build_from_seeds(seeds, name=name, count=count, brief=cleaned)

    def _seeds_from_brief(self, brief: str) -> list[SeedTrack]:
        match = BRIEF_SUBJECT_PATTERN.search(brief)
        subject = (match.group(1) if match else brief).strip(" .!?\"'")
        try:
            candidates = self.client.search_songs(subject, limit=5)
        except YTMClientError as exc:
            raise PlaylistBuildError(str(exc)) from exc
        return [
            SeedTrack(
                artist=candidate.artists[0] if candidate.artists else subject,
                title=candidate.title,
                source="brief-search",
            )
            for candidate in candidates
        ]

    def build_from_seeds(
        self,
        seeds: list[SeedTrack],
        name: str,
        count: int,
        brief: str = "",
    ) -> PlaylistPlan:
        plan = self.provider.build_playlist_plan(seeds, count, brief, name)
        self._resolve_seed_tracks(plan)
        self._append_related_tracks(plan)
        self._fill_from_seed_searches(plan)
        plan.planned_tracks = plan.planned_tracks[:count]
        return plan

    def _resolve_seed_tracks(self, plan: PlaylistPlan) -> None:
        for track in plan.planned_tracks:
            try:
                candidates = self.client.search_songs(track.query, limit=7)
            except YTMClientError as exc:
                track.reason = f"{track.reason} Resolution failed: {exc}."
                continue
            self.resolver.resolve_track(track, candidates)

    def _append_related_tracks(self, plan: PlaylistPlan) -> None:
        existing_video_ids = set(plan.selected_video_ids)
        seed_by_query = {seed.query: seed for seed in plan.seed_tracks}
        related_by_seed: list[tuple[SeedTrack, list[SongCandidate]]] = []
        for track in list(plan.planned_tracks):
            if len(plan.planned_tracks) >= plan.target_count:
                return
            if not track.selected_video_id:
                continue
            seed = seed_by_query.get(track.query)
            if seed is None:
                continue
            try:
                related = self.client.get_related_candidates(track.selected_video_id, limit=15)
            except YTMClientError as exc:
                track.reason = f"{track.reason} Related lookup failed: {exc}."
                continue
            related_by_seed.append((seed, related))

        index = 0
        while len(plan.planned_tracks) < plan.target_count and related_by_seed:
            added_this_round = False
            for seed, related in related_by_seed:
                if len(plan.planned_tracks) >= plan.target_count:
                    return
                if index >= len(related):
                    continue
                candidate = related[index]
                if not self.allow_variants and variant_term(candidate.title):
                    continue
                if candidate.video_id in existing_video_ids:
                    continue
                planned = self.provider.plan_related_track(
                    candidate,
                    seed,
                    existing_video_ids,
                )
                if planned is None:
                    continue
                planned.confidence = max(0.55, 0.78 - (index * 0.03))
                plan.planned_tracks.append(planned)
                existing_video_ids.add(candidate.video_id)
                added_this_round = True
            index += 1
            if not added_this_round and all(
                index >= len(related) for _, related in related_by_seed
            ):
                return

    def _fill_from_seed_searches(self, plan: PlaylistPlan) -> None:
        existing_video_ids = set(plan.selected_video_ids)
        for seed in plan.seed_tracks:
            if len(plan.planned_tracks) >= plan.target_count:
                return
            try:
                candidates = self.client.search_songs(seed.artist, limit=8)
            except YTMClientError:
                continue
            for candidate in candidates:
                if len(plan.planned_tracks) >= plan.target_count:
                    return
                if candidate.video_id in existing_video_ids:
                    continue
                if not self.allow_variants and variant_term(candidate.title):
                    continue
                artist = candidate.artists[0] if candidate.artists else seed.artist
                artist_score = self._artist_similarity(seed.artist, candidate.artists)
                if artist_score < 0.55:
                    continue
                target = PlannedTrack(
                    artist=artist,
                    title=candidate.title,
                    reason=(
                        f"Fallback discovery from the seed artist {seed.artist}; "
                        f"kept to fill the requested playlist length "
                        f"(artist match {artist_score:.2f})."
                    ),
                    role="deep_cut",
                    query=f"{artist} {candidate.title}",
                    candidates=[candidate],
                )
                target.selected_video_id = candidate.video_id
                target.confidence = min(0.85, 0.5 + (artist_score * 0.35))
                plan.planned_tracks.append(target)
                existing_video_ids.add(candidate.video_id)

    @staticmethod
    def _artist_similarity(seed_artist: str, candidate_artists: list[str]) -> float:
        if not candidate_artists:
            return 0.0
        folded_seed = seed_artist.casefold()
        scores = [
            SequenceMatcher(None, folded_seed, artist.casefold()).ratio()
            for artist in candidate_artists
        ]
        joined = " ".join(candidate_artists).casefold()
        scores.append(SequenceMatcher(None, folded_seed, joined).ratio())
        return max(scores)
