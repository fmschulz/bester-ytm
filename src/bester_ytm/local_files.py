"""Local audio files as playable search results (video_id = "local:<path>")."""

from __future__ import annotations

from pathlib import Path

from .playlist_plan import SongCandidate
from .search_query import SearchItem, search_item_from_song

LOCAL_VIDEO_ID_PREFIX = "local:"
AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac", ".aiff", ".wma"}
)
MAX_LOCAL_RESULTS = 500


def is_local_video_id(video_id: str) -> bool:
    return video_id.startswith(LOCAL_VIDEO_ID_PREFIX)


def local_path(video_id: str) -> str:
    return video_id[len(LOCAL_VIDEO_ID_PREFIX) :]


def _candidate_from_file(path: Path) -> SongCandidate:
    return SongCandidate(
        video_id=f"{LOCAL_VIDEO_ID_PREFIX}{path}",
        title=path.stem,
        album=path.parent.name or None,
        source="local",
    )


def _audio_files(root: Path) -> list[Path]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in AUDIO_EXTENSIONS
    ]
    files.sort(key=lambda path: str(path).casefold())
    return files[:MAX_LOCAL_RESULTS]


def local_candidates(path_text: str) -> list[SongCandidate]:
    """Audio files at a path (file or directory, searched recursively)."""
    # Imported here: config -> transitions -> deck -> local_files at module load.
    from .config import ConfigError

    if not path_text.strip():
        raise ConfigError("Give a path, e.g. local:~/Music or /home/you/Music.")
    root = Path(path_text.strip()).expanduser()
    if not root.exists():
        raise ConfigError(f"Path not found: {root}")
    if root.is_file():
        if root.suffix.casefold() not in AUDIO_EXTENSIONS:
            raise ConfigError(f"Not a supported audio file: {root}")
        return [_candidate_from_file(root.resolve())]
    return [_candidate_from_file(path.resolve()) for path in _audio_files(root)]


def local_search_items(path_text: str) -> list[SearchItem]:
    return [
        search_item_from_song(candidate, source="local")
        for candidate in local_candidates(path_text)
    ]
