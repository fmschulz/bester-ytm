import asyncio

from textual.binding import Binding
from textual.widgets import Static

from bester_ytm.tui import BesterYTMApp
from bester_ytm.tui_help import HelpScreen, help_sections, key_display


def _as_binding(binding) -> Binding:
    return binding if isinstance(binding, Binding) else Binding(*binding)


def test_help_binding_is_visible_in_footer() -> None:
    binding = next(
        _as_binding(binding)
        for binding in BesterYTMApp.BINDINGS
        if _as_binding(binding).action == "help"
    )
    assert binding.key == "question_mark"
    assert binding.key_display == "?"
    assert binding.show is True


def test_every_binding_appears_in_help_sections() -> None:
    """Drift guard: each app binding (visible and hidden) gets a help row."""
    keys_shown = {
        key
        for _section, rows in help_sections(BesterYTMApp.BINDINGS)
        for key, _description in rows
    }
    for entry in BesterYTMApp.BINDINGS:
        binding = _as_binding(entry)
        if binding.action == "help":
            continue
        assert key_display(binding) in keys_shown, (
            f"binding {binding.key} ({binding.action}) missing from help overlay"
        )


def test_question_mark_opens_help_and_escape_closes(monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent-bytm-config")

    async def run_flow() -> None:
        app = BesterYTMApp()
        async with app.run_test() as pilot:
            app.set_focus(None)  # the search Input would swallow the character
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)

    asyncio.run(run_flow())


def test_question_mark_again_closes_help(monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent-bytm-config")

    async def run_flow() -> None:
        app = BesterYTMApp()
        async with app.run_test() as pilot:
            app.set_focus(None)
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("?")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)

    asyncio.run(run_flow())


def test_overlay_renders_every_help_row(monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent-bytm-config")

    async def run_flow() -> None:
        app = BesterYTMApp()
        async with app.run_test() as pilot:
            app.set_focus(None)
            await pilot.pause()
            app.action_help()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, HelpScreen)
            content = {str(static.content) for static in screen.query(Static)}
            for section, rows in help_sections(app.BINDINGS):
                assert section in content
                for key, description in rows:
                    assert key in content, f"key {key!r} not rendered in overlay"
                    assert description in content

    asyncio.run(run_flow())
