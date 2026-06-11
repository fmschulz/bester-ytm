from __future__ import annotations

from pydantic import BaseModel, Field

from .playlist_plan import PlaylistPlan
from .stores import PlanStore
from .ytm_client import YTMClient


class PlaylistCreateError(RuntimeError):
    pass


class PlaylistCreateResult(BaseModel):
    playlist_id: str
    created: bool
    requested_video_ids: list[str] = Field(default_factory=list)
    missing_video_ids: list[str] = Field(default_factory=list)

    @property
    def verified(self) -> bool:
        return not self.missing_video_ids


def playlist_description(plan: PlaylistPlan) -> str:
    return (
        f"Created by bester-ytm from plan {plan.id}. "
        f"Seeds: {', '.join(seed.query for seed in plan.seed_tracks[:8])}"
    )


def create_or_update_playlist(
    plan: PlaylistPlan,
    client: YTMClient,
    store: PlanStore,
    privacy: str = "PRIVATE",
) -> PlaylistCreateResult:
    video_ids = plan.selected_video_ids
    if not video_ids:
        raise PlaylistCreateError("Plan has no resolved video IDs; run playlist build again.")

    created = False
    if plan.playlist_id:
        playlist_id = plan.playlist_id
    else:
        playlist_id = client.create_playlist(
            plan.name,
            playlist_description(plan),
            privacy,
            [],
        )
        plan.playlist_id = playlist_id
        store.save(plan)
        created = True
    plan.verified = False
    store.save(plan)
    client.add_playlist_items(playlist_id, video_ids)
    snapshot = client.get_playlist(playlist_id)

    present = set(snapshot.video_ids)
    missing = [video_id for video_id in video_ids if video_id not in present]
    plan.verified = not missing
    store.save(plan)
    return PlaylistCreateResult(
        playlist_id=playlist_id,
        created=created,
        requested_video_ids=video_ids,
        missing_video_ids=missing,
    )
