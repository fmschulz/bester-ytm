"""One-line result and queue rows: labels, tails, flags, and fitting to the width."""

from __future__ import annotations

import asyncio

import pytest
from rich.cells import cell_len
from textual.app import App, ComposeResult
from textual.widgets import ListView

from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.search_query import SearchItem, search_item_from_song
from bester_ytm.tui_rows import QueueRow, ResultRow, queue_heading

MYTH = SongCandidate(
    video_id="v1", title="Myth", artists=["Beach House"], album="Bloom", duration_seconds=258
)


def test_song_result_shows_title_artist_album_and_duration() -> None:
    row = ResultRow(search_item_from_song(MYTH))

    assert row.label == "  Myth  Beach House  Bloom"
    assert row.tail == "  4:18"


@pytest.mark.parametrize(
    ("kind", "tag"),
    [("album", "album"), ("playlist", "playlist"), ("local_playlist", "local"), ("radio", "radio")],
)
def test_other_results_name_their_kind(kind: str, tag: str) -> None:
    row = ResultRow(SearchItem(item_type=kind, title="Deep Focus", subtitle="YouTube Music"))

    assert row.label == "  Deep Focus  YouTube Music"
    assert row.tail == "  " + tag


def test_marks_and_stars_are_flags() -> None:
    row = ResultRow(search_item_from_song(MYTH), favorite=True)

    row.marked = True

    assert str(row.label).startswith("● Myth")
    assert str(row.tail).startswith("★")


def test_queue_row_marks_the_playing_track() -> None:
    playing = QueueRow("v1", 3, MYTH, is_playing=True, is_favorite=True)
    played = QueueRow("v0", 2, None, is_played=True)

    assert playing.label == "▶  3  Myth  Beach House"
    assert playing.tail == "★ 4:18"
    assert playing.has_class("playing")
    assert played.label == "   2  v0"
    assert played.has_class("played")


@pytest.mark.parametrize(
    ("count", "seconds", "expected"),
    [
        (0, 0, "Mix  0 tracks"),
        (1, 258, "Mix  1 track, 4 min"),
        (14, 3840, "Mix  14 tracks, 1 h 04 min"),
    ],
)
def test_queue_heading_sums_up_the_queue(count: int, seconds: float, expected: str) -> None:
    assert queue_heading("Mix", count, seconds) == expected


class RowsApp(App[None]):
    def __init__(self, *rows: ResultRow) -> None:
        super().__init__()
        self.rows = rows

    def compose(self) -> ComposeResult:
        yield ListView(*self.rows)


def test_rows_fit_the_width_with_the_tail_right_aligned() -> None:
    long_title = SongCandidate(
        video_id="v2", title="夜に駆ける" * 6, artists=["YOASOBI"], duration_seconds=261
    )

    async def run() -> None:
        app = RowsApp(ResultRow(search_item_from_song(long_title)))
        async with app.run_test(size=(30, 5)) as pilot:
            await pilot.pause()
            row = app.query_one(ResultRow)
            line = str(row.render())

            assert cell_len(line) == row.content_size.width
            assert line.endswith("4:21")
            assert "…" in line

    asyncio.run(run())


def test_changing_a_flag_redraws_the_row() -> None:
    async def run() -> None:
        app = RowsApp(ResultRow(search_item_from_song(MYTH)))
        async with app.run_test(size=(40, 5)) as pilot:
            row = app.query_one(ResultRow)
            before = str(row.render())

            row.marked = True
            await pilot.pause()

            assert str(row.render()) != before
            assert str(row.render()).startswith("●")

    asyncio.run(run())


def test_a_narrow_row_drops_the_album_before_cutting_the_artist() -> None:
    async def run() -> None:
        app = RowsApp(ResultRow(search_item_from_song(MYTH)))
        async with app.run_test(size=(30, 5)) as pilot:
            await pilot.pause()
            line = str(app.query_one(ResultRow).render())

            assert "Beach House" in line
            assert "Bloom" not in line
            assert line.endswith("4:18")

    asyncio.run(run())
