import subprocess
from pathlib import Path

import pytest

from bester_ytm.config import ConfigError
from bester_ytm.deck import video_url
from bester_ytm.local_files import (
    is_local_video_id,
    local_candidates,
    local_path,
    local_search_items,
)
from bester_ytm.playback import PlaybackController, PlaybackStatus


def _make_music_dir(tmp_path: Path) -> Path:
    music = tmp_path / "music"
    (music / "album").mkdir(parents=True)
    (music / "b-song.mp3").write_bytes(b"x")
    (music / "album" / "a-song.flac").write_bytes(b"x")
    (music / "notes.txt").write_text("not audio", encoding="utf-8")
    return music


def test_local_candidates_scans_directory_recursively_sorted(tmp_path: Path) -> None:
    music = _make_music_dir(tmp_path)

    candidates = local_candidates(str(music))

    assert [c.title for c in candidates] == ["a-song", "b-song"]
    assert candidates[0].video_id == f"local:{(music / 'album' / 'a-song.flac').resolve()}"
    assert candidates[0].album == "album"
    assert all(c.source == "local" for c in candidates)


def test_local_candidates_single_file(tmp_path: Path) -> None:
    song = tmp_path / "song.ogg"
    song.write_bytes(b"x")

    candidates = local_candidates(str(song))

    assert len(candidates) == 1
    assert candidates[0].video_id == f"local:{song.resolve()}"


def test_local_candidates_rejects_missing_path_and_non_audio(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Path not found"):
        local_candidates(str(tmp_path / "nope"))
    text = tmp_path / "notes.txt"
    text.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError, match="Not a supported audio file"):
        local_candidates(str(text))
    with pytest.raises(ConfigError, match="Give a path"):
        local_candidates("   ")


def test_local_search_items_are_songs_with_candidates(tmp_path: Path) -> None:
    music = _make_music_dir(tmp_path)

    items = local_search_items(str(music))

    assert all(item.item_type == "song" for item in items)
    assert all(item.candidate is not None for item in items)
    assert items[0].video_id and is_local_video_id(items[0].video_id)


def test_video_url_passes_local_paths_through() -> None:
    assert video_url("local:/home/me/song.mp3") == "/home/me/song.mp3"
    assert video_url("abc123") == "https://music.youtube.com/watch?v=abc123"
    assert local_path("local:/a/b.mp3") == "/a/b.mp3"


def test_play_video_local_file_skips_yt_dlp_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    song = tmp_path / "song.mp3"
    song.write_bytes(b"x")
    calls: list[list[str]] = []

    class FakeProcess:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return FakeProcess()

    controller = PlaybackController()
    monkeypatch.setattr(controller, "_mpv_path", lambda: "mpv")
    monkeypatch.setattr("bester_ytm.playback.shutil.which", lambda name: None)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("bester_ytm.playback.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        controller,
        "status",
        lambda: PlaybackStatus(running=True, current_video_id=controller.current_video_id),
    )

    status = controller.play_video(f"local:{song}")

    assert status.current_video_id == f"local:{song}"
    assert str(song) in calls[0]
