from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

SEED_LINE_RE = re.compile(
    r"^\s*(?:[-*]|\d+[.)])?\s*"
    r"(?:(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+)?"
    r"(?:\[(?P<station>[^\]]+)\]\s+)?"
    r"(?P<body>.+?)\s*$"
)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "playlist"


class SeedTrack(BaseModel):
    artist: str
    title: str
    source: str
    station: str | None = None
    favorited_at: str | None = None

    @property
    def query(self) -> str:
        return f"{self.artist} {self.title}".strip()


class SongCandidate(BaseModel):
    video_id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    year: str | None = None
    duration_seconds: int | None = None
    result_type: str | None = None
    is_explicit: bool | None = None
    source: str = "ytmusic"

    @field_validator("video_id")
    @classmethod
    def non_empty_video_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("video_id must not be empty")
        return value.strip()

    @property
    def artist_text(self) -> str:
        return ", ".join(self.artists)

    @property
    def display_name(self) -> str:
        if self.artist_text:
            return f"{self.artist_text} - {self.title}"
        return self.title


class RankedCandidate(BaseModel):
    candidate: SongCandidate
    score: float
    reason: str


class PlannedTrack(BaseModel):
    artist: str
    title: str
    reason: str
    role: str = "related"
    query: str
    candidates: list[SongCandidate] = Field(default_factory=list)
    selected_video_id: str | None = None
    confidence: float = 0.0

    @property
    def selected_candidate(self) -> SongCandidate | None:
        if self.selected_video_id is None:
            return None
        for candidate in self.candidates:
            if candidate.video_id == self.selected_video_id:
                return candidate
        return None


class PlaylistPlan(BaseModel):
    id: str
    name: str
    target_count: int
    seed_tracks: list[SeedTrack] = Field(default_factory=list)
    planned_tracks: list[PlannedTrack] = Field(default_factory=list)
    brief: str = ""
    playlist_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str | None = None
    verified: bool = False

    @property
    def resolved_count(self) -> int:
        return sum(1 for track in self.planned_tracks if track.selected_video_id)

    def resolved_candidates(self) -> list[SongCandidate]:
        """Playable candidates for every resolved planned track, in plan order."""
        candidates: list[SongCandidate] = []
        seen: set[str] = set()
        for track in self.planned_tracks:
            video_id = track.selected_video_id
            if not video_id or video_id in seen:
                continue
            candidate = track.selected_candidate or SongCandidate(
                video_id=video_id, title=track.title, artists=[track.artist]
            )
            candidates.append(candidate)
            seen.add(video_id)
        return candidates

    @property
    def selected_video_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for track in self.planned_tracks:
            if track.selected_video_id and track.selected_video_id not in seen:
                ids.append(track.selected_video_id)
                seen.add(track.selected_video_id)
        return ids

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat()


def new_plan_id(name: str, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{slugify(name)}"


def split_artist_title(body: str) -> tuple[str, str] | None:
    cleaned = body.strip()
    if not cleaned:
        return None

    separators = [" - ", " – ", " — ", " | "]
    for separator in separators:
        if separator in cleaned:
            artist, title = cleaned.split(separator, 1)
            artist = artist.strip()
            title = title.strip()
            if artist and title:
                return artist, title
    return None


def parse_seed_text(text: str, source: str) -> list[SeedTrack]:
    seeds: list[SeedTrack] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = SEED_LINE_RE.match(line)
        if not match:
            continue
        parsed = split_artist_title(match.group("body"))
        if not parsed:
            continue
        artist, title = parsed
        key = (artist.casefold(), title.casefold())
        if key in seen:
            continue
        seen.add(key)
        seeds.append(
            SeedTrack(
                artist=artist,
                title=title,
                source=source,
                station=match.group("station"),
                favorited_at=match.group("timestamp"),
            )
        )
    return seeds


def parse_seed_file(path: Path) -> list[SeedTrack]:
    return parse_seed_text(path.read_text(encoding="utf-8"), str(path))


def parse_favorites_markdown(path: Path) -> list[SeedTrack]:
    return parse_seed_file(path)


def plan_to_markdown(plan: PlaylistPlan) -> str:
    lines = [
        f"# {plan.name}",
        "",
        f"- Plan ID: `{plan.id}`",
        f"- Target count: {plan.target_count}",
        f"- Resolved tracks: {plan.resolved_count}/{len(plan.planned_tracks)}",
    ]
    if plan.playlist_id:
        lines.append(f"- YouTube Music playlist: `{plan.playlist_id}`")
    if plan.brief:
        lines.extend(["", "## Brief", "", plan.brief])
    lines.extend(["", "## Seeds", ""])
    for seed in plan.seed_tracks:
        meta = f" ({seed.station})" if seed.station else ""
        lines.append(f"- {seed.artist} - {seed.title}{meta}")
    lines.extend(["", "## Planned Tracks", ""])
    for index, track in enumerate(plan.planned_tracks, start=1):
        selected = track.selected_video_id or "unresolved"
        lines.append(
            f"{index}. **{track.artist} - {track.title}** "
            f"`{selected}` [{track.role}, {track.confidence:.2f}]"
        )
        lines.append(f"   - {track.reason}")
    lines.append("")
    return "\n".join(lines)
