from __future__ import annotations

import builtins
import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .config import ConfigError, get_paths, write_private_text
from .playlist_plan import PlaylistPlan, SongCandidate, parse_seed_file, plan_to_markdown, slugify
from .search_query import SearchItem, search_item_from_song

logger = logging.getLogger(__name__)


def _corrupt_store_error(path: Path, error: Exception) -> ConfigError:
    return ConfigError(
        f"Store file {path} is corrupt: {error}. "
        "Move the file aside (or delete it) and retry."
    )


class PlanStore:
    def __init__(self, plans_dir: Path | None = None) -> None:
        self.paths = get_paths()
        self.plans_dir = plans_dir or self.paths.plans_dir

    def ensure(self) -> None:
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    def json_path(self, plan_id: str) -> Path:
        return self.plans_dir / f"{plan_id}.json"

    def markdown_path(self, plan_id: str) -> Path:
        return self.plans_dir / f"{plan_id}.md"

    def save(self, plan: PlaylistPlan) -> tuple[Path, Path]:
        self.ensure()
        plan.touch()
        json_path = self.json_path(plan.id)
        md_path = self.markdown_path(plan.id)
        json_path.write_text(
            plan.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        md_path.write_text(plan_to_markdown(plan), encoding="utf-8")
        return json_path, md_path

    def find(self, plan_id_or_path: str) -> Path:
        candidate = Path(plan_id_or_path).expanduser()
        if candidate.exists():
            return candidate.resolve()
        self.ensure()
        direct = self.json_path(plan_id_or_path)
        if direct.exists():
            return direct
        matches = sorted(self.plans_dir.glob(f"{plan_id_or_path}*.json"))
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise FileNotFoundError(f"No playlist plan found for {plan_id_or_path!r}")
        raise FileExistsError(
            f"Plan id prefix {plan_id_or_path!r} is ambiguous: "
            + ", ".join(path.stem for path in matches[:8])
        )

    def load(self, plan_id_or_path: str) -> PlaylistPlan:
        path = self.find(plan_id_or_path)
        try:
            return PlaylistPlan.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise _corrupt_store_error(path, exc) from exc

    def list(self) -> list[Path]:
        self.ensure()
        return sorted(self.plans_dir.glob("*.json"), reverse=True)

    def export(self, plan_id_or_path: str, fmt: str) -> str:
        plan = self.load(plan_id_or_path)
        if fmt == "json":
            return plan.model_dump_json(indent=2) + "\n"
        if fmt == "md":
            return plan_to_markdown(plan)
        raise ValueError(f"Unsupported export format: {fmt}")


# Marker appended to a faved song's row label in the results and queue lists.
# Distinct from the multi-select marker, which is a "* " prefix on the left.
FAVORITE_SUFFIX = " *"

_LEGACY_FAVORITE_LINE = re.compile(r"^- (?P<name>.+) \((?P<video_id>[^()\s]+)\)$")


class FavoritesStore:
    """Faved tracks as SongCandidates in favorites.json; the legacy favorites.md
    (written by older versions and `favorites import-tuiradio`) is migrated on
    first read and still used as the tuiradio import target."""

    def __init__(self, path: Path | None = None, legacy_path: Path | None = None) -> None:
        paths = get_paths()
        self.path = path or paths.favorites_store_file
        self.legacy_path = legacy_path or paths.favorites_file

    def import_tuiradio(self, source: Path) -> int:
        seeds = parse_seed_file(source)
        lines = ["# bester-ytm Favorites", ""]
        for seed in seeds:
            station = f" [{seed.station}]" if seed.station else ""
            lines.append(f"- {seed.artist} - {seed.title}{station}")
        write_private_text(self.legacy_path, "\n".join(lines) + "\n")
        return len(seeds)

    def list(self) -> builtins.list[SongCandidate]:
        if not self.path.exists():
            return self._migrate_legacy()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise _corrupt_store_error(self.path, exc) from exc
        if not isinstance(payload, list):
            raise _corrupt_store_error(
                self.path, ValueError("expected a JSON array of favorite tracks")
            )
        try:
            return [SongCandidate.model_validate(entry) for entry in payload]
        except ValidationError as exc:
            raise _corrupt_store_error(self.path, exc) from exc

    def ids(self) -> set[str]:
        return {candidate.video_id for candidate in self.list()}

    def toggle(self, candidate: SongCandidate) -> bool:
        """Fav an unfaved track / unfav a faved one; returns the new faved state."""
        favorites = self.list()
        remaining = [item for item in favorites if item.video_id != candidate.video_id]
        if len(remaining) < len(favorites):
            self._write(remaining)
            return False
        favorites.append(candidate)
        self._write(favorites)
        return True

    def search_items(self, text: str = "") -> builtins.list[SearchItem]:
        needle = text.strip().casefold()
        return [
            search_item_from_song(candidate, source="favorites")
            for candidate in self.list()
            if not needle or needle in candidate.display_name.casefold()
        ]

    def _write(self, favorites: builtins.list[SongCandidate]) -> None:
        payload = [candidate.model_dump(mode="json") for candidate in favorites]
        write_private_text(self.path, json.dumps(payload, indent=2) + "\n")

    def _migrate_legacy(self) -> builtins.list[SongCandidate]:
        """Carry `- Display Name (video_id)` lines from favorites.md into the JSON
        store once; tuiradio-imported lines have no video id and are skipped."""
        if not self.legacy_path.exists():
            return []
        favorites: builtins.list[SongCandidate] = []
        for line in self.legacy_path.read_text(encoding="utf-8").splitlines():
            match = _LEGACY_FAVORITE_LINE.match(line.strip())
            if match:
                favorites.append(
                    SongCandidate(video_id=match.group("video_id"), title=match.group("name"))
                )
        if favorites:
            self._write(favorites)
        return favorites


class LocalPlaylist(BaseModel):
    id: str
    name: str
    tracks: list[SongCandidate] = Field(default_factory=list)

    @property
    def video_ids(self) -> list[str]:
        return [track.video_id for track in self.tracks]


class LocalPlaylistStore:
    def __init__(self, playlists_dir: Path | None = None) -> None:
        self.playlists_dir = playlists_dir or get_paths().local_playlists_dir

    def ensure(self) -> None:
        self.playlists_dir.mkdir(parents=True, exist_ok=True)

    def path_for_id(self, playlist_id: str) -> Path:
        return self.playlists_dir / f"{slugify(playlist_id)}.json"

    def load(self, playlist_id: str) -> LocalPlaylist:
        path = self.path_for_id(playlist_id)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise FileNotFoundError(
                f"No local playlist named {playlist_id!r}; in the Ctrl+P list only "
                "LOCAL PLAYLIST entries are local, the rest live on YouTube"
            ) from None
        try:
            return LocalPlaylist.model_validate_json(text)
        except ValidationError as exc:
            raise _corrupt_store_error(path, exc) from exc

    def delete(self, playlist_id: str) -> LocalPlaylist:
        """Delete a local playlist file; returns the playlist so callers can report its name."""
        playlist = self.load(playlist_id)
        self.path_for_id(playlist_id).unlink(missing_ok=True)
        return playlist

    def save(self, playlist: LocalPlaylist) -> Path:
        self.ensure()
        path = self.path_for_id(playlist.id)
        write_private_text(path, playlist.model_dump_json(indent=2) + "\n")
        return path

    def list(self) -> list[LocalPlaylist]:
        self.ensure()
        playlists: list[LocalPlaylist] = []
        for path in sorted(self.playlists_dir.glob("*.json")):
            try:
                playlists.append(LocalPlaylist.model_validate_json(path.read_text(encoding="utf-8")))
            except ValidationError as exc:
                logger.warning("%s", _corrupt_store_error(path, exc))
        return playlists

    def search_items(self) -> builtins.list[SearchItem]:
        return [
            SearchItem(
                item_type="local_playlist",
                title=playlist.name,
                source="local",
                playlist_id=playlist.id,
                track_count=len(playlist.tracks),
            )
            for playlist in self.list()
        ]

    def add_track(self, name: str, candidate: SongCandidate) -> LocalPlaylist:
        playlist_id = slugify(name or "TUI Playlist")
        path = self.path_for_id(playlist_id)
        if path.exists():
            playlist = self.load(playlist_id)
        else:
            playlist = LocalPlaylist(id=playlist_id, name=name or "TUI Playlist")
        if candidate.video_id not in playlist.video_ids:
            playlist.tracks.append(candidate)
        self.save(playlist)
        return playlist

    def remove_track(self, playlist_id: str, video_id: str) -> LocalPlaylist:
        playlist = self.load(playlist_id)
        playlist.tracks = [track for track in playlist.tracks if track.video_id != video_id]
        self.save(playlist)
        return playlist
