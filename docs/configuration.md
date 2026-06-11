# Configuration

## config.toml

Playback, layout, and builder options live in
`~/.config/bester-ytm/config.toml`. The file is optional; without it the
defaults below are in effect.

```toml
[playback]
transition = "crossfade"   # crossfade | cut
fade_seconds = 6.0         # crossfade length, 1-15
volume = 100               # startup volume, 0-100

[ui]
visualizer = "mythos"      # mythos | bars | wave | pulse | scope
left_width = 30            # pane widths in terminal cells
right_width = 44

[builder]
favorites_file = "~/music/favs.md"   # favorites used by seed-less builds

[intelligence]
provider = "auto"          # auto | heuristic | codex | openai | anthropic
```

- `transition = "crossfade"` (default): the next queued track is prebuffered
  on a second silent mpv deck and blended in with an equal-power fade;
  `"cut"` switches instantly.
- `visualizer`, `left_width`, `right_width`: written automatically when you
  change the visual style or drag the pane splitters in the TUI (mouse
  support required; inside tmux enable `set -g mouse on`).
- `favorites_file`: path to a favorites markdown file used by
  favorites-based playlist builds.
- `[intelligence]`: see [Playlist Builder & AI](builder.md#ai-providers).

Inspect the effective settings with:

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
~/.local/share/bester-ytm/track-metadata.json   ratings and tags
~/.local/share/bester-ytm/favorites.md          imported favorites
```

Auth files are written with mode `0600` in a `0700` directory and never
enter the repository. `XDG_CONFIG_HOME` and `XDG_DATA_HOME` are honored.
