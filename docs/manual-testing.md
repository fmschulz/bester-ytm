# Manual Test Checklist

These checks need audio or a login, so the automated tests skip them.

## Auth

- [ ] `uv run bester-ytm auth login` finds an installed browser, reads the
      login, prints `Login verified (...)`, and writes
      `~/.config/bester-ytm/browser.json` with mode `0600`.
- [ ] `uv run bester-ytm auth login --paste` accepts a `Copy as cURL` request
      ended by a blank line (no `Ctrl-D`) and writes the same file.
- [ ] `uv run bester-ytm auth login --oauth` prints the Google Cloud setup
      steps on the first run, asks for the client ID and secret, and starts
      the device flow; `oauth-client.json` has mode `0600`.
- [ ] `uv run bester-ytm auth status` reports an authenticated library request
      without printing tokens.
- [ ] The TUI status line shows a login hint without a login and
      `Logged in to YouTube Music.` with one.

## Playlists

- [ ] `uv run bester-ytm playlist build --from examples/seeds.txt --name
      "Test Mix" --count 30` writes a JSON and a Markdown plan.
- [ ] The plan has 30 tracks with resolved `videoId`s, a reason for each, and
      no obvious cover, live, or remix picks unless requested.
- [ ] `uv run bester-ytm playlist create <plan-id>` creates or updates the
      playlist and confirms its tracks.

## Playback

- [ ] `uv run bester-ytm play search "Beach House Myth" --seconds 20` plays
      audio through `mpv` and exits cleanly.
- [ ] In `uv run bester-ytm`, search, queue, play and pause, skip, favorites
      (`f`, the `★` marker, `Ctrl+F`), login status, and the builder respond to
      the documented keys.
- [ ] While a song plays, the seek bar fills with its loudness shape up to the
      playhead; seeking ahead leaves a flat stretch; clicking the bar seeks.
- [ ] After `./scripts/download-example-songs.sh`, `local:examples/music`
      lists three songs, `Enter` plays one, and crossfades work between local
      and YouTube tracks.
- [ ] `radio:` lists ByteFM and KALX; `Enter` plays a station, the player
      shows the live track within about 20 seconds, and `f` saves a YouTube
      Music match without a login.
- [ ] `F1` opens help while typing, filtering by `favorite` finds the favorite
      keys, and `F1` closes help and restores input focus.
- [ ] `V` or a click on the stage shows it full screen; `Ctrl+Space` pauses;
      a resize redraws the scene; `Esc` returns. `v` cycles Astra, Pulsar,
      Bars, and Scope, and a theme from `Ctrl+Shift+P` recolors the stage.
- [ ] At 80x24, `F2` shows the workspace, and the transport and help stay
      reachable.
- [ ] In Favorites, `f` removes a row and the cursor stays in the list. The
      player's star saves the playing song even when another row is
      highlighted.

## DJ transitions

- [ ] With two or more tracks queued in crossfade mode, the next track blends
      in before the current one ends (no silence), and the crossfader knob
      slides from one deck to the other.
- [ ] `n` in the last fade length plus 12 seconds of a track runs a quick
      audible mix instead of a cut.
- [ ] `t` switches to cut: track changes are instant, and the crossfader shows
      a dotted rail and `cut`.
- [ ] `[` and `]` change the fade length, the status line confirms it, and the
      value appears in `~/.config/bester-ytm/config.toml` and in
      `uv run bester-ytm config show`.
- [ ] `uv run bester-ytm play playlist <id> --transition crossfade --fade 8`
      blends tracks from the CLI.
- [ ] Quitting mid-mix (`q` while the knob is between A and B) leaves no mpv
      process (`pgrep -a mpv`) and no `bester-ytm-mpv-*.sock` file in the temp
      directory.
- [ ] Pausing during a mix snaps to the incoming track; resuming plays at full
      volume.
