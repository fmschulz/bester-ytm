# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2026-07-03

### Added

- AI-assisted radio station adding: type `add radio station <name>` into the
  playlist builder and the configured AI provider looks up the station's
  direct stream URL; bester-ytm verifies the URL serves audio and writes it
  to `[radio.stations]` in config.toml, so the station appears under
  `radio:`. The heuristic provider explains how to add a station manually
  instead.

### Fixed

- Config rewrites quote TOML keys that need it, so stations named with
  spaces ("Groove Salad") no longer corrupt config.toml.

## [1.2.0] - 2026-07-03

### Added

- Web radio in the TUI: `radio:` in the search box lists stations — ByteFM
  and KALX built in, more via `[radio.stations]` in config.toml — and they
  play like songs, in the queue. While a station plays, the Now Playing
  label shows the live track from the station's metadata, refreshed every
  ~20 seconds.
- `f` during radio favs the song the station is playing: the track is
  resolved on YouTube Music, liked there, and saved to local favorites; the
  status line names the match.
- Faving any song now also likes it on YouTube Music when logged in (and
  unfaving removes the like); `liked:` joins `favs:`/`favorites:` as a
  search prefix for the favorites list.

## [1.1.0] - 2026-07-03

### Added

- Local audio file playback: type `local:` plus a path — or simply paste a
  path starting with `/`, `~`, or `./` — into the search box and the audio
  files there (folders are scanned recursively) appear in the left pane as
  regular song rows. `Enter` plays, `a` queues, `f` favs, local playlists
  can hold them, and DJ crossfades blend local and YouTube tracks
  interchangeably. `./scripts/download-example-songs.sh` fetches three
  public-domain example songs into `examples/music/` to try it out.
- `g` takes a digit count for similar tracks: `g` alone queues the default
  number of AI-suggested similar songs, `g11` queues eleven (up to 30), and
  Escape cancels the pending count.
- Favorites as a first-class feature: `f` favs or unfavs the highlighted
  song (falling back to the playing track), faved songs show a trailing `*`
  in the queue, search results, and the Now Playing label, and a `favs:`
  search prefix lists them (`favs:text` filters). Favorites persist as full
  track records in `favorites.json`; entries from the legacy `favorites.md`
  are migrated on first use.
- Album search as an expandable tree: `album:` queries render album titles
  in the left pane; Enter expands an album (its songs load in the background
  on first expand), `a` adds an album, song, or the marked rows to the queue,
  and `A` (shift+a) plays the album now — from the top or from the
  highlighted song on.
- Range selection in search results and the album tree: `Shift+Space` and
  shift+click mark every song from the first marked one through the
  highlighted row.
- A dedicated Playlist / Queue section in the right pane: a playlist name
  field with New / Save / Add / Remove buttons plus the Shuffle / Mix /
  Clear and Fade- / Fade+ controls. New starts a fresh playlist while the
  playing track keeps playing, and freshly built or saved playlists appear
  in the left library immediately.
- A keyboard help overlay: `?` opens a modal listing every key binding,
  grouped by purpose; Escape, `q`, or `?` closes it.
- Login state at startup: the status line reports
  `Logged in to YouTube Music.` or a hint to run `bester-ytm auth login`;
  the volume buttons moved into their own row under the transport controls.

### Changed

- The right pane got simpler: the Track Details section is gone, and the
  Mix / Fade- / Fade+ transition controls moved from the Playlist / Queue
  section into Now Playing next to the volume row, since they act on live
  playback rather than the queue.
- Playback status messages name the track instead of showing raw video ids,
  including the remove, move, skip-unplayable, and mixing messages.
- Deleting a local playlist with `d` now requires a confirming second press,
  matching YouTube playlist deletion.
- Search, playlist loading, YouTube library listing, and album expansion run
  on worker threads, so slow YouTube Music responses no longer freeze the
  TUI.
- The visualizers lock their motion to the audible beat.
- Internal: `tui.py` and `ytm_client.py` were split into focused modules
  (`tui_*` action mixins; session, search, library, and models behind the
  `ytm_client` facade), and the test suite runs markedly faster.

### Removed

- Track ratings and tags: the Track Details section, the `r` key, and the
  Rate- / Rate+ / Save Tags buttons are gone in favor of the simpler
  favorites toggle. An existing `track-metadata.json` is left untouched on
  disk but is no longer read.

### Fixed

- Browser login accepts headers pasted from Firefox, whose "Copy Request
  Headers" separates lines with NEL characters that broke the old
  line-by-line reader (and left Ctrl-D doing nothing). Input is now read to
  EOF and normalized, and the guide says to click a song so a `browse`
  request appears, then press Enter and Ctrl-D after pasting.
- `f` favs the highlighted search result while the results pane has focus
  even when a playlist is loaded; the queue's remembered selection no longer
  hijacks the toggle.
- The `=` (volume up) and `.` (seek +30s) keys were dead because the
  bindings used the wrong Textual key names; both work again, and `+` also
  raises the volume.
- The periodic refresh tick redraws the Now Playing label only when the
  track actually changes.
- Variant filtering (live/remix/cover detection) matches whole words only,
  so titles like "Alive" or "Deliverance" are no longer rejected as "live"
  variants.
- Deferred loads (search, playlist listing, album results) that finish while
  you are typing in the search input or the builder text area no longer steal
  the focus mid-keystroke.
- `a` / `A` / `x` on a collapsed album fetch its tracks on a worker thread
  and apply the action when they land, instead of freezing the TUI during
  the fetch.
- When pause falls back to process signals (mpv IPC unavailable), resume
  works again, and status polling, seeking, volume, and mute no longer stall
  against the signal-stopped mpv.
- Corrupt store files (favorites, plans, local playlists) now produce
  an actionable "move the file aside and retry" error that the TUI shows in
  the status bar instead of crashing; corrupt local playlists are skipped
  with a warning when listing.
- Retiring a crossfade deck no longer blocks playback: decks terminate in
  the background and are force-killed after a 5-second grace period.
- `bester-ytm search --help` now shows a description of the command.

## [1.0.0] - 2026-06-11

First public release.

### Added

- DJ-style transitions between tracks: a dual-deck mpv engine prebuffers the
  next queued track on a silent second deck and blends it in with an
  equal-power crossfade. TUI controls: `t` toggles cut/crossfade, `[` / `]`
  adjust the fade length, and the DECK line becomes a live MIX meter while
  two tracks blend.
- Browser-header login as the default (`auth login`): paste request headers
  from a logged-in music.youtube.com tab — no Google Cloud setup needed.
  The Google OAuth device flow remains available via `auth login --oauth`.
- Playlist building from prose briefs: describe the playlist in plain words
  and the configured AI provider (Codex CLI, any OpenAI-compatible endpoint,
  Anthropic API, or an offline heuristic) proposes the tracks and names the
  playlist — an explicit "save it as X" in the brief is honored verbatim.
- Finished builds become named local playlists and load into the queue
  without interrupting the playing track.
- Track removal from both local and YouTube playlists, local playlist
  deletion, and YouTube playlist deletion with a confirming second press.
- Audio-reactive visualizers driven by live mpv loudness, rendered as glowing
  panels in the bottom of every pane: six effects (Mythos, Oracle, Bars, Wave,
  Pulse, Scope) with a per-cell ember gradient and an additive bloom, where
  Mythos is a luminous mind-core orbited by a constellation that flares with the
  music and Oracle is a mind's-eye of expanding thought-rings. Switch effects via
  the right-pane dropdown, the `v` key, or the command palette.
- A branded "ember" theme applied by default and selectable from the command
  palette (the circle in the header), with the chosen theme remembered across
  runs.
- Draggable pane splitters with persistent layout, and per-track ratings and
  tags.
- Transition, volume, layout, theme, builder, and AI provider configuration in
  `~/.config/bester-ytm/config.toml` (including `ui.visual_fps`, which lowers the
  animation rate or turns the panels off with `0`); `--transition` / `--fade`
  flags on `play playlist`; a `config show` command.
- Documentation site (MkDocs Material) deployed to GitHub Pages, MIT
  license, changelog, architecture documentation, and continuous
  integration (lint, type check, 80% coverage gate, release consistency).

## [0.1.0] - 2026-06-08

### Added

- Initial release: Typer CLI and Textual TUI, YouTube Music search
  (including structured queries), mpv audio playback with JSON IPC
  (pause/seek/volume/mute), queue with history, shuffle, and auto-advance.
- Google OAuth device-flow login (`auth login` / `auth status` / `auth logout`)
  with private credential storage under `~/.config/bester-ytm/`.
- Playlist planning from favorites or free-form text, candidate resolution
  with variant filtering, plan export, and authenticated YouTube playlist
  create/update with verification.
- Local favorites, local playlists, per-track ratings and tags, and a
  global CLI installer (`install.sh`).
