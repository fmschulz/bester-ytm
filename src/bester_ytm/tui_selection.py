"""Multi-select of search-result songs for batch queueing."""

from __future__ import annotations

from textual.widgets import ListView

from .playback import PlaybackError
from .playlist_plan import SongCandidate

SELECTED_PREFIX = "* "


class SelectionActions:
    """Mixin that lets the user mark several search results and queue them in order."""

    selected_result_video_ids: set[str]
    result_selection_anchor_video_id: str | None
    playlist_video_ids: list[str]
    playlist_title: str

    def action_range_select(self) -> None:
        if self._range_select_highlighted_result():
            return
        self._set_status(
            "Shift+space or shift+click extends selection from the first marked song."
        )

    def action_toggle_select(self) -> None:
        if self._album_tree_active():
            self._toggle_album_tree_selection()
            return
        results = self._query_optional("#results", ListView)
        item = getattr(results, "highlighted_child", None) if results else None
        if not self._toggle_result_item(item):
            self._set_status(
                "Space/x mark songs; shift+space or shift+click extends selection; "
                "Enter queues them."
            )

    def _highlighted_result_can_toggle_selection(self) -> bool:
        if self._album_tree_active():
            tree = self._album_tree()
            node = getattr(tree, "cursor_node", None) if tree else None
            data = getattr(node, "data", None)
            return isinstance(data, dict) and data.get("kind") in {"album", "song"}
        results = self._query_optional("#results", ListView)
        item = getattr(results, "highlighted_child", None) if results else None
        return self._selection_candidate(item) is not None

    def _toggle_clicked_result(self, widget: object) -> bool:
        item = widget
        while item is not None and getattr(item, "candidate", None) is None:
            item = getattr(item, "parent", None)
        return self._toggle_result_item(item)

    def _range_select_clicked_result(self, widget: object) -> bool:
        item = widget
        while item is not None and getattr(item, "candidate", None) is None:
            item = getattr(item, "parent", None)
        return self._range_select_item(item)

    def _range_select_highlighted_result(self) -> bool:
        if self._album_tree_active():
            tree = self._album_tree()
            node = getattr(tree, "cursor_node", None) if tree else None
            return self._range_select_item(node)
        results = self._query_optional("#results", ListView)
        item = getattr(results, "highlighted_child", None) if results else None
        return self._range_select_item(item)

    def _range_select_tree_node(self, node: object) -> bool:
        return self._range_select_item(node)

    def _toggle_result_item(self, item: object) -> bool:
        candidate = self._selection_candidate(item)
        if candidate is None:
            return False
        video_id = candidate.video_id
        selected = video_id not in self.selected_result_video_ids
        self._mark_selection_item(item, selected)
        if selected and self.result_selection_anchor_video_id is None:
            self.result_selection_anchor_video_id = video_id
        elif not selected and self.result_selection_anchor_video_id == video_id:
            self.result_selection_anchor_video_id = self._first_selected_result_video_id()
        count = len(self.selected_result_video_ids)
        self._set_status(f"{count} track(s) selected; Enter queues them in order.")
        return True

    def _range_select_item(self, target: object) -> bool:
        target_candidate = self._selection_candidate(target)
        if target_candidate is None:
            return False
        items = self._selection_items_in_display_order()
        target_index = self._selection_item_index(items, target_candidate.video_id)
        if target_index is None:
            return False

        anchor_video_id = self.result_selection_anchor_video_id
        anchor_index = (
            self._selection_item_index(items, anchor_video_id) if anchor_video_id else None
        )
        if anchor_index is None:
            anchor_index = target_index
            self.result_selection_anchor_video_id = target_candidate.video_id

        start, end = sorted((anchor_index, target_index))
        for item in items[start : end + 1]:
            self._mark_selection_item(item, True)
        count = len(self.selected_result_video_ids)
        self._set_status(f"{count} track(s) selected; Enter queues them in order.")
        return True

    def _selection_candidate(self, item: object) -> SongCandidate | None:
        if item is None:
            return None
        candidate = getattr(item, "candidate", None)
        if candidate is not None:
            return candidate
        data = getattr(item, "data", None)
        if isinstance(data, dict) and data.get("kind") == "song":
            candidate = data.get("candidate")
            if isinstance(candidate, SongCandidate):
                return candidate
        return None

    def _selection_items_in_display_order(self) -> list[object]:
        if self._album_tree_active():
            tree = self._album_tree()
            if tree is None:
                return []
            items: list[object] = []
            for album_node in list(tree.root.children):
                items.extend(self._song_children(album_node))
            return items

        results = self._query_optional("#results", ListView)
        if results is None:
            return []
        return [
            item
            for item in list(results.children)
            if self._selection_candidate(item) is not None
        ]

    def _selection_item_index(self, items: list[object], video_id: str | None) -> int | None:
        if video_id is None:
            return None
        for index, item in enumerate(items):
            candidate = self._selection_candidate(item)
            if candidate is not None and candidate.video_id == video_id:
                return index
        return None

    def _first_selected_result_video_id(self) -> str | None:
        for item in self._selection_items_in_display_order():
            candidate = self._selection_candidate(item)
            if candidate is not None and candidate.video_id in self.selected_result_video_ids:
                return candidate.video_id
        return None

    def _mark_selection_item(self, item: object, selected: bool) -> None:
        candidate = self._selection_candidate(item)
        if candidate is None:
            return
        if selected:
            self.selected_result_video_ids.add(candidate.video_id)
        else:
            self.selected_result_video_ids.discard(candidate.video_id)
        self._render_selection_item(item, selected)

    def _render_selection_item(self, item: object, selected: bool) -> None:
        if isinstance(getattr(item, "data", None), dict):
            candidate = self._selection_candidate(item)
            set_label = getattr(item, "set_label", None)
            if candidate is not None and callable(set_label):
                set_label(self._song_label(candidate, selected))
                parent = getattr(item, "parent", None)
                if parent is not None:
                    self._refresh_album_marker(parent)
                return
        self._render_result_marker(item, selected)

    def _render_result_marker(self, item: object, selected: bool) -> None:
        label = getattr(item, "label_widget", None)
        base = getattr(item, "base_label", None)
        if label is None or base is None:
            return
        label.update(f"{SELECTED_PREFIX}{base}" if selected else base)

    def _clear_result_selection(self) -> None:
        self.selected_result_video_ids.clear()
        self.result_selection_anchor_video_id = None

    async def _queue_selected_results(self) -> bool:
        """Queue every selected result in display order; True if selection was handled."""
        candidates = self._selected_candidates_in_display_order()
        if not candidates:
            return False
        for candidate in candidates:
            self.candidates_by_video_id[candidate.video_id] = candidate
        video_ids = [candidate.video_id for candidate in candidates]
        try:
            message = self._start_or_extend_queue(video_ids)
        except PlaybackError as exc:
            await self._report_playback_error(exc)
            return True
        self._clear_selection_markers()
        await self._render_queue()
        self._set_status(message)
        return True

    def _start_or_extend_queue(self, video_ids: list[str]) -> str:
        video_ids = self._drop_queued_radio(video_ids)
        if not video_ids:
            return "Radio stations are already playing or queued."
        self._supersede_queue_load()
        if self.playback.status().running:
            self.playback.enqueue(video_ids)
            self.playlist_video_ids.extend(video_ids)
            return f"Queued {len(video_ids)} track(s)."
        if self.playlist_video_ids or self.playback.queue:
            # A playlist is loaded but not playing: grow it instead of replacing it.
            self.playback.enqueue(video_ids)
            self.playlist_video_ids.extend(video_ids)
            return f"Added {len(video_ids)} track(s) to {self.playlist_title}."
        self.playback.replace_queue(video_ids)
        self.playlist_video_ids = list(video_ids)
        self.playlist_title = "Queue"
        status = self.playback.play_queue()
        self.playback_was_active = True
        self._sync_current_track(status.current_video_id)
        return f"Playing 1/{len(video_ids)} queued track(s); auto-advance plays the rest."

    def _selected_candidates_in_display_order(self) -> list[SongCandidate]:
        if not self.selected_result_video_ids:
            return []
        ordered: list[SongCandidate] = []
        for item in self._selection_items_in_display_order():
            candidate = self._selection_candidate(item)
            if candidate is not None and candidate.video_id in self.selected_result_video_ids:
                ordered.append(candidate)
        return ordered

    def _clear_selection_markers(self) -> None:
        for item in self._selection_items_in_display_order():
            self._render_selection_item(item, False)
        self._clear_result_selection()
