# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

- Playback status messages name the track instead of showing raw video ids,
  including the remove, move, skip-unplayable, and mixing messages.
- Deleting a local playlist with `d` now requires a confirming second press,
  matching YouTube playlist deletion.
- Search, playlist loading, YouTube library listing, and album expansion run
  on worker threads, so slow YouTube Music responses no longer freeze the
  TUI.
- The visualizers lock their motion to the audible beat.

### Fixed

- The `=` (volume up) and `.` (seek +30s) keys were dead because the
  bindings used the wrong Textual key names; both work again, and `+` also
  raises the volume.
- The periodic refresh tick no longer overwrites the tags input while you
  type and no longer resets the Track Details pane to the playing track on
  every tick.
- Variant filtering (live/remix/cover detection) matches whole words only,
  so titles like "Alive" or "Deliverance" are no longer rejected as "live"
  variants.
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
