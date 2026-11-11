"""Keep the favorites view and its song markers in sync."""

from __future__ import annotations

from textual.widgets import Input, ListView

from .config import ConfigError
from .stores import FavoritesStore
from .tui_rows import ResultRow


class FavoritesView:
    """Mixin for local favorites and their markers across the workspace."""

    _favorites_query: str | None = None
    result_selection_anchor_video_id: str | None

    async def action_show_favorites(self) -> None:
        self.action_leave_stage()
        search = self._query_optional("#search", Input)
        if search is not None:
            search.value = "favs:"
        await self._search("favs:")

    def _update_favorites_summary(self, count: int) -> None:
        self._update_library_summary(
            f"Favorites / {count} saved locally",
            (
                "No matching favorites. Edit favs: to change the filter."
                if self._favorites_query
                else "Your favorites live here. Highlight a song and press f to save it.\n"
                "Use Favorite playing to save the current track. No account needed."
            )
            if count == 0
            else "",
        )

    def _favorite_video_ids(self) -> set[str]:
        """Faved ids for row markers; a corrupt store degrades to a status message."""
        try:
            return FavoritesStore().ids()
        except ConfigError as exc:
            self._report_error(str(exc))
            return set()

    def _refresh_favorite_markers(self, video_id: str, faved: bool) -> None:
        """Reflect a favorite toggle in the result rows, the queue, and Now Playing."""
        self._relabel_result_favorite(video_id, faved)
        tree = self._album_tree()
        if tree is not None:
            favorite_ids = self._favorite_video_ids()
            for album in tree.root.children:
                for node in self._song_children(album):
                    if self._song_candidate(node).video_id == video_id:
                        node.set_label(
                            self._song_label(
                                self._song_candidate(node),
                                video_id in self.selected_result_video_ids,
                                favorite_ids,
                            )
                        )
        if self._favorites_query is not None:
            self.run_worker(
                self._refresh_favorites_view(self._results_load_id),
                exclusive=True,
                group="favorites-refresh",
            )
        self.run_worker(self._render_queue(), exclusive=True, group="queue-render")
        current = self.current_candidate
        if current is not None and current.video_id == video_id:
            self._show_playing_favorite(faved)

    async def _refresh_favorites_view(self, load_id: int) -> None:
        """Keep the filter, cursor and surviving selections when a favorite changes."""
        if load_id != self._results_load_id or self._favorites_query is None:
            return
        results = self.query_one("#results", ListView)
        highlighted = self._highlighted_result_candidate()
        index = getattr(results, "index", 0) or 0
        try:
            items = FavoritesStore().search_items(self._favorites_query)
        except ConfigError as exc:
            self._report_error(str(exc))
            return
        ids = [item.candidate.video_id for item in items if item.candidate]
        self.selected_result_video_ids.intersection_update(ids)
        if self.result_selection_anchor_video_id not in self.selected_result_video_ids:
            self.result_selection_anchor_video_id = next(
                (video_id for video_id in ids if video_id in self.selected_result_video_ids), None
            )
        await results.clear()
        rows: list[ResultRow] = []
        favorite_ids = set(ids)
        for search_item in items:
            item = self._result_item(search_item, favorite_ids)
            candidate = item.candidate
            item.marked = bool(candidate and candidate.video_id in self.selected_result_video_ids)
            rows.append(item)
        if load_id != self._results_load_id:
            return
        await results.extend(rows)
        if ids:
            results.index = (
                ids.index(highlighted.video_id)
                if highlighted is not None and highlighted.video_id in ids
                else min(index, len(ids) - 1)
            )
        self._update_favorites_summary(len(items))

    def _relabel_result_favorite(self, video_id: str, faved: bool) -> None:
        results = self._query_optional("#results", ListView)
        if results is None:
            return
        for item in getattr(results, "children", []):
            candidate = getattr(item, "candidate", None)
            if candidate is not None and candidate.video_id == video_id:
                item.favorite = faved
