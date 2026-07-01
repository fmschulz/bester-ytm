"""Album browsing as a tree in the left pane: expand albums, select and queue songs."""

from __future__ import annotations

import inspect

from textual import events
from textual.widgets import ListView, Tree
from textual.widgets.tree import TreeNode

from .config import ConfigError
from .playback import PlaybackError
from .playlist_plan import SongCandidate
from .search_query import SearchItem
from .ytm_client import YTMClientError

SELECTED_PREFIX = "* "


class AlbumTree(Tree):
    """Album/song tree that leaves space and shift+space to the app selection logic."""

    BINDINGS = [
        binding
        for binding in Tree.BINDINGS
        if getattr(binding, "key", None) not in {"space", "shift+space"}
    ]

    async def _on_key(self, event: events.Key) -> None:
        if event.key in {"space", "shift+space"}:
            event.stop()
            event.prevent_default()
            if event.key == "shift+space":
                self.app.action_range_select()
                return
            result = self.app.action_pause_resume()
            if inspect.iscoroutine(result):
                await result
            return
        await super()._on_key(event)

    async def _on_click(self, event: events.Click) -> None:
        if event.shift and "line" in event.style.meta:
            node = self.get_node_at_line(event.style.meta["line"])
            handled = bool(self.app._range_select_tree_node(node))
            if handled:
                event.stop()
                event.prevent_default()
                return
        await super()._on_click(event)


def _node_data(node: TreeNode) -> dict:
    data = node.data
    return data if isinstance(data, dict) else {}


class AlbumActions:
    """Mixin that renders album searches as a tree and adds songs whole-album or one by one."""

    selected_result_video_ids: set[str]
    candidates_by_video_id: dict[str, SongCandidate]
    playlist_video_ids: list[str]
    playlist_title: str
    active_local_playlist_id: str | None
    active_youtube_playlist_id: str | None
    selected_queue_video_id: str | None
    result_selection_anchor_video_id: str | None

    # --- visibility -------------------------------------------------------

    def _album_tree(self) -> AlbumTree | None:
        return self._query_optional("#album-tree", AlbumTree)

    def _album_tree_active(self) -> bool:
        tree = self._album_tree()
        return bool(tree and tree.display)

    def _show_album_tree(self) -> None:
        results = self._query_optional("#results", ListView)
        if results is not None:
            results.display = False
        tree = self._album_tree()
        if tree is not None:
            tree.display = True

    def _show_results_list(self) -> None:
        tree = self._album_tree()
        if tree is not None:
            tree.display = False
        results = self._query_optional("#results", ListView)
        if results is not None:
            results.display = True

    # --- labels -----------------------------------------------------------

    def _album_label(self, item: SearchItem, selected: bool) -> str:
        details = item.subtitle
        if item.year and item.year not in details:
            details = f"{details} ({item.year})" if details else item.year
        text = f"{item.title} - {details}" if details else item.title
        return f"{SELECTED_PREFIX}{text}" if selected else text

    def _song_label(self, candidate: SongCandidate, selected: bool) -> str:
        text = candidate.display_name
        return f"{SELECTED_PREFIX}{text}" if selected else text

    @staticmethod
    def _song_children(node: TreeNode) -> list[TreeNode]:
        return [child for child in node.children if _node_data(child).get("kind") == "song"]

    @staticmethod
    def _song_candidate(node: TreeNode) -> SongCandidate:
        candidate: SongCandidate = _node_data(node)["candidate"]
        return candidate

    # --- population -------------------------------------------------------

    async def _populate_album_tree(self, items: list[SearchItem]) -> None:
        self._show_album_tree()
        tree = self.query_one("#album-tree", AlbumTree)
        tree.auto_expand = False
        tree.show_root = False
        tree.clear()
        for item in items:
            if item.item_type != "album" or not item.browse_id:
                continue
            tree.root.add(
                self._album_label(item, False),
                data={"kind": "album", "item": item, "loaded": False},
                expand=False,
            )
        tree.focus()

    def _load_album_node(self, node: TreeNode) -> list[SongCandidate]:
        """Fetch and attach an album's songs once; safe to call repeatedly."""
        data = _node_data(node)
        if data.get("kind") != "album":
            return []
        if not data.get("loaded"):
            item: SearchItem = data["item"]
            snapshot = self.client.get_album(str(item.browse_id))
            data["loaded"] = True
            for track in snapshot.tracks:
                self.candidates_by_video_id[track.video_id] = track
                selected = track.video_id in self.selected_result_video_ids
                node.add_leaf(
                    self._song_label(track, selected),
                    data={"kind": "song", "candidate": track},
                )
        return [self._song_candidate(child) for child in self._song_children(node)]

    # --- tree events ------------------------------------------------------

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        try:
            self._load_album_node(event.node)
        except (ConfigError, YTMClientError) as exc:
            self._set_status(str(exc))

    async def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = _node_data(event.node)
        kind = data.get("kind")
        if (
            self.selected_result_video_ids
            and not (kind == "album" and not event.node.is_expanded)
        ):
            event.stop()
            await self.action_add_to_queue()
            return
        if kind == "album":
            event.node.toggle()
        elif kind == "song":
            await self._queue_or_play_candidate(data["candidate"])

    # --- selection (x) ----------------------------------------------------

    def _toggle_album_tree_selection(self) -> None:
        tree = self.query_one("#album-tree", AlbumTree)
        node = tree.cursor_node
        data = _node_data(node) if node else {}
        if not node or not data:
            self._set_status("Highlight an album or song to select.")
            return
        if data.get("kind") == "song":
            self._toggle_song_node(node)
        elif data.get("kind") == "album":
            try:
                self._toggle_album_node(node)
            except (ConfigError, YTMClientError) as exc:
                self._set_status(str(exc))
                return
        count = len(self.selected_result_video_ids)
        self._set_status(f"{count} track(s) selected; Enter queues them in order.")

    def _toggle_song_node(self, node: TreeNode) -> None:
        candidate = self._song_candidate(node)
        selected = candidate.video_id not in self.selected_result_video_ids
        self._mark_selected(candidate.video_id, selected)
        node.set_label(self._song_label(candidate, selected))
        if node.parent is not None:
            self._refresh_album_marker(node.parent)

    def _toggle_album_node(self, node: TreeNode) -> None:
        candidates = self._load_album_node(node)
        select_all = not (
            candidates
            and all(c.video_id in self.selected_result_video_ids for c in candidates)
        )
        for candidate in candidates:
            self._mark_selected(candidate.video_id, select_all)
        for child in self._song_children(node):
            song = self._song_candidate(child)
            child.set_label(
                self._song_label(song, song.video_id in self.selected_result_video_ids)
            )
        node.set_label(self._album_label(_node_data(node)["item"], select_all and bool(candidates)))

    def _refresh_album_marker(self, node: TreeNode) -> None:
        data = _node_data(node)
        if data.get("kind") != "album":
            return
        songs = [self._song_candidate(child) for child in self._song_children(node)]
        all_selected = bool(songs) and all(
            song.video_id in self.selected_result_video_ids for song in songs
        )
        node.set_label(self._album_label(data["item"], all_selected))

    def _mark_selected(self, video_id: str, selected: bool) -> None:
        if selected:
            self.selected_result_video_ids.add(video_id)
            if self.result_selection_anchor_video_id is None:
                self.result_selection_anchor_video_id = video_id
        else:
            self.selected_result_video_ids.discard(video_id)
            if self.result_selection_anchor_video_id == video_id:
                self.result_selection_anchor_video_id = self._first_selected_result_video_id()

    def _reset_album_tree_markers(self) -> None:
        tree = self._album_tree()
        if tree is None:
            return
        for album_node in tree.root.children:
            for song_node in self._song_children(album_node):
                song_node.set_label(self._song_label(self._song_candidate(song_node), False))
            album_data = _node_data(album_node)
            if album_data.get("kind") == "album":
                album_node.set_label(self._album_label(album_data["item"], False))

    # --- play now, replacing the queue (shift+a) --------------------------

    async def action_play_album(self) -> None:
        candidates, title = self._candidates_to_play_now()
        if not candidates:
            self._set_status("Highlight an album or song to play it now.")
            return
        for candidate in candidates:
            self.candidates_by_video_id[candidate.video_id] = candidate
        video_ids = [candidate.video_id for candidate in candidates]
        try:
            self.playback.replace_queue(video_ids)
            self.playlist_video_ids = list(video_ids)
            self.playlist_title = title
            status = self.playback.play_queue()
            self.playback_was_active = True
        except PlaybackError as exc:
            await self._report_playback_error(exc)
            return
        self.active_local_playlist_id = None
        self.active_youtube_playlist_id = None
        self.selected_queue_video_id = video_ids[0]
        self._reset_album_tree_markers()
        self._clear_selection_markers()
        self._sync_current_track(status.current_video_id)
        await self._render_queue()
        self._refresh_playback(status)
        self._set_status(f"Playing {title}: {len(video_ids)} track(s).")

    def _candidates_to_play_now(self) -> tuple[list[SongCandidate], str]:
        if self.selected_result_video_ids:
            selected = self._selected_candidates_for_add()
            if selected:
                return selected, "Queue"
        if self._album_tree_active():
            return self._cursor_play_candidates()
        candidate = self._highlighted_result_candidate()
        return ([candidate], "Queue") if candidate else ([], "Queue")

    def _cursor_play_candidates(self) -> tuple[list[SongCandidate], str]:
        tree = self.query_one("#album-tree", AlbumTree)
        node = tree.cursor_node
        data = _node_data(node) if node else {}
        if not node or not data:
            return [], "Queue"
        try:
            if data.get("kind") == "album":
                return self._load_album_node(node), self._album_title(node)
            if data.get("kind") == "song" and node.parent is not None:
                album_songs = self._load_album_node(node.parent)
                ids = [candidate.video_id for candidate in album_songs]
                current = self._song_candidate(node).video_id
                if current in ids:
                    return album_songs[ids.index(current) :], self._album_title(node.parent)
        except (ConfigError, YTMClientError) as exc:
            self._set_status(str(exc))
            return [], "Queue"
        if data.get("kind") == "song":
            return [self._song_candidate(node)], "Queue"
        return [], "Queue"

    @staticmethod
    def _album_title(node: TreeNode) -> str:
        item = _node_data(node).get("item")
        return getattr(item, "title", None) or "Queue"

    # --- add (a) ----------------------------------------------------------

    async def action_add_to_queue(self) -> None:
        candidates = self._candidates_for_add()
        if not candidates:
            self._set_status(
                "Nothing to add. Highlight a song or album row, or mark rows with x."
            )
            return
        for candidate in candidates:
            self.candidates_by_video_id[candidate.video_id] = candidate
        video_ids = [candidate.video_id for candidate in candidates]
        try:
            message = self._start_or_extend_queue(video_ids)
        except PlaybackError as exc:
            await self._report_playback_error(exc)
            return
        self._reset_album_tree_markers()
        self._clear_selection_markers()
        await self._render_queue()
        self._set_status(message)

    def _candidates_for_add(self) -> list[SongCandidate]:
        if self.selected_result_video_ids:
            ordered = self._selected_candidates_for_add()
            if ordered:
                return ordered
        if self._album_tree_active():
            return self._cursor_candidates()
        candidate = self._highlighted_result_candidate()
        return [candidate] if candidate else []

    def _selected_candidates_for_add(self) -> list[SongCandidate]:
        if self._album_tree_active():
            return self._album_tree_selected_candidates()
        return self._selected_candidates_in_display_order()

    def _cursor_candidates(self) -> list[SongCandidate]:
        tree = self.query_one("#album-tree", AlbumTree)
        node = tree.cursor_node
        data = _node_data(node) if node else {}
        if not node or not data:
            return []
        if data.get("kind") == "song":
            return [data["candidate"]]
        if data.get("kind") == "album":
            try:
                return self._load_album_node(node)
            except (ConfigError, YTMClientError) as exc:
                self._set_status(str(exc))
                return []
        return []

    def _album_tree_selected_candidates(self) -> list[SongCandidate]:
        tree = self._album_tree()
        if tree is None:
            return []
        ordered: list[SongCandidate] = []
        for album_node in tree.root.children:
            for song_node in self._song_children(album_node):
                candidate = self._song_candidate(song_node)
                if candidate.video_id in self.selected_result_video_ids:
                    ordered.append(candidate)
        return ordered
