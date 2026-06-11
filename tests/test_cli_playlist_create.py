from pathlib import Path

from typer.testing import CliRunner

from bester_ytm import cli
from bester_ytm.cli import app
from bester_ytm.config import ConfigError
from bester_ytm.playlist_plan import PlannedTrack, PlaylistPlan, SeedTrack, SongCandidate
from bester_ytm.stores import PlanStore


def test_playlist_create_handles_client_config_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    plan = PlaylistPlan(
        id="plan-with-track",
        name="Plan With Track",
        target_count=1,
        seed_tracks=[SeedTrack(artist="Beach House", title="Myth", source="favs.md")],
        planned_tracks=[
            PlannedTrack(
                artist="Beach House",
                title="Myth",
                reason="Seed favorite.",
                role="seed",
                query="Beach House Myth",
                candidates=[SongCandidate(video_id="v1", title="Myth", artists=["Beach House"])],
                selected_video_id="v1",
                confidence=1.0,
            )
        ],
    )
    PlanStore().save(plan)

    class RaisingClient:
        def __init__(self, authenticated: bool = True) -> None:
            raise ConfigError("No auth configured")

    monkeypatch.setattr(cli, "YTMClient", RaisingClient)

    result = CliRunner().invoke(app, ["playlist", "create", plan.id])

    assert result.exit_code == 1
    assert "No auth configured" in result.output
    assert "Traceback" not in result.output
