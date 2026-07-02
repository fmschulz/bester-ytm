"""Stylesheet for the BesterYTMApp screen."""

from __future__ import annotations

APP_CSS = """
Screen {
    layout: vertical;
}
#main {
    height: 1fr;
}
#left {
    width: 2fr;
}
#center {
    width: 3fr;
}
#right {
    width: 2fr;
}
#left, #center, #right {
    border: solid #5b4a55;
    padding: 1;
}
#left, #right {
    min-width: 16;
}
#center {
    min-width: 20;
}
PaneSplitter {
    width: 1;
    height: 1fr;
    background: #3b2330;
}
PaneSplitter:hover {
    background: #e07a5f;
}
#right {
    overflow-y: auto;
    scrollbar-size-vertical: 1;
}
#right.playing-effect {
    border: heavy #e07a5f;
}
#right.paused-effect {
    border: heavy #9ca3af;
}
#left:focus-within, #center:focus-within, #right:focus-within {
    border: heavy #e07a5f;
}
#search {
    dock: top;
    margin-bottom: 1;
}
#queue-title, #player-title,
#playlist-section-title, #builder-title {
    color: #e07a5f;
    text-style: bold;
}
#playlist-section-title, #builder-title {
    margin-top: 1;
}
#queue {
    height: 1fr;
}
#results {
    height: 1fr;
}
#album-tree {
    height: 1fr;
    display: none;
}
#album-tree .tree--cursor {
    background: #3b2330;
    color: #f2cc8f;
    text-style: bold;
}
#big-visual, #left-visual, #right-visual {
    margin-top: 1;
    color: #e07a5f;
}
#big-visual {
    height: 9;
}
#left-visual {
    height: 8;
}
#right-visual {
    dock: bottom;
    height: 7;
}
#big-visual.idle-effect,
#left-visual.idle-effect,
#right-visual.idle-effect {
    color: #6b7280;
}
#big-visual.paused-effect,
#left-visual.paused-effect,
#right-visual.paused-effect {
    color: #9ca3af;
}
#queue .playing {
    background: #3b2330;
    color: #f2cc8f;
    text-style: bold;
}
#track {
    min-height: 3;
    margin-bottom: 1;
}
#progress-time {
    height: 1;
}
#progress {
    margin: 0 0 1 0;
}
#visualizer {
    height: 1;
    margin: 0;
    color: #eda36c;
}
#visualizer.idle-effect {
    color: #6b7280;
}
#visualizer.paused-effect {
    color: #9ca3af;
}
#transport, #queue-actions, #volume-row, #transition-row, #playlist-actions {
    height: auto;
    layout: horizontal;
}
#transition-row {
    margin-bottom: 1;
}
Button {
    margin-right: 1;
    min-width: 5;
}
#builder {
    height: 4;
}
#builder-actions {
    height: auto;
    layout: horizontal;
    margin-top: 1;
}
#effect-row {
    height: auto;
    layout: horizontal;
    margin-top: 1;
}
#effect-label {
    margin-right: 1;
    padding-top: 1;
}
#effect-select {
    width: 20;
}
#status {
    height: auto;
    margin-top: 1;
}
HelpScreen {
    align: center middle;
}
#help-panel {
    width: 60;
    max-width: 90%;
    height: auto;
    max-height: 90%;
    border: heavy #e07a5f;
    padding: 1 2;
    scrollbar-size-vertical: 1;
}
#help-title {
    color: #e07a5f;
    text-style: bold;
}
#help-hint {
    color: #6b7280;
    margin-top: 1;
}
.help-section {
    color: #e07a5f;
    text-style: bold;
    margin-top: 1;
}
.help-row {
    height: 1;
}
.help-key {
    width: 13;
    text-align: right;
    color: #f2cc8f;
    text-style: bold;
}
.help-desc {
    width: 1fr;
    padding-left: 2;
}
"""
