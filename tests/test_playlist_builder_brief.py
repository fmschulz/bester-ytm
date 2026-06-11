from __future__ import annotations

import pytest

from bester_ytm import playlist_builder as builder_module
from bester_ytm.intelligence.llm import (
    IntelligenceError,
    IntelligenceSettings,
    SuggestedTrack,
    SuggestedTracks,
)
from bester_ytm.playlist_builder import (
    PlaylistBuilder,
    PlaylistBuildError,
    count_from_brief,
    name_from_brief,
)
from bester_ytm.playlist_plan import PlaylistPlan, SeedTrack, SongCandidate


class FakeClient:
    def __init__(self, results=None) -> None:
        self.results = results or {}
        self.queries: list[str] = []

    def search_songs(self, query: str, limit: int = 5):
        self.queries.append(query)
        return self.results.get(query, [])

    def get_related_candidates(self, video_id: str, limit: int = 10):
        return []


def _candidate(video_id: str, title: str, artist: str) -> SongCandidate:
    return SongCandidate(video_id=video_id, title=title, artists=[artist])


def _patched_builder(monkeypatch, client) -> PlaylistBuilder:
    builder = PlaylistBuilder(client=client)
    captured: dict[str, object] = {}

    def fake_build_from_seeds(seeds, name, count, brief=""):
        captured.update({"seeds": seeds, "name": name, "count": count, "brief": brief})
        return PlaylistPlan(id="plan-1", name=name, target_count=count)

    monkeypatch.setattr(builder, "build_from_seeds", fake_build_from_seeds)
    builder.captured = captured  # type: ignore[attr-defined]
    return builder


def test_brief_with_ai_provider_seeds_from_suggestions(monkeypatch) -> None:
    monkeypatch.setattr(
        builder_module,
        "suggest_playlist",
        lambda settings, context, count, brief: SuggestedTracks(
            tracks=[SuggestedTrack(artist="Soulfly", title="Eye for an Eye", reason="tribal")]
        ),
    )
    builder = _patched_builder(monkeypatch, FakeClient())

    plan = builder.build_from_brief(
        "songs similar to sepultura",
        name="Sepultura-ish",
        count=10,
        settings=IntelligenceSettings(provider="codex"),
    )

    seeds = builder.captured["seeds"]  # type: ignore[attr-defined]
    assert plan.id == "plan-1"
    assert [seed.artist for seed in seeds] == ["Soulfly"]
    assert seeds[0].source == "ai:codex"
    assert builder.captured["brief"] == "songs similar to sepultura"  # type: ignore[attr-defined]
    assert builder.captured["name"] == "Sepultura-ish"  # type: ignore[attr-defined]


def test_brief_uses_the_ai_provided_playlist_name(monkeypatch) -> None:
    monkeypatch.setattr(
        builder_module,
        "suggest_playlist",
        lambda settings, context, count, brief: SuggestedTracks(
            name="powermetal-10",
            tracks=[SuggestedTrack(artist="Blind Guardian", title="Valhalla")],
        ),
    )
    builder = _patched_builder(monkeypatch, FakeClient())

    builder.build_from_brief(
        "10 songs similar to blind guardian, save the playlist as powermetal-10",
        name="Blind Guardian",
        count=10,
        settings=IntelligenceSettings(provider="codex"),
    )

    assert builder.captured["name"] == "powermetal-10"  # type: ignore[attr-defined]


def test_brief_with_heuristic_provider_searches_the_subject(monkeypatch) -> None:
    client = FakeClient(
        results={"sepultura": [_candidate("v1", "Territory", "Sepultura")]}
    )
    builder = _patched_builder(monkeypatch, client)

    builder.build_from_brief(
        "build playlist with songs similar to sepultura",
        name="Metal",
        count=10,
        settings=IntelligenceSettings(provider="heuristic"),
    )

    assert client.queries == ["sepultura"]
    seeds = builder.captured["seeds"]  # type: ignore[attr-defined]
    assert isinstance(seeds[0], SeedTrack)
    assert seeds[0].artist == "Sepultura"


def test_count_from_brief_honors_explicit_track_counts() -> None:
    assert count_from_brief("playlist with 10 songs similar to blind guardian") == 10
    assert count_from_brief("give me 25 tracks of doom metal") == 25
    assert count_from_brief("songs similar to sepultura") == 30
    assert count_from_brief("0 songs") == 1
    assert count_from_brief("999 songs") == 200


def test_name_from_brief_extracts_the_essence() -> None:
    assert (
        name_from_brief("Create a playlist with 15 songs in style similar to blind guardian")
        == "Blind Guardian"
    )
    assert name_from_brief("give me 25 tracks of doom metal") == "Doom Metal"
    assert name_from_brief("songs like The Cure") == "The Cure"
    assert name_from_brief("in the style of Boards of Canada") == "Boards of Canada"


def test_name_from_brief_honors_explicit_save_as() -> None:
    assert (
        name_from_brief(
            "create a playlist with 10 songs in style similar to blind guardian "
            "and also include at least 3 blind guardian songs  save the playlist "
            "as  powermetal-10  "
        )
        == "powermetal-10"
    )
    assert name_from_brief("upbeat funk, call it Friday Fuel and keep it fresh") == (
        "Friday Fuel"
    )
    assert name_from_brief("name it 'Rainy Days' please") == "Rainy Days"
    assert name_from_brief("songs that call to mind summer evenings") == (
        "That Call To Mind Summer Evenings"
    )


def test_name_from_brief_keeps_typed_case_and_falls_back() -> None:
    assert name_from_brief("inspired by AC/DC") == "AC/DC"
    assert name_from_brief("melancholic shoegaze for a rainy night") == (
        "Melancholic Shoegaze For A Rainy Night"
    )
    assert name_from_brief("15 songs") == "AI Mix"
    assert name_from_brief("") == "AI Mix"


def test_brief_errors_are_actionable(monkeypatch) -> None:
    builder = PlaylistBuilder(client=FakeClient())

    with pytest.raises(PlaylistBuildError, match="brief is empty"):
        builder.build_from_brief("  ", name="X", count=10)

    monkeypatch.setattr(
        builder_module,
        "suggest_playlist",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            IntelligenceError("codex CLI is not installed or not on PATH")
        ),
    )
    with pytest.raises(PlaylistBuildError, match="codex CLI is not installed"):
        builder.build_from_brief(
            "anything", name="X", count=10, settings=IntelligenceSettings(provider="codex")
        )

    with pytest.raises(PlaylistBuildError, match="No songs found for brief"):
        builder.build_from_brief(
            "similar to nobody-known",
            name="X",
            count=10,
            settings=IntelligenceSettings(provider="heuristic"),
        )
