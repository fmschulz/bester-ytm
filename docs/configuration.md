# Configuration

## config.toml

Settings live in `~/.config/bester-ytm/config.toml`. The file is optional;
without it the defaults below apply. Lines marked "example" have no default.

```toml
[playback]
transition = "crossfade"   # crossfade | cut
fade_seconds = 6.0         # crossfade length, 1-15
volume = 100               # startup volume, 0-100

[ui]
visualizer = "astra"       # astra | pulsar | bars | scope
theme = "astra"            # astra | ember | any built-in Textual theme
visual_fps = 20            # animation rate, 0 (still frames) to 30
left_width = 30            # example
right_width = 44           # example

[builder]
favorites_file = "~/music/favs.md"   # example

[intelligence]
provider = "auto"          # auto | heuristic | codex | claude | openai | anthropic

[radio.stations]
fip = "https://icecast.radiofrance.fr/fip-midfi.mp3"   # example
```

- `transition`: `crossfade` prebuffers the next track on a second mpv deck and
  blends it in with an equal-power fade; `cut` switches instantly.
- `visualizer`, `theme`, `left_width`, `right_width`: the TUI writes these when
  you change the scene, pick a theme in the command palette (`Ctrl+Shift+P`),
  or drag a pane splitter. Dragging needs mouse support; in tmux, set
  `set -g mouse on`.
- `visualizer`: an unknown name starts the stage on Astra.
- `left_width`, `right_width`: pane widths in terminal cells, 10-400. Without
  them, the panes share the width by the stylesheet's ratios.
- `visual_fps`: how often the stage redraws and samples loudness, 0-30, read
  at startup. Lower it on slow or remote terminals; `0` freezes the stage and
  drops the seek bar's loudness shape. Beat tracking gets less accurate below
  about 15.
- `favorites_file`: the seeds file for favorites-based builds.
- `[intelligence]`: see [Playlist Builder & AI](builder.md#ai-providers).
- `[radio.stations]`: extra stations for `radio:`, one `name = "stream url"`
  per line. Song names come from the stream's ICY metadata when present. The
  builder's `add radio station <name>` writes this section for you.

Values out of range raise a `ConfigError` at startup. `bester-ytm config show`
prints the effective `transition` and `fade_seconds`.

## Data locations

```text
~/.config/bester-ytm/config.toml             settings (optional)
~/.config/bester-ytm/browser.json            browser login (default login)
~/.config/bester-ytm/oauth-client.json       OAuth client credentials (--oauth)
~/.config/bester-ytm/oauth.json              OAuth token (--oauth)
~/.local/share/bester-ytm/plans/             playlist plans (JSON and Markdown)
~/.local/share/bester-ytm/local-playlists/   local playlists
~/.local/share/bester-ytm/favorites.json     favorites (f, favs:)
~/.local/share/bester-ytm/favorites.md       legacy or imported favorites
```

Login files are written with mode `0600` in a `0700` directory. The app honors
`XDG_CONFIG_HOME` and `XDG_DATA_HOME`.
