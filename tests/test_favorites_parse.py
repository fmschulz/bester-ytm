from pathlib import Path

from bester_ytm.playlist_plan import parse_favorites_markdown, parse_seed_text


def test_parse_tuiradio_favorites(tmp_path: Path) -> None:
    favs = tmp_path / "favs.md"
    favs.write_text(
        "\n".join(
            [
                "# TUI Radio Favorites",
                "- 2026-05-12 23:56:24 [ByteFM] Beach House - Myth",
                "- 2026-05-13 16:09:21 [ByteFM] Combo Chimbita;Nick Hakim - Perdón Divino",
                "- 2026-03-25 23:21:09 [ByteFM] Andrew Wasylyk"
                " - Private Symphony (feat. Stuart Murdoch9",
                "- malformed without separator",
                "- 2026-05-12 23:56:24 [ByteFM] Beach House - Myth",
            ]
        ),
        encoding="utf-8",
    )

    seeds = parse_favorites_markdown(favs)

    assert [seed.artist for seed in seeds] == [
        "Beach House",
        "Combo Chimbita;Nick Hakim",
        "Andrew Wasylyk",
    ]
    assert seeds[0].title == "Myth"
    assert seeds[0].station == "ByteFM"
    assert seeds[0].favorited_at == "2026-05-12 23:56:24"
    assert seeds[1].query == "Combo Chimbita;Nick Hakim Perdón Divino"


def test_parse_plain_seed_text() -> None:
    seeds = parse_seed_text(
        "\n".join(
            [
                "# Paste from notes",
                "1. Beach House - Myth",
                "My Bloody Valentine – Soon",
                "* Yo La Tengo | Autumn Sweater",
                "plain prose without an artist title separator",
                "Beach House - Myth",
            ]
        ),
        source="paste",
    )

    assert [(seed.artist, seed.title, seed.source) for seed in seeds] == [
        ("Beach House", "Myth", "paste"),
        ("My Bloody Valentine", "Soon", "paste"),
        ("Yo La Tengo", "Autumn Sweater", "paste"),
    ]
