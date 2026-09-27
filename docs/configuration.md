# Configuration

## config.toml

Playback, layout, and builder options live in
`~/.config/bester-ytm/config.toml`. The file is optional; without it the
defaults below are in effect (the lines marked "example" have no default
and stay unset until you write them).

```toml
[playback]
transition = "crossfade"   # crossfade | cut
fade_seconds = 6.0         # crossfade length, 1-15
volume = 100               # startup volume, 0-100

[ui]
visualizer = "astra"       # astra | pulsar | bars | scope
theme = "astra"            # astra | ember | any built-in Textual theme
visual_fps = 20            # animation rate, 0 (static frame) to 30
left_width = 30            # example; unset by default (see below)
right_width = 44           # example; unset by default

[builder]
favorites_file = "~/music/favs.md"   # example; unset by default

[intelligence]
provider = "auto"          # auto | heuristic | codex | claude | openai | anthropic

[radio.stations]
fip = "https://icecast.radiofrance.fr/fip-midfi.mp3"   # example; unset by default
```

- `transition = "crossfade"` (default): the next queued track is prebuffered
  on a second silent mpv deck and blended in with an equal-power fade;
  `"cut"` switches instantly.
- `visualizer`, `theme`, `left_width`, `right_width`: written automatically
  when you change the stage scene, pick a theme from the command palette
  (`Ctrl+Shift+P`), or drag the pane splitters in the TUI (mouse support
  required; inside tmux enable `set -g mouse on`).
- `left_width` / `right_width`: pane widths in terminal cells, valid range
  10-400 (values outside it raise a `ConfigError` at startup; the values
  above are examples). When unset, the panes use the stylesheet's fractional widths.
- `visualizer`: the stage scene. A name that is not one of the four scenes
  starts the stage on Astra.
- `visual_fps`: how often the stage redraws and samples live
  loudness. Lower it (or set `0` to freeze the stage) on slow or remote
  terminals. At `0` the seek bar shows progress without the loudness shape.
  Beat tracking becomes less accurate below about 15 frames per
  second. This setting is read at startup.
  Capped at 30: values above 30 (or below 0) are rejected with a
  `ConfigError` at startup.
- `favorites_file`: path to a favorites markdown file used by
  favorites-based playlist builds (the value above is an example; unset by
  default).
- `[intelligence]`: see [Playlist Builder & AI](builder.md#ai-providers).
- `[radio.stations]`: extra web radio stations for the `radio:` search, one
  `name = "stream url"` per line (ByteFM and KALX are built in). Song names
  for added stations come from the stream's ICY metadata when present.
  Typing `add radio station <name>` into the playlist builder writes this
  section for you: the AI provider finds the stream URL and bester-ytm
  verifies it plays before saving.

Inspect the effective transition settings (`[playback]` `transition` and
`fade_seconds`) with:

```bash
bester-ytm config show
```

## Data locations

```text
~/.config/bester-ytm/config.toml        settings (optional)
~/.config/bester-ytm/browser.json       browser login headers (default login)
~/.config/bester-ytm/oauth-client.json  OAuth client credentials (--oauth)
~/.config/bester-ytm/oauth.json         OAuth token (--oauth)
~/.local/share/bester-ytm/plans/        playlist plans (JSON + Markdown)
~/.local/share/bester-ytm/local-playlists/      TUI local playlists
~/.local/share/bester-ytm/favorites.json        faved songs (f / favs:)
~/.local/share/bester-ytm/favorites.md          legacy/imported favorites
```

Auth files are written with mode `0600` in a `0700` directory and never
enter the repository. `XDG_CONFIG_HOME` and `XDG_DATA_HOME` are honored.
