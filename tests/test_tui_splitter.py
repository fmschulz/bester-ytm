from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from bester_ytm.config import get_paths
from bester_ytm.config_options import load_app_options
from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_splitter import (
    MIN_PANE_WIDTH,
    PaneSplitter,
    clamped_pane_width,
)


def test_clamped_pane_width_within_bounds() -> None:
    assert clamped_pane_width(40, total_width=120, other_pane_width=30) == 40


def test_clamped_pane_width_enforces_minimum() -> None:
    assert clamped_pane_width(3, total_width=120, other_pane_width=30) == MIN_PANE_WIDTH


def test_clamped_pane_width_keeps_center_alive() -> None:
    # total 120 - other 30 - splitters 2 - center 20 = 68 available at most.
    assert clamped_pane_width(500, total_width=120, other_pane_width=30) == 68


def test_clamped_pane_width_tiny_terminal_floors_at_minimum() -> None:
    assert clamped_pane_width(50, total_width=40, other_pane_width=30) == MIN_PANE_WIDTH


def _write_config(tmp_path: Path, monkeypatch, content: str) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    path = get_paths().config_file
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_drag_resizes_left_pane_and_persists(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = BesterYTMApp()

    async def run_flow() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            splitter = app.query_one("#splitter-left", PaneSplitter)
            left = app.query_one("#left")
            start = left.size.width

            splitter.on_mouse_down(SimpleNamespace(screen_x=50))
            splitter.on_mouse_move(SimpleNamespace(screen_x=58))
            splitter.on_mouse_up(SimpleNamespace())
            await pilot.pause()

            assert left.styles.width is not None
            assert int(left.styles.width.value) == start + 8

    asyncio.run(run_flow())

    options = load_app_options()
    assert options.left_width is not None


def test_drag_right_splitter_grows_right_pane_leftward(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = BesterYTMApp()

    async def run_flow() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            splitter = app.query_one("#splitter-right", PaneSplitter)
            right = app.query_one("#right")
            start = right.size.width

            splitter.on_mouse_down(SimpleNamespace(screen_x=80))
            splitter.on_mouse_move(SimpleNamespace(screen_x=74))  # drag left -> right pane grows
            splitter.on_mouse_up(SimpleNamespace())
            await pilot.pause()

            assert right.styles.width is not None
            assert int(right.styles.width.value) == start + 6

    asyncio.run(run_flow())


def test_saved_layout_and_visualizer_apply_on_startup(monkeypatch, tmp_path) -> None:
    _write_config(
        tmp_path,
        monkeypatch,
        '[ui]\nvisualizer = "bars"\nleft_width = 30\nright_width = 44\n',
    )
    app = BesterYTMApp()

    async def run_flow() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert int(app.query_one("#left").styles.width.value) == 30
            assert int(app.query_one("#right").styles.width.value) == 44

    asyncio.run(run_flow())

    assert app.visualizer_effect == "bars"


def test_configured_volume_seeds_playback(monkeypatch, tmp_path) -> None:
    _write_config(tmp_path, monkeypatch, "[playback]\nvolume = 55\n")

    app = BesterYTMApp()

    assert app.playback.master_volume == 55.0


def test_configured_favorites_file_wins(monkeypatch, tmp_path) -> None:
    favs = tmp_path / "favs.md"
    favs.write_text("Artist - Title\n", encoding="utf-8")
    _write_config(
        tmp_path, monkeypatch, f'[builder]\nfavorites_file = "{favs}"\n'
    )

    app = BesterYTMApp()

    assert app._favorites_source() == favs.resolve()
    assert app._has_default_favorites() is True
