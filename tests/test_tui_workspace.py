"""Exercise stage, resize and modal boundaries with real Textual key dispatch."""
from __future__ import annotations

import asyncio

from textual.widgets import Input, ListView, Static

from bester_ytm.playback import PlaybackStatus
from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_help import HelpScreen
from bester_ytm.tui_stage import Stage


def _stage_lines(stage: Stage) -> list[str]:
    return [stage.render_line(y).text for y in range(stage.size.height)]


def test_resize_stage_and_restore_focus(monkeypatch):
    async def run():
        app = BesterYTMApp()
        status = PlaybackStatus(running=True, paused=True)
        monkeypatch.setattr(app.playback, "status", lambda: status)
        async with app.run_test(size=(150, 48)) as pilot:
            queue = app.query_one("#queue", ListView)
            queue.focus()
            await pilot.press("V")
            assert app.screen.has_class("immersive")
            assert app._focus_context() == "other"
            await pilot.resize_terminal(80, 24)
            app._check_resize()  # flush Textual's debounce; test clock skips idle delays
            await pilot.pause()
            assert app.screen.has_class("compact")
            assert app.screen.has_class("short")
            stage = app.query_one(Stage)
            lines = _stage_lines(stage)
            assert any(line.strip() for line in lines)  # redrawn at the new size, not blank
            assert all(len(line) == stage.size.width for line in lines)
            await pilot.press("escape")
            assert not app.screen.has_class("immersive")
            assert app.focused is queue
            assert not app.query_one("#right").display
            await pilot.press("f2")
            assert app.query_one("#right").display
            assert not app.query_one("#center").display
            await pilot.resize_terminal(150, 48)
            app._check_resize()
            await pilot.pause()
            assert app.query_one("#center").display
            assert app.query_one("#right").display
            app.set_focus(None)
            await pilot.press("V", "ctrl+f")
            assert not app.screen.has_class("immersive")
            assert app.query_one("#search", Input).value == "favs:"
    asyncio.run(run())


def test_global_pause_preserves_typing_and_help_blocks_library_actions(monkeypatch):
    async def run():
        app = BesterYTMApp()
        states = [PlaybackStatus(running=True), PlaybackStatus(running=True, paused=True)]
        current = [0]
        monkeypatch.setattr(app.playback, "status", lambda: states[current[0]])
        def pause():
            current[0] = 1 - current[0]
            return states[current[0]]
        monkeypatch.setattr(app.playback, "pause_resume", pause)
        async with app.run_test(size=(110, 40)) as pilot:
            search = app.query_one("#search", Input)
            search.value = "Daft Punk"
            search.focus()
            await pilot.press("ctrl+space")
            assert current[0] == 1
            assert search.value == "Daft Punk"
            await pilot.press("f1")
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("ctrl+f", "ctrl+p", "f2")
            assert isinstance(app.screen, HelpScreen)
            assert search.value == "Daft Punk"
            await pilot.press("f1")
            assert app.focused is search
    asyncio.run(run())


def test_zero_fps_updates_playback_state_without_animating(monkeypatch):
    async def run():
        app = BesterYTMApp()
        app.visual_fps = 0
        states = [PlaybackStatus(running=False), PlaybackStatus(running=True)]
        current = [0]
        monkeypatch.setattr(app.playback, "status", lambda: states[current[0]])
        async with app.run_test(size=(110, 40)) as pilot:
            stage = app.query_one(Stage)
            current[0] = 1
            app._refresh_playback()
            await pilot.pause()
            assert not stage.has_class("idle-effect")
            frame = _stage_lines(stage)
            app._refresh_playback()
            await pilot.pause()
            assert _stage_lines(stage) == frame
            assert app.signal.samples == 0  # visuals off: audio is never sampled

    asyncio.run(run())


def test_command_palette_has_a_separate_shortcut():
    from textual.command import CommandPalette

    async def run():
        app = BesterYTMApp()
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.press("ctrl+shift+p")
            assert isinstance(app.screen, CommandPalette)
            await pilot.press("escape")
            assert not isinstance(app.screen, CommandPalette)
    asyncio.run(run())


def test_idle_transport_and_background_updates_work_under_help():
    from bester_ytm.playlist_plan import SongCandidate

    async def run():
        app = BesterYTMApp()
        async with app.run_test(size=(150, 48)) as pilot:
            main = app.screen
            await pilot.press("f1")
            app._query_one_cache.clear()
            await pilot.press("ctrl+space")
            assert isinstance(app.screen, HelpScreen)
            app.candidates_by_video_id["song"] = SongCandidate(video_id="song", title="Title")
            app.playlist_video_ids = ["song"]
            app.playlist_title = "[Chill] Mix [/unexpected]"
            await app._render_queue()
            app._sync_current_track("song")
            assert "Title" in str(main.query_one("#track", Static).content)
            title = str(main.query_one("#queue-title", Static).content)
            assert "[Chill] Mix [/unexpected]" in title
            await pilot.resize_terminal(80, 24)
            app._check_resize()
            await pilot.pause()
            await pilot.press("f1")
            assert app.screen.has_class("compact")
            assert app.screen.has_class("short")
    asyncio.run(run())
