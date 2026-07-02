from __future__ import annotations

import re
from difflib import SequenceMatcher

from .playlist_plan import PlannedTrack, RankedCandidate, SongCandidate

VARIANT_TERMS = (
    "cover",
    "demo",
    "karaoke",
    "instrumental",
    "live",
    "lyrics",
    "lyric video",
    "remaster",
    "remastered",
    "remix",
    "sped up",
    "slowed",
    "tribute",
)


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.casefold(), right.casefold()).ratio()


# Terms whose plural forms also mark a variant ("The Remixes", "Acoustic Covers").
# "live" is excluded: "lives" is a different word ("Nine Lives").
_PLURAL_VARIANT_TERMS = frozenset(
    {"cover", "demo", "instrumental", "remaster", "remix", "tribute"}
)


def _variant_pattern(term: str) -> re.Pattern[str]:
    suffix = "(?:e?s)?" if term in _PLURAL_VARIANT_TERMS else ""
    return re.compile(rf"\b{re.escape(term)}{suffix}\b")


_VARIANT_PATTERNS = tuple((term, _variant_pattern(term)) for term in VARIANT_TERMS)


def variant_term(title: str) -> str | None:
    folded = title.casefold()
    for term, pattern in _VARIANT_PATTERNS:
        if pattern.search(folded):
            return term
    return None


def rank_candidate(
    target: PlannedTrack,
    candidate: SongCandidate,
    allow_variants: bool = False,
) -> RankedCandidate:
    title_score = _similarity(target.title, candidate.title)
    artist_text = " ".join(candidate.artists)
    artist_score = _similarity(target.artist, artist_text) if artist_text else 0.0
    combined_score = _similarity(
        target.query,
        " ".join(part for part in [artist_text, candidate.title] if part),
    )
    split_score = (title_score * 0.62) + (artist_score * 0.33)
    score = max(split_score, combined_score * 0.95)
    reasons = [
        f"title match {title_score:.2f}",
        f"artist match {artist_score:.2f}",
        f"combined query match {combined_score:.2f}",
    ]

    if candidate.result_type and "song" in candidate.result_type.casefold():
        score += 0.05
        reasons.append("song result")

    variant = variant_term(candidate.title)
    if variant and not allow_variants:
        score -= 0.35
        reasons.append(f"penalized {variant} variant")

    if candidate.duration_seconds is not None:
        if 60 <= candidate.duration_seconds <= 600:
            score += 0.03
            reasons.append("plausible song duration")
        else:
            score -= 0.08
            reasons.append("unusual song duration")

    return RankedCandidate(
        candidate=candidate,
        score=max(0.0, min(score, 1.0)),
        reason=", ".join(reasons),
    )


class Resolver:
    def __init__(self, allow_variants: bool = False) -> None:
        self.allow_variants = allow_variants

    def select_best(
        self,
        target: PlannedTrack,
        candidates: list[SongCandidate],
        min_score: float = 0.55,
    ) -> RankedCandidate | None:
        viable = [
            candidate
            for candidate in candidates
            if self.allow_variants or not variant_term(candidate.title)
        ]
        if not viable:
            return None
        ranked = [
            rank_candidate(target, candidate, allow_variants=self.allow_variants)
            for candidate in viable
        ]
        ranked.sort(key=lambda item: item.score, reverse=True)
        if ranked[0].score < min_score:
            return None
        return ranked[0]

    def resolve_track(self, target: PlannedTrack, candidates: list[SongCandidate]) -> PlannedTrack:
        target.candidates = candidates
        best = self.select_best(target, candidates)
        if best:
            target.selected_video_id = best.candidate.video_id
            target.confidence = best.score
            if best.reason:
                target.reason = f"{target.reason} Resolver: {best.reason}."
        elif candidates:
            skipped = [
                f"{candidate.display_name} ({variant_term(candidate.title)})"
                for candidate in candidates
                if variant_term(candidate.title)
            ]
            if skipped and not self.allow_variants:
                target.reason = (
                    f"{target.reason} Resolver skipped variant candidates: "
                    f"{'; '.join(skipped[:3])}."
                )
            else:
                target.reason = (
                    f"{target.reason} Resolver found no candidate above the "
                    "minimum confidence threshold."
                )
        else:
            target.reason = f"{target.reason} Resolver found no candidates."
        return target
