# Manual Test Checklist

Use this checklist for the credentialed and audio-producing checks that unit
tests intentionally do not perform.

## Auth

- [ ] First run of `uv run bester-ytm auth login` prints the browser-header
      guide, accepts pasted headers, and writes
      `~/.config/bester-ytm/browser.json` with mode `0600`.
- [ ] `uv run bester-ytm auth login --oauth` prints the Google Cloud setup
      steps on first run, prompts for client ID/secret, and starts the
      device flow; `oauth-client.json` exists with mode `0600`.
- [ ] `uv run bester-ytm auth status` reports an authenticated YouTube Music library request without printing tokens.
- [ ] Launching the TUI without a login shows the login hint in the status
      line; with one it shows `Logged in to YouTube Music.`.

## Playlists

- [ ] `uv run bester-ytm playlist build --from examples/seeds.txt --name "Test Mix" --count 30` writes a JSON and Markdown plan.
- [ ] The generated plan has 30 planned tracks, resolved `videoId` selections, non-empty reasons, and no obvious cover/live/remix selections unless requested.
- [ ] `uv run bester-ytm playlist create <plan-id>` creates or updates the YouTube Music playlist and verifies expected track membership.

## Playback

- [ ] `uv run bester-ytm play search "Beach House Myth" --seconds 20` starts `mpv`, plays audio, and exits cleanly.
- [ ] `uv run bester-ytm` opens the player TUI; search, queue, play/pause, skip, favorite toggle (f, trailing * marker, favs: listing), auth status, and playlist builder views respond to the documented keys.
- [ ] After `./scripts/download-example-songs.sh`, searching
      `local:examples/music` lists the three example songs, `Enter` plays one
      audibly, and crossfade transitions work between local and YouTube
      tracks.
- [ ] Searching `radio:` lists ByteFM and KALX; `Enter` plays the station
      audibly, the Now Playing label shows the live track within ~20 seconds,
      and `f` while it plays reports a YouTube Music match and likes it (with
      a login configured).

## DJ transitions

- [ ] With two or more tracks queued and crossfade active, the second track
      audibly blends in before the first ends (no silence gap), and the DECK
      line becomes a `MIX A [######------] B` meter during the blend.
- [ ] Pressing `n` during crossfade mode performs a quick audible mix instead
      of a hard cut.
- [ ] Pressing `t` switches to cut; track changes become instant hard
      switches and the DECK line shows `cut`.
- [ ] `[` and `]` change the fade length, the status line confirms it, and
      the new value appears in `~/.config/bester-ytm/config.toml` and in
      `uv run bester-ytm config show`.
- [ ] `uv run bester-ytm play playlist <id> --transition crossfade --fade 8`
      blends between tracks from the CLI.
- [ ] Quit the TUI mid-mix (`q` while the MIX meter is visible), then run
      `pgrep -a mpv`: no orphaned mpv processes remain and no
      `bester-ytm-mpv-*.sock` files are left in the temp directory.
- [ ] Pause during a mix snaps cleanly to the incoming track; resume plays at
      full volume.
