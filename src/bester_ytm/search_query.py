from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .playlist_plan import SongCandidate

SearchKind = Literal["free", "song", "artist", "album", "playlist", "favorites"]
SearchView = Literal["songs", "albums", "playlists"]
SearchItemType = Literal["song", "album", "playlist", "local_playlist"]


class ParsedSearch(BaseModel):
    raw: str
    kind: SearchKind
    text: str = ""
    view: SearchView = "songs"
    year: int | None = None

    @property
    def lists_local_playlists(self) -> bool:
        return self.kind == "playlist" and not self.text

    @property
    def lists_favorites(self) -> bool:
        return self.kind == "favorites"


class SearchItem(BaseModel):
    item_type: SearchItemType
    title: str
    subtitle: str = ""
    source: str = "ytmusic"
    video_id: str | None = None
    browse_id: str | None = None
    playlist_id: str | None = None
    year: str | None = None
    track_count: int | None = None
    candidate: SongCandidate | None = None

    @property
    def display_name(self) -> str:
        prefix = self.item_type.replace("_", " ").upper()
        details = self.subtitle
        if self.year and self.year not in details:
            details = f"{details} ({self.year})" if details else self.year
        return f"{prefix}  {self.title}" + (f" - {details}" if details else "")


def parse_search_query(value: str) -> ParsedSearch:
    raw = value.strip()
    if not raw:
        return ParsedSearch(raw=value, kind="free")

    parts = [part.strip() for part in raw.split(",") if part.strip()]
    head = parts[0] if parts else raw
    rest = parts[1:]

    kind: SearchKind = "free"
    text = raw
    view: SearchView = "songs"
    year: int | None = None

    for prefix, parsed_kind in (
        ("songs:", "song"),
        ("song:", "song"),
        ("artist:", "artist"),
        ("albums:", "album"),
        ("album:", "album"),
        ("playlists:", "playlist"),
        ("playlist:", "playlist"),
        ("favorites:", "favorites"),
        ("favs:", "favorites"),
    ):
        if head.casefold().startswith(prefix):
            kind = parsed_kind  # type: ignore[assignment]
            text = head[len(prefix) :].strip()
            break

    for token in rest:
        folded = token.casefold()
        if folded == "songs":
            view = "songs"
        elif folded == "albums":
            view = "albums"
        elif folded == "playlists":
            view = "playlists"
        elif folded.startswith("year:"):
            year_text = token.split(":", 1)[1].strip()
            if year_text.isdigit():
                year = int(year_text)

    if kind == "playlist":
        view = "playlists"
    elif kind == "album":
        view = "albums"
    elif kind == "artist" and view not in {"songs", "albums"}:
        view = "songs"
    elif kind in {"song", "favorites"}:
        view = "songs"

    return ParsedSearch(raw=value, kind=kind, text=text, view=view, year=year)


def search_item_from_song(candidate: SongCandidate, *, source: str = "search") -> SearchItem:
    details = candidate.artist_text
    if candidate.album:
        details = f"{details} | {candidate.album}" if details else candidate.album
    return SearchItem(
        item_type="song",
        title=candidate.title,
        subtitle=details,
        source=source,
        video_id=candidate.video_id,
        candidate=candidate,
    )
