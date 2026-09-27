"""Layout and theme-aware styling for the music workspace and visual stage."""

from __future__ import annotations

APP_CSS = """
Screen { layout: vertical; }
Header { display: none; }
#navigation { height: 1; background: $panel; }
#brand { width: 1fr; color: $accent; text-style: bold; padding-left: 1; }
Button { min-width: 5; margin: 0 1 0 0; }
#navigation Button { min-width: 6; }
#main { height: 1fr; }
#left { width: 3fr; }
#center { width: 3fr; }
#right { width: 2fr; min-width: 30; overflow-y: auto; scrollbar-size-vertical: 1; }
#left, #center, #right { border: round $primary-muted; padding: 0 1; }
#left, #center { min-width: 20; }
#left:focus-within, #center:focus-within, #right:focus-within { border: round $accent; }
PaneSplitter { width: 1; height: 1fr; background: $background; }
PaneSplitter:hover { background: $accent; }
#library-title, #queue-title, #tools-title { color: $accent; text-style: bold; height: 1; }
#search { margin: 0; }
#results, #queue, #album-tree { height: 1fr; }
#album-tree { display: none; }
#library-empty { height: auto; color: $text-muted; padding: 1 0; }
#results-hint, #queue-hint { height: 1; color: $text-muted; text-overflow: ellipsis; }
ListItem { padding: 0 1; }
ListItem Label { width: 1fr; text-overflow: ellipsis; }
#queue .playing { background: $primary-muted; color: $accent; text-style: bold; }
#album-tree .tree--cursor { background: $primary-muted; color: $accent; text-style: bold; }
Collapsible { padding: 0; margin: 0; border: none; }
Collapsible > Contents { padding: 0; }
#playlist-actions, #queue-actions, #builder-actions, #transition-row { height: auto; }
#playlist-actions Button { min-width: 3; margin-right: 1; }
#builder { height: 4; }
#stage { height: 40%; min-height: 7; background: $background; }
#stage-heading { height: 1; padding: 0 1; }
#effect-select { width: 14; }
#stage-button { dock: right; }
#big-visual { height: 1fr; background: $background; }
#player { height: 3; padding: 1 1 0 1; background: $panel; }
#now-playing, #seek-row { height: 1; }
#track { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
#transport { width: auto; height: 1; }
#transport Button { min-width: 4; margin: 0 0 0 1; }
#favorite-playing-button.is-favorite { color: $accent; }
#progress-time, #duration-time { width: auto; height: 1; color: $text-muted; }
#progress-time { margin-right: 1; }
#duration-time { margin-left: 1; }
#progress { width: 1fr; }
#crossfader { width: auto; height: 1; margin-left: 3; }
#volume-row { width: auto; height: 1; margin-left: 3; }
#volume-row Button { min-width: 3; margin: 0; }
#volume { width: auto; height: 1; margin: 0 1; }
#big-visual.paused-effect { opacity: 85%; }
#big-visual.idle-effect { opacity: 70%; }
#status { height: 1; padding: 0 1; color: $text-muted; text-overflow: ellipsis; }
Screen.immersive #main, Screen.immersive #navigation { display: none; }
Screen.immersive #stage { height: 1fr; }
Screen.compact #right, Screen.compact PaneSplitter { display: none; }
Screen.compact.tools-open #right { display: block; width: 1fr; min-width: 25; }
Screen.compact.tools-open #left { width: 1fr; }
Screen.compact.tools-open #center { display: none; }
Screen.compact #brand { display: none; }
Screen.compact #navigation Button { width: 1fr; }
Screen.compact #crossfader { display: none; }
Screen.short #library-empty { display: none; }
Screen.compact #results-hint, Screen.compact #queue-hint { display: none; }
Screen.short #stage { height: 7; }
Screen.short.immersive #stage { height: 1fr; }
"""
