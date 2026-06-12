"""The branded 'ember' Textual theme, matched to the visualizer palette."""

from __future__ import annotations

from textual.theme import Theme

# Warm ember tones that echo tui_visuals.PALETTE (deep rust to white-hot crest).
EMBER_THEME = Theme(
    name="ember",
    primary="#e07a5f",
    secondary="#eda36c",
    accent="#f2cc8f",
    foreground="#f4e3d3",
    background="#1a1014",
    surface="#241319",
    panel="#3b2330",
    success="#8fb88f",
    warning="#eda36c",
    error="#d6584f",
    dark=True,
    variables={
        "border": "#5b4a55",
        "block-cursor-background": "#e07a5f",
        "block-cursor-foreground": "#1a1014",
        "input-selection-background": "#c96442 35%",
    },
)
