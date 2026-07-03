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


def test_brief_reaches_the_ai_and_stands_alone_without_seeds(monkeypatch) -> None:
    from bester_ytm import similar as similar_module
    from bester_ytm.intelligence.llm import IntelligenceSettings, SuggestedTrack

    captured: dict = {}

    def fake_suggest(settings, context, count, brief=""):
        captured["brief"] = brief
        captured["context"] = context
        return [SuggestedTrack(artist="Four Tet", title="Two Thousand and Seventeen")]

    class FakeClient:
        def search_songs(self, query, limit=4):
            return [
                SongCandidate(
                    video_id="ft1",
                    title="Two Thousand and Seventeen",
                    artists=["Four Tet"],
                )
            ]

    monkeypatch.setattr(similar_module, "resolve_provider", lambda settings: "codex")
    monkeypatch.setattr(similar_module, "suggest_tracks", fake_suggest)

    found, provider = similar_module.find_similar_candidates(
        FakeClient(), [], 5, IntelligenceSettings(), brief="add 5 songs similar to Four Tet"
    )

    assert captured["brief"] == "add 5 songs similar to Four Tet"
    assert captured["context"] == []
    assert [c.video_id for c in found] == ["ft1"]
    assert provider == "codex"


def test_heuristic_without_seeds_rejects_briefs(monkeypatch) -> None:
    from bester_ytm import similar as similar_module
    from bester_ytm.intelligence.llm import IntelligenceError, IntelligenceSettings

    monkeypatch.setattr(similar_module, "resolve_provider", lambda settings: "heuristic")

    with pytest.raises(IntelligenceError, match="play or queue something first"):
        similar_module.find_similar_candidates(
            object(), [], 5, IntelligenceSettings(), brief="add 5 songs like Four Tet"
        )
