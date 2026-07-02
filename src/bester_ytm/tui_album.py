"""Album browsing as a tree in the left pane: expand albums, select and queue songs."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import partial

from textual import events
from textual.widgets import ListView, Tree
from textual.widgets.tree import TreeNode

from .config import ConfigError
from .playlist_plan import SongCandidate
from .search_query import SearchItem
from .ytm_client import PlaylistSnapshot, YTMClientError

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


@dataclass(frozen=True)
class _PendingAlbumAction:
    """An a/A/x press on a collapsed album, waiting for its tracks to load."""

    action_id: int
    node: TreeNode
    action: str  # "add" | "play" | "select"
    queue_load_id: int


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
    _queue_load_id: int
    _results_load_id: int
    _album_action_id: int = 0
    _pending_album_action: _PendingAlbumAction | None = None

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
        self._cancel_pending_album_action()
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

    @staticmethod
    def _album_title(node: TreeNode) -> str:
        item = _node_data(node).get("item")
        return getattr(item, "title", None) or "Queue"

    # --- population -------------------------------------------------------

    async def _populate_album_tree(self, items: list[SearchItem]) -> None:
        self._cancel_pending_album_action()
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
        if self._input_focus_changed_since_load():
            return  # the user is typing in an input; do not yank focus away
        tree.focus()

    def _album_songs(self, node: TreeNode) -> list[SongCandidate]:
        """Return an album node's already-loaded songs; never fetches."""
        return [self._song_candidate(child) for child in self._song_children(node)]

    def _attach_album_tracks(self, node: TreeNode, snapshot: PlaylistSnapshot) -> None:
        data = _node_data(node)
        if data.get("loaded"):
            return
        data["loaded"] = True
        for track in snapshot.tracks:
            self.candidates_by_video_id[track.video_id] = track
            selected = track.video_id in self.selected_result_video_ids
            node.add_leaf(
                self._song_label(track, selected),
                data={"kind": "song", "candidate": track},
            )

    # --- deferred a/A/x on collapsed albums ---------------------------------

    def _cancel_pending_album_action(self) -> None:
        """Any new a/A/x press or tree rebuild supersedes an in-flight deferred action."""
        self._album_action_id += 1
        self._pending_album_action = None

    def _defer_album_action(self, node: TreeNode, action: str) -> None:
        """Fetch a collapsed album off the UI thread; the action runs when tracks land."""
        self._album_action_id += 1
        self._pending_album_action = _PendingAlbumAction(
            action_id=self._album_action_id,
            node=node,
            action=action,
            queue_load_id=self._queue_load_id,
        )
        data = _node_data(node)
        item: SearchItem = data["item"]
        self._set_status(f"Loading album {item.title}...")
        if data.get("loading"):
            return  # reuse the in-flight fetch; the pending action fires when it lands
        data["loading"] = True
        self.run_worker(
            partial(self._album_node_worker, node, self._results_load_id),
            name="album",
            group="album",
            thread=True,
        )

    async def _run_album_action(self, pending: _PendingAlbumAction) -> None:
        """Deferred action; staleness must be rechecked here, not only when scheduled."""
        if pending.action_id != self._album_action_id:
            return  # superseded by a newer action after this coroutine was scheduled
        self._pending_album_action = None
        node = pending.node
        if pending.action == "select":
            self._toggle_album_node(node)
            count = len(self.selected_result_video_ids)
            self._set_status(f"{count} track(s) selected; Enter queues them in order.")
            return
        if pending.queue_load_id != self._queue_load_id:
            return  # the user built competing queue state while the album loaded
        candidates = self._album_songs(node)
        if not candidates:
            self._set_status(f"Album {self._album_title(node)} has no playable tracks.")
            return
        if pending.action == "play":
            await self._play_candidates_now(candidates, self._album_title(node))
            return
        await self._add_candidates_to_queue(candidates)

    # --- tree events ------------------------------------------------------

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        data = _node_data(event.node)
        if data.get("kind") != "album" or data.get("loaded") or data.get("loading"):
            return
        data["loading"] = True
        item: SearchItem = data["item"]
        self._set_status(f"Loading album {item.title}...")
        self.run_worker(
            partial(self._album_node_worker, event.node, self._results_load_id),
            name="album",
            group="album",
            thread=True,
        )

    def _album_node_worker(self, node: TreeNode, load_id: int) -> None:
        """Runs on a worker thread so slow album fetches never freeze the UI."""
        item: SearchItem = _node_data(node)["item"]
        try:
            snapshot = self.client.get_album(str(item.browse_id))
        except (ConfigError, YTMClientError) as exc:
            self.call_from_thread(self._finish_album_node_error, node, str(exc), load_id)
            return
        self.call_from_thread(self._finish_album_node, node, snapshot, load_id)

    def _finish_album_node_error(self, node: TreeNode, message: str, load_id: int) -> None:
        _node_data(node)["loading"] = False
        pending = self._pending_album_action
        if pending is not None and pending.node is node:
            self._pending_album_action = None
        if load_id != self._results_load_id:
            return  # a newer search replaced these results; keep its status
        self._set_status(message)

    def _finish_album_node(
        self, node: TreeNode, snapshot: PlaylistSnapshot, load_id: int
    ) -> None:
        _node_data(node)["loading"] = False
        if load_id != self._results_load_id:
            return  # a newer search detached this node while the album loaded
        self._attach_album_tracks(node, snapshot)
        self._set_status(
            f"Loaded album {self._album_title(node)}: "
            f"{len(self._song_children(node))} track(s)."
        )
        pending = self._pending_album_action
        if pending is not None and pending.node is node:
            self.run_worker(self._run_album_action(pending), exclusive=False)

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
