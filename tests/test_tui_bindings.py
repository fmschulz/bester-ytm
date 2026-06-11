import asyncio

from textual.binding import Binding

from bester_ytm.playback import PlaybackStatus
from bester_ytm.tui import BesterYTMApp


def test_playlist_shortcut_has_priority_binding() -> None:
    bindings = [
        binding
        for binding in BesterYTMApp.BINDINGS
        if isinstance(binding, Binding) and binding.action == "show_playlists"
    ]

    assert any(binding.key == "ctrl+p" and binding.priority for binding in bindings)


def _bound_actions() -> dict[str, str]:
    actions: dict[str, str] = {}
    for binding in BesterYTMApp.BINDINGS:
        if isinstance(binding, Binding):
            actions[binding.key] = binding.action
        else:
            actions[binding[0]] = binding[1]
    return actions


def test_plain_p_is_previous_track_not_playlist_picker() -> None:
    assert _bound_actions()["p"] == "previous_track"


def test_plain_s_shuffles_queue() -> None:
    assert _bound_actions()["s"] == "shuffle_queue"


def test_r_cycles_rating_and_g_adds_similar() -> None:
    actions = _bound_actions()
    assert actions["r"] == "cycle_rating"
    assert actions["g"] == "add_similar"


def test_footer_stays_compact_per_context_and_palette_disabled(monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent-bytm-config")
    app = BesterYTMApp()
    shown_actions = [
        binding.action if isinstance(binding, Binding) else binding[1]
        for binding in BesterYTMApp.BINDINGS
        if not isinstance(binding, Binding) or binding.show
    ]

    def visible_in(context: str) -> list[str]:
        monkeypatch.setattr(app, "_focus_context", lambda: context)
        return [a for a in shown_actions if app.check_action(a, ()) is True]

    everywhere = visible_in("other")
    results = visible_in("results")
    queue = visible_in("queue")

    assert "toggle_select" in results and "toggle_select" not in everywhere
    # d removes queue tracks and, in results, deletes highlighted local playlists.
    assert "remove_from_queue" in queue and "remove_from_queue" in results
    assert "remove_from_queue" not in everywhere
    assert "save_queue_playlist" in queue and "save_queue_playlist" not in everywhere
    assert "play_selected" in results and "play_selected" in queue
    for context_bindings in (everywhere, results, queue):
        assert len(context_bindings) <= 13
    assert BesterYTMApp.ENABLE_COMMAND_PALETTE is False


def test_volume_buttons_send_playback_commands() -> None:
    class FakePlayback:
        def __init__(self) -> None:
            self.volume = 50
            self.muted = False
            self.queue: list[str] = []

        def status(self) -> PlaybackStatus:
            return PlaybackStatus(
                running=True,
                current_video_id="v1",
                volume=self.volume,
                muted=self.muted,
            )

        def change_volume(self, delta: float) -> PlaybackStatus:
            self.volume += int(delta)
            return self.status()

        def toggle_mute(self) -> PlaybackStatus:
            self.muted = not self.muted
            return self.status()

    async def run_flow() -> None:
        app = BesterYTMApp()
        app.playback = FakePlayback()  # type: ignore[assignment]
        async with app.run_test() as pilot:
            # The right pane scrolls; bring the volume row into view first.
            app.query_one("#volume-row").scroll_visible(animate=False)
            await pilot.pause()
            await pilot.click("#volume-down-button")
            await pilot.pause()
            assert app.playback.volume == 45

            await pilot.click("#volume-up-button")
            await pilot.pause()
            assert app.playback.volume == 50

            await pilot.click("#mute-button")
            await pilot.pause()
            assert app.playback.muted is True

    asyncio.run(run_flow())


def test_playback_effects_update_for_playing_paused_and_idle(monkeypatch) -> None:
    class FakeWidget:
        def __init__(self) -> None:
            self.value = ""
            self.classes = set()

        def update(self, value: str) -> None:
            self.value = value

        def add_class(self, class_name: str) -> None:
            self.classes.add(class_name)

        def remove_class(self, class_name: str) -> None:
            self.classes.discard(class_name)

    visualizer = FakeWidget()
    panel = FakeWidget()
    progress_time = FakeWidget()
    volume = FakeWidget()
    track = FakeWidget()
    status_widget = FakeWidget()
    progress_updates = []

    class FakeProgress:
        def update(self, *, total, progress) -> None:
            progress_updates.append((total, progress))

    class FakePlayback:
        def __init__(self) -> None:
            self.current = PlaybackStatus(
                running=True,
                current_video_id="v1",
                position_seconds=15,
                duration_seconds=60,
                volume=55,
            )
            self.queue = []

        def status(self) -> PlaybackStatus:
            return self.current

    widgets = {
        "#visualizer": visualizer,
        "#right": panel,
        "#progress-time": progress_time,
        "#volume-status": volume,
        "#track": track,
        "#status": status_widget,
        "#progress": FakeProgress(),
    }

    app = BesterYTMApp()
    app.playback = FakePlayback()  # type: ignore[assignment]
    monkeypatch.setattr(app, "query_one", lambda selector, widget_type=None: widgets[selector])
    monkeypatch.setattr(app, "run_worker", lambda work, **kwargs: work.close())

    app._refresh_playback()

    assert visualizer.value.startswith("PLAY")
    assert "EQ    " in visualizer.value
    assert "SEEK  [###---------" in visualizer.value
    assert "playing-effect" in panel.classes
    assert "paused-effect" not in panel.classes
    assert progress_updates[-1] == (60, 15)

    app.playback.current = PlaybackStatus(
        running=True,
        current_video_id="v1",
        paused=True,
        position_seconds=30,
        duration_seconds=60,
        volume=55,
    )
    app._refresh_playback()

    assert visualizer.value.startswith("PAUSED")
    assert "paused-effect" in panel.classes
    assert "playing-effect" not in panel.classes

    app.playback.current = PlaybackStatus(running=False, current_video_id=None)
    app._refresh_playback()

    assert visualizer.value.startswith("IDLE")
    assert "idle-effect" in visualizer.classes
    assert "playing-effect" not in panel.classes
    assert "paused-effect" not in panel.classes
