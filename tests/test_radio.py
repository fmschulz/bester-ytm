import io
import json
import subprocess
from pathlib import Path

import pytest

from bester_ytm import radio
from bester_ytm.deck import video_url
from bester_ytm.playback import PlaybackController, PlaybackStatus
from bester_ytm.radio import (
    RadioError,
    RadioNowPlaying,
    RadioStation,
    is_radio_video_id,
    now_playing,
    station_for,
    station_search_items,
    stations,
    stream_url_for,
)


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()


def _icy_stream(title: str, interval: int = 4) -> FakeResponse:
    metadata = f"StreamTitle='{title}';".encode()
    padded = metadata + b"\x00" * (-len(metadata) % 16)
    body = b"a" * interval + bytes([len(padded) // 16]) + padded
    return FakeResponse(body, {"icy-metaint": str(interval)})


def test_builtin_stations_and_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    keys = [station.key for station in stations()]

    assert keys == ["bytefm", "kalx"]
    assert is_radio_video_id("radio:bytefm")
    assert not is_radio_video_id("abc123")
    assert stream_url_for("radio:kalx") == radio.KALX_STREAM


def test_config_adds_extra_icy_stations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config" / "bester-ytm"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        '[radio.stations]\nfip = "https://icecast.radiofrance.fr/fip-midfi.mp3"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    result = stations()

    assert [station.key for station in result] == ["bytefm", "kalx", "fip"]
    assert result[-1].kind == "icy"
    assert stream_url_for("radio:fip").endswith("fip-midfi.mp3")


def test_unknown_station_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    with pytest.raises(RadioError, match="Unknown radio station"):
        station_for("radio:nope")


def test_station_search_items_are_radio_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    items = station_search_items()

    assert [item.title for item in items] == ["ByteFM", "KALX 90.7FM"]
    assert all(item.item_type == "radio" for item in items)
    assert items[0].display_name.startswith("RADIO  ByteFM")
    assert all(item.candidate is not None for item in items)
    assert items[0].candidate.video_id == "radio:bytefm"


def test_icy_now_playing_parses_stream_title(monkeypatch: pytest.MonkeyPatch) -> None:
    station = RadioStation(key="fip", name="fip", stream_url="https://x/stream")
    monkeypatch.setattr(
        radio, "_open_url", lambda url, headers=None: _icy_stream("Beach House - Myth")
    )

    info = now_playing(station)

    assert info.artist == "Beach House"
    assert info.song == "Myth"
    assert info.display == "Beach House - Myth"


def test_bytefm_now_playing_merges_api_show_and_icy_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_payload = json.dumps(
        {"broadcast_title": "Golden Glades", "show_subtitle": "mit Juli", "moderator": "Juli"}
    ).encode()

    def fake_open(url, headers=None):
        if url == radio.BYTEFM_API:
            return FakeResponse(api_payload)
        return _icy_stream("Sault - Wildfires")

    monkeypatch.setattr(radio, "_open_url", fake_open)

    info = now_playing(radio.BUILTIN_STATIONS[0])

    assert info.artist == "Sault"
    assert info.song == "Wildfires"
    assert info.show == "Golden Glades / mit Juli"
    assert info.host == "Juli"
    assert "Golden Glades" in info.display


def test_kalx_now_playing_scrapes_page(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        '<p class="artist large-17 bold">Stereolab\t</p>'
        '<p class="song">French Disko\t<span class="time small-15">from '
        "Refried Ectoplasm ...</span></p>"
    )
    monkeypatch.setattr(radio, "_open_url", lambda url, headers=None: FakeResponse(html.encode()))

    info = now_playing(radio.BUILTIN_STATIONS[1])

    assert info.artist == "Stereolab"
    assert info.song == "French Disko"


def test_now_playing_without_icy_metadata_is_live_radio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    station = RadioStation(key="x", name="X", stream_url="https://x/stream")
    monkeypatch.setattr(radio, "_open_url", lambda url, headers=None: FakeResponse(b"audio"))

    info = now_playing(station)

    assert info.display == "Live radio"


def test_video_url_resolves_radio_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert video_url("radio:bytefm") == radio.BYTEFM_STREAM


def test_play_video_radio_skips_yt_dlp_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    calls: list[list[str]] = []

    class FakeProcess:
        returncode = None

        def poll(self) -> None:
            return None

    controller = PlaybackController()
    monkeypatch.setattr(controller, "_mpv_path", lambda: "mpv")
    monkeypatch.setattr("bester_ytm.playback.shutil.which", lambda name: None)
    monkeypatch.setattr(
        subprocess, "Popen", lambda cmd, **kwargs: calls.append(cmd) or FakeProcess()
    )
    monkeypatch.setattr("bester_ytm.playback.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        controller,
        "status",
        lambda: PlaybackStatus(running=True, current_video_id=controller.current_video_id),
    )

    status = controller.play_video("radio:kalx")

    assert status.current_video_id == "radio:kalx"
    assert radio.KALX_STREAM in calls[0]


def test_now_playing_display_variants() -> None:
    assert RadioNowPlaying(station="X", show="Morning Show").display == "Morning Show"
    assert (
        RadioNowPlaying(station="X", artist="A", song="B", show="S").display == "A - B (S)"
    )


def test_settings_rewrite_preserves_radio_stations_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bester_ytm.config import load_config_document, rewrite_config_sections

    config = tmp_path / "config.toml"
    config.write_text(
        '[radio.stations]\nfip = "https://icecast.example/fip.mp3"\n', encoding="utf-8"
    )

    rewrite_config_sections({"ui": {"theme": "ember"}}, config)

    document = load_config_document(config)
    assert document["ui"]["theme"] == "ember"
    assert document["radio"]["stations"]["fip"] == "https://icecast.example/fip.mp3"


def test_play_video_unknown_station_raises_playback_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bester_ytm.playback import PlaybackError

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    controller = PlaybackController()
    monkeypatch.setattr(controller, "_mpv_path", lambda: "mpv")

    with pytest.raises(PlaybackError, match="Unknown radio station"):
        controller.play_video("radio:gone")


def test_add_station_writes_config_and_keeps_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bester_ytm.radio import add_station

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = tmp_path / "config" / "bester-ytm" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        '[radio.stations]\nfip = "https://icecast.example/fip.mp3"\n', encoding="utf-8"
    )

    station = add_station("WFMU", "https://stream.wfmu.org/freeform-128k")

    assert station.key == "wfmu"
    keys = [s.key for s in stations()]
    assert keys == ["bytefm", "kalx", "fip", "wfmu"]
    assert stream_url_for("radio:wfmu") == "https://stream.wfmu.org/freeform-128k"


def test_add_station_rejects_builtin_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bester_ytm.radio import add_station

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    with pytest.raises(RadioError, match="matches an existing station"):
        add_station("ByteFM", "https://example.com/stream")
    # An AI suggestion may carry the built-in slug under a longer display name.
    with pytest.raises(RadioError, match="matches an existing station"):
        add_station("KALX 90.7FM", "https://example.com/stream", key="kalx")


def test_probe_stream_accepts_audio_and_rejects_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bester_ytm.radio import probe_stream

    monkeypatch.setattr(
        radio,
        "_open_url",
        lambda url, headers=None: FakeResponse(b"data", {"content-type": "audio/mpeg"}),
    )
    probe_stream("https://ok.example/stream")

    monkeypatch.setattr(
        radio,
        "_open_url",
        lambda url, headers=None: FakeResponse(b"<html>", {"content-type": "text/html"}),
    )
    with pytest.raises(RadioError, match="not an audio stream"):
        probe_stream("https://bad.example/page")


def test_add_station_with_spaces_in_name_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bester_ytm.radio import add_station

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    add_station("Groove Salad", "https://ice5.somafm.com/groovesalad-256-mp3")

    result = {s.key: s.stream_url for s in stations()}
    assert result["groove salad"] == "https://ice5.somafm.com/groovesalad-256-mp3"


def test_probe_stream_rejects_playlist_urls_and_mime_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bester_ytm.radio import probe_stream

    with pytest.raises(RadioError, match="playlist file"):
        probe_stream("https://example.com/listen.m3u")
    with pytest.raises(RadioError, match="playlist file"):
        probe_stream("https://example.com/listen.pls?arg=1")

    monkeypatch.setattr(
        radio,
        "_open_url",
        lambda url, headers=None: FakeResponse(
            b"#EXTM3U", {"content-type": "audio/x-mpegurl"}
        ),
    )
    with pytest.raises(RadioError, match="serves a playlist"):
        probe_stream("https://example.com/stream")
