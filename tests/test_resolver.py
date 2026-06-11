from bester_ytm.playlist_plan import PlannedTrack, SongCandidate
from bester_ytm.resolver import Resolver


def test_resolver_penalizes_cover_live_remix_variants() -> None:
    target = PlannedTrack(
        artist="Beach House",
        title="Myth",
        reason="Seed.",
        role="seed",
        query="Beach House Myth",
    )
    official = SongCandidate(
        video_id="official",
        title="Myth",
        artists=["Beach House"],
        result_type="song",
        duration_seconds=258,
    )
    cover = SongCandidate(
        video_id="cover",
        title="Myth rare demo live cover",
        artists=["Beach House"],
        result_type="song",
        duration_seconds=260,
    )

    best = Resolver().select_best(target, [cover, official])

    assert best is not None
    assert best.candidate.video_id == "official"
    assert best.score > 0.9


def test_resolver_rejects_variant_when_no_clean_candidate() -> None:
    target = PlannedTrack(
        artist="Beach House",
        title="Myth",
        reason="Seed.",
        role="seed",
        query="Beach House Myth",
    )
    live = SongCandidate(
        video_id="live",
        title="Myth live",
        artists=["Beach House"],
        result_type="song",
        duration_seconds=260,
    )

    resolved = Resolver().resolve_track(target, [live])

    assert resolved.selected_video_id is None
    assert "skipped variant candidates" in resolved.reason


def test_resolver_can_allow_variants_when_requested() -> None:
    target = PlannedTrack(
        artist="Artist",
        title="Song remix",
        reason="Prompt requested variants.",
        role="related",
        query="Artist Song remix",
    )
    remix = SongCandidate(
        video_id="remix",
        title="Song remix",
        artists=["Artist"],
        result_type="song",
        duration_seconds=240,
    )

    best = Resolver(allow_variants=True).select_best(target, [remix])

    assert best is not None
    assert best.candidate.video_id == "remix"
    assert best.score > 0.9


def test_resolver_uses_combined_query_for_free_form_search() -> None:
    target = PlannedTrack(
        artist="",
        title="Beach House Myth",
        reason="Search.",
        role="search",
        query="Beach House Myth",
    )
    myth = SongCandidate(
        video_id="myth",
        title="Myth",
        artists=["Beach House"],
        result_type="song",
        duration_seconds=259,
    )
    become = SongCandidate(
        video_id="become",
        title="Become",
        artists=["Beach House"],
        result_type="song",
        duration_seconds=358,
    )

    best = Resolver().select_best(target, [become, myth])

    assert best is not None
    assert best.candidate.video_id == "myth"
