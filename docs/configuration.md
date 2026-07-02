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
visualizer = "mythos"      # mythos | oracle | bars | wave | pulse | scope
theme = "ember"            # ember (branded) or any built-in Textual theme
visual_fps = 20            # animation rate, 0 (panels off) to 30
left_width = 30            # example; unset by default (see below)
right_width = 44           # example; unset by default

[builder]
favorites_file = "~/music/favs.md"   # example; unset by default

[intelligence]
provider = "auto"          # auto | heuristic | codex | openai | anthropic
```

- `transition = "crossfade"` (default): the next queued track is prebuffered
  on a second silent mpv deck and blended in with an equal-power fade;
  `"cut"` switches instantly.
- `visualizer`, `theme`, `left_width`, `right_width`: written automatically
  when you change the visual style, pick a theme from the command palette (the
  circle in the header), or drag the pane splitters in the TUI (mouse support
  required; inside tmux enable `set -g mouse on`).
- `left_width` / `right_width`: pane widths in terminal cells, valid range
  10-400 (values outside it raise a `ConfigError` at startup; the values
  above are examples). Unset by default — the panes then fall back to the
  stylesheet's fractional widths.
- `visual_fps`: how often the audio-reactive panels redraw and sample live
  loudness. Lower it (or set `0` to freeze the panels) on slow or remote
  terminals — beat tracking loosens below ~15 — it is read at startup only.
  Capped at 30: values above 30 (or below 0) are rejected with a
  `ConfigError` at startup.
- `favorites_file`: path to a favorites markdown file used by
  favorites-based playlist builds (the value above is an example; unset by
  default).
- `[intelligence]`: see [Playlist Builder & AI](builder.md#ai-providers).

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
