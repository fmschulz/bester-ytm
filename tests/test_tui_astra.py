import pytest
from rich.cells import cell_len
from rich.text import Text

from bester_ytm.tui_visuals import render_visual_panel


@pytest.mark.parametrize("size", [(8, 3), (84, 13), (140, 34), (200, 60)])
def test_astra_markup_fills_compact_and_fullscreen_canvases(size) -> None:
    width, height = size
    frame = render_visual_panel(
        "astra", 24, width, height, running=True, levels=[0.4] * 11 + [0.85]
    )
    rows = Text.from_markup(frame).plain.splitlines()
    assert len(rows) == height
    assert all(cell_len(row) == width for row in rows)


def test_astra_brightens_on_loud_passages() -> None:
    def light(level: float) -> int:
        frame = render_visual_panel("astra", 24, 100, 25, running=True, levels=[level])
        plain = Text.from_markup(frame).plain
        return sum(plain.count(glyph) * weight for weight, glyph in enumerate(" ·∙░▒▓█"))

    assert light(1.0) > light(0.05) * 1.5
