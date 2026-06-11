from __future__ import annotations

import pytest

from bester_ytm import similar
from bester_ytm.intelligence.llm import IntelligenceError, IntelligenceSettings, SuggestedTrack
from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.similar import find_similar_candidates
from bester_ytm.ytm_client import YTMClientError


def _candidate(video_id: str, title: str, artist: str = "Artist") -> SongCandidate:
    return SongCandidate(video_id=video_id, title=title, artists=[artist])


class FakeClient:
    def __init__(self, search_results=None, related=None) -> None:
        self.search_results = search_results or {}
        self.related = related or {}
        self.queries: list[str] = []

    def search_songs(self, query: str, limit: int = 5):
        self.queries.append(query)
        if isinstance(self.search_results, Exception):
            raise self.search_results
        return self.search_results.get(query, [])

    def get_related_candidates(self, video_id: str, limit: int = 10):
        return self.related.get(video_id, [])


SETTINGS = IntelligenceSettings(provider="codex")
SEEDS = [_candidate("s1", "Territory", "Sepultura")]


def test_ai_suggestions_resolve_in_order_and_skip_duplicates(monkeypatch) -> None:
    suggestions = [
        SuggestedTrack(artist="Machine Head", title="Davidian"),
        SuggestedTrack(artist="Prong", title="Snap"),
    ]
    monkeypatch.setattr(similar, "suggest_tracks", lambda *args, **kwargs: suggestions)
    client = FakeClient(
        search_results={
            "Machine Head Davidian": [
                _candidate("s1", "Already queued"),
                _candidate("v1", "Davidian"),
            ],
            "Prong Snap": [_candidate("v2", "Snap (Live)"), _candidate("v3", "Snap")],
        }
    )

    found, provider = find_similar_candidates(client, SEEDS, 5, SETTINGS)

    assert provider == "codex"
    assert [candidate.video_id for candidate in found] == ["v1", "v3"]


def test_ai_path_raises_when_nothing_resolves(monkeypatch) -> None:
    monkeypatch.setattr(
        similar,
        "suggest_tracks",
        lambda *args, **kwargs: [SuggestedTrack(artist="X", title="Y")],
    )
    client = FakeClient(search_results=YTMClientError("offline"))

    with pytest.raises(IntelligenceError, match="could be resolved"):
        find_similar_candidates(client, SEEDS, 5, SETTINGS)


def test_heuristic_path_uses_related_tracks() -> None:
    client = FakeClient(
        related={"s1": [_candidate("s1", "Territory"), _candidate("r1", "Refuse/Resist")]}
    )

    found, provider = find_similar_candidates(
        client, SEEDS, 5, IntelligenceSettings(provider="heuristic")
    )

    assert provider == "heuristic"
    assert [candidate.video_id for candidate in found] == ["r1"]


def test_empty_seeds_are_rejected() -> None:
    with pytest.raises(IntelligenceError, match="nothing is playing or queued"):
        find_similar_candidates(FakeClient(), [], 5, SETTINGS)
