from __future__ import annotations

from pathlib import Path

import pytest

from bester_ytm.config import ConfigError, get_paths, save_transition_settings
from bester_ytm.config_options import AppOptions, load_app_options, save_ui_options
from bester_ytm.transitions import TransitionSettings, TransitionStyle


def _sandbox(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return get_paths().config_file


def test_defaults_when_config_missing(tmp_path: Path, monkeypatch) -> None:
    _sandbox(tmp_path, monkeypatch)

    assert load_app_options() == AppOptions()


def test_ui_options_round_trip(tmp_path: Path, monkeypatch) -> None:
    _sandbox(tmp_path, monkeypatch)

    save_ui_options("bars", left_width=30, right_width=44)
    options = load_app_options()

    assert options.visualizer == "bars"
    assert options.left_width == 30
    assert options.right_width == 44


def test_saving_visualizer_alone_keeps_widths(tmp_path: Path, monkeypatch) -> None:
    _sandbox(tmp_path, monkeypatch)
    save_ui_options("mythos", left_width=28, right_width=40)

    save_ui_options("wave")
    options = load_app_options()

    assert options.visualizer == "wave"
    assert options.left_width == 28
    assert options.right_width == 40


def test_ui_and_transition_saves_preserve_each_other(tmp_path: Path, monkeypatch) -> None:
    path = _sandbox(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True)
    path.write_text('[intelligence]\nprovider = "codex"\n', encoding="utf-8")

    save_ui_options("pulse", left_width=25, right_width=35)
    save_transition_settings(TransitionSettings(style=TransitionStyle.CUT, fade_seconds=4.0))
    options = load_app_options()

    assert options.visualizer == "pulse"
    assert options.left_width == 25
    text = path.read_text(encoding="utf-8")
    assert 'provider = "codex"' in text
    assert 'transition = "cut"' in text


def test_volume_and_favorites_load(tmp_path: Path, monkeypatch) -> None:
    path = _sandbox(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True)
    path.write_text(
        '[playback]\nvolume = 55\n\n[builder]\nfavorites_file = "~/music/favs.md"\n',
        encoding="utf-8",
    )

    options = load_app_options()

    assert options.volume == 55.0
    assert options.favorites_file == Path("~/music/favs.md").expanduser()


@pytest.mark.parametrize(
    "content, message",
    [
        ("[playback]\nvolume = 250\n", "playback.volume"),
        ('[playback]\nvolume = "loud"\n', "playback.volume"),
        ("[ui]\nleft_width = 4\n", "ui.left_width"),
        ('[ui]\nright_width = "wide"\n', "ui.right_width"),
        ("[ui]\nvisualizer = 7\n", "ui.visualizer"),
        ('[builder]\nfavorites_file = ""\n', "builder.favorites_file"),
    ],
)
def test_invalid_options_raise_config_error(
    tmp_path: Path, monkeypatch, content: str, message: str
) -> None:
    path = _sandbox(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_app_options()
