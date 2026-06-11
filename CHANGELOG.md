# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- Audio-reactive visualizers (Mythos, Bars, Wave, Pulse, Scope) driven by
  live mpv loudness, draggable pane splitters with persistent layout, and
  per-track ratings and tags.
- Transition, volume, layout, builder, and AI provider configuration in
  `~/.config/bester-ytm/config.toml`; `--transition` / `--fade` flags on
  `play playlist`; a `config show` command.
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
