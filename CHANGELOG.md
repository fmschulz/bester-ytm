# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- DJ-style transitions between tracks: a dual-deck mpv engine prebuffers the
  next queued track on a silent second deck and blends it in with an
  equal-power crossfade.
- TUI transition controls: `t` toggles cut/crossfade, `[` / `]` adjust the
  fade length (1-15s), and the visualizer shows a permanent DECK line that
  becomes a live MIX meter while two tracks blend.
- Transition configuration persisted in `~/.config/bester-ytm/config.toml`
  (`[playback]` section), `--transition` / `--fade` flags on
  `play playlist`, and a `config show` command.
- First-run login guidance: `auth login` walks through the Google Cloud
  credential steps, and the TUI hints at login when no token is present.
- MIT license, changelog, architecture documentation, project agent guide,
  and continuous integration (lint, type check, coverage gate).

### Changed

- The TUI module was split into focused modules (styles, layout, effects,
  playback actions, library actions); playback was split into deck, fader,
  IPC transport, and transition-engine modules.

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
