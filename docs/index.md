# bester-ytm

A terminal YouTube Music player. Search, queue, and play through `mpv` with
DJ-style crossfades, build playlists from plain-English briefs with the AI
provider you choose, and publish them to your YouTube Music account.

![bester-ytm TUI](assets/screenshot.png)

## What it does

- **Player**: search, album browsing, an editable queue, local playlists,
  favorites, local audio files, and web radio with live song names.
- **Stage**: a black hole, a pulsar plot after Joy Division's *Unknown
  Pleasures*, a loudness skyline, or an oscilloscope, driven by the music's
  loudness and drawn in your theme's colors.
- **DJ transitions**: the next track is prebuffered on a second `mpv` deck and
  crossfaded in. The seek bar draws each track's loudness as it plays.
- **Playlist builder**: turns seed songs or a brief into a reviewed plan, then
  creates the playlist in your account.
- **AI providers**: the Codex CLI, the Claude Code CLI, any OpenAI-compatible
  endpoint (OpenRouter, Ollama, vLLM), the Anthropic API, or an offline
  heuristic.
- **Local-first**: logins, plans, playlists, and settings stay under your home
  directory. Only YouTube Music and your AI provider receive requests.

Runs on Linux and macOS. The player controls `mpv` over a Unix domain socket,
so Windows needs WSL2.

## Where to start

- [Getting Started](getting-started.md): install, first run, and login.
- [Usage](usage.md): TUI keys, search syntax, and CLI commands.
- [Playlist Builder & AI](builder.md): how plans are built and which AI
  providers work.
- [Configuration](configuration.md): `config.toml` and data locations.
- [Architecture](architecture.md): the dual-deck engine and the stage.
