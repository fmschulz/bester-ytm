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


def test_playlist_commands_report_a_corrupt_plan_without_a_traceback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    store = PlanStore()
    store.ensure()
    store.json_path("broken").write_text('{"id": "broken"}', encoding="utf-8")

    for command in (["playlist", "create", "broken"], ["playlist", "export", "broken"]):
        result = CliRunner().invoke(app, command)

        assert result.exit_code == 1, command
        assert "is corrupt" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)


def test_playlist_commands_report_an_unreadable_plan_without_a_traceback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    store = PlanStore()
    store.ensure()
    store.json_path("binary").write_bytes(b"\xff\xfe\x00not text")

    for command in (["playlist", "create", "binary"], ["playlist", "export", "binary"]):
        result = CliRunner().invoke(app, command)

        assert result.exit_code == 1, command
        assert "is corrupt" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)
