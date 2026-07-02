"""Queueing and selection actions on the album tree (x, a, shift+a)."""

from __future__ import annotations

from textual.widgets.tree import TreeNode

from .playback import PlaybackError
from .playlist_plan import SongCandidate
from .tui_album import AlbumTree, _node_data


class AlbumQueueActions:
    """Mixin that plays, queues, or marks the albums and songs in the tree."""

    selected_result_video_ids: set[str]
    candidates_by_video_id: dict[str, SongCandidate]
    playlist_video_ids: list[str]
    playlist_title: str
    active_local_playlist_id: str | None
    active_youtube_playlist_id: str | None
    selected_queue_video_id: str | None
    result_selection_anchor_video_id: str | None

    # --- selection (x) ----------------------------------------------------

    def _toggle_album_tree_selection(self) -> None:
        self._cancel_pending_album_action()
        tree = self.query_one("#album-tree", AlbumTree)
        node = tree.cursor_node
        data = _node_data(node) if node else {}
        if not node or not data:
            self._set_status("Highlight an album or song to select.")
            return
        if data.get("kind") == "song":
            self._toggle_song_node(node)
        elif data.get("kind") == "album":
            if not data.get("loaded"):
                self._defer_album_action(node, "select")
                return
            self._toggle_album_node(node)
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
        candidates = self._album_songs(node)
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
        self._cancel_pending_album_action()
        candidates, title = self._candidates_to_play_now()
        if candidates is None:
            return  # deferred: the album is loading; playback starts when tracks land
        if not candidates:
            self._set_status("Highlight an album or song to play it now.")
            return
        await self._play_candidates_now(candidates, title)

    async def _play_candidates_now(self, candidates: list[SongCandidate], title: str) -> None:
        self._supersede_queue_load()
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

    def _candidates_to_play_now(self) -> tuple[list[SongCandidate] | None, str]:
        """Candidates for shift+a; None means a deferred album load was started."""
        if self.selected_result_video_ids:
            selected = self._selected_candidates_for_add()
            if selected:
                return selected, "Queue"
        if self._album_tree_active():
            return self._cursor_play_candidates()
        candidate = self._highlighted_result_candidate()
        return ([candidate], "Queue") if candidate else ([], "Queue")

    def _cursor_play_candidates(self) -> tuple[list[SongCandidate] | None, str]:
        tree = self.query_one("#album-tree", AlbumTree)
        node = tree.cursor_node
        data = _node_data(node) if node else {}
        if not node or not data:
            return [], "Queue"
        if data.get("kind") == "album":
            if not data.get("loaded"):
                self._defer_album_action(node, "play")
                return None, "Queue"
            return self._album_songs(node), self._album_title(node)
        if data.get("kind") == "song" and node.parent is not None:
            album_songs = self._album_songs(node.parent)
            ids = [candidate.video_id for candidate in album_songs]
            current = self._song_candidate(node).video_id
            if current in ids:
                return album_songs[ids.index(current) :], self._album_title(node.parent)
        if data.get("kind") == "song":
            return [self._song_candidate(node)], "Queue"
        return [], "Queue"

    # --- add (a) ----------------------------------------------------------

    async def action_add_to_queue(self) -> None:
        self._cancel_pending_album_action()
        candidates = self._candidates_for_add()
        if candidates is None:
            return  # deferred: the album is loading; its tracks queue when they land
        if not candidates:
            self._set_status(
                "Nothing to add. Highlight a song or album row, or mark rows with x."
            )
            return
        await self._add_candidates_to_queue(candidates)

    async def _add_candidates_to_queue(self, candidates: list[SongCandidate]) -> None:
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

    def _candidates_for_add(self) -> list[SongCandidate] | None:
        """Candidates for a/Enter; None means a deferred album load was started."""
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

    def _cursor_candidates(self) -> list[SongCandidate] | None:
        tree = self.query_one("#album-tree", AlbumTree)
        node = tree.cursor_node
        data = _node_data(node) if node else {}
        if not node or not data:
            return []
        if data.get("kind") == "song":
            return [data["candidate"]]
        if data.get("kind") == "album":
            if not data.get("loaded"):
                self._defer_album_action(node, "add")
                return None
            return self._album_songs(node)
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
