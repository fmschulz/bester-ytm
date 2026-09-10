"""Real Textual event-loop coverage for favorites and focused track actions."""

import asyncio
from types import SimpleNamespace

from textual.widgets import Input, ListView

from bester_ytm.playlist_plan import SongCandidate
from bester_ytm.search_query import SearchItem, search_item_from_song
from bester_ytm.stores import FavoritesStore
from bester_ytm.tui import BesterYTMApp


def test_favorites_removal_keeps_cursor_and_surviving_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    tracks = [SongCandidate(video_id=f"v{i}", title=f"Song {i}") for i in range(3)]
    for track in tracks:
        FavoritesStore().toggle(track)

    async def exercise():
        app = BesterYTMApp()
        async with app.run_test() as pilot:
            await app.action_show_favorites()
            results = app.query_one("#results", ListView)
            results.index = 1
            results.focus()
            await pilot.pause()
            app.selected_result_video_ids = {"v0", "v1"}
            app.result_selection_anchor_video_id = "v1"
            app.action_toggle_favorite()
            await pilot.pause()
            assert [item.candidate.video_id for item in results.children] == ["v0", "v2"]
            assert results.highlighted_child.candidate.video_id == "v2"
            assert app.focused is results
            assert app.selected_result_video_ids == {"v0"}
            assert app.result_selection_anchor_video_id == "v0"
            assert app.query_one("#search", Input).value == "favs:"
            app.action_toggle_favorite()
            await pilot.pause()
            assert results.highlighted_child.candidate.video_id == "v0"
            app.action_toggle_favorite()
            await pilot.pause()
            assert len(results.children) == 0
            assert FavoritesStore().ids() == set()

    asyncio.run(exercise())


def test_favorite_button_uses_playing_track_while_f_uses_result(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    async def exercise():
        app = BesterYTMApp()
        async with app.run_test() as pilot:
            playing = SongCandidate(video_id="playing", title="Playing")
            browsing = SongCandidate(video_id="browsing", title="Browsing")
            app.current_candidate = playing
            results = app.query_one("#results", ListView)
            await results.append(app._result_item(search_item_from_song(browsing)))
            results.focus()
            results.index = 0
            await pilot.pause()
            app.action_toggle_playing_favorite()
            await pilot.pause()
            assert FavoritesStore().ids() == {"playing"}
            app.action_toggle_favorite()
            await pilot.pause()
            assert FavoritesStore().ids() == {"playing", "browsing"}

    asyncio.run(exercise())


def test_track_actions_use_focused_result_over_remembered_queue(monkeypatch):
    app = BesterYTMApp()
    candidate = SongCandidate(video_id="result", title="Result")
    app.selected_queue_video_id = "old-queue-cursor"
    monkeypatch.setattr(app, "_focus_context", lambda: "results")
    monkeypatch.setattr(app, "_highlighted_result_candidate", lambda: candidate)
    assert app._current_video_id() == "result"
    assert app._current_candidate() is candidate
    monkeypatch.setattr(app, "_highlighted_result_candidate", lambda: None)
    assert app._current_video_id() is None
    assert app._favorite_target() is None


def test_favorite_on_album_tree_uses_its_song_not_hidden_list(monkeypatch):
    app = BesterYTMApp()
    candidate = SongCandidate(video_id="album-song", title="Album song")
    monkeypatch.setattr(app, "_album_tree_active", lambda: True)
    monkeypatch.setattr(app, "_focus_context", lambda: "results")
    monkeypatch.setattr(
        app,
        "_album_tree",
        lambda: SimpleNamespace(
            cursor_node=SimpleNamespace(data={"kind": "song", "candidate": candidate})
        ),
    )
    assert app._favorite_target() is candidate


def test_expanded_album_favorite_marker_survives_selection(monkeypatch):
    from bester_ytm.tui_album import AlbumTree
    from bester_ytm.ytm_client import PlaylistSnapshot

    async def run():
        app = BesterYTMApp()
        candidate = SongCandidate(video_id="album-song", title="Song [live]", artists=["Artist"])
        async with app.run_test(size=(110, 40)) as pilot:
            tree = app.query_one("#album-tree", AlbumTree)
            await app._populate_album_tree([SearchItem(
                item_type="album", title="[Album] [/bad]", browse_id="album"
            )])
            album = tree.root.children[0]
            assert str(album.label) == "[Album] [/bad]"
            app._attach_album_tracks(album, PlaylistSnapshot(
                playlist_id="album", title="Album", video_ids=[candidate.video_id],
                tracks=[candidate],
            ))
            node = album.children[0]
            app._show_album_tree()
            tree.root.expand()
            album.expand()
            await pilot.pause()
            tree.select_node(node)
            tree.focus()
            await pilot.press("f")
            await pilot.pause()
            assert "[live]" in str(node.label)
            assert "[fav]" in str(node.label)
            await pilot.press("space")
            assert "[fav]" in str(node.label)
            await pilot.press("f")
            await pilot.pause()
            assert "[fav]" not in str(node.label)
    asyncio.run(run())
