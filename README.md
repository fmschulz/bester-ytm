# bester-ytm

[![CI](https://github.com/fmschulz/bester-ytm/actions/workflows/ci.yml/badge.svg)](https://github.com/fmschulz/bester-ytm/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/fmschulz/bester-ytm?color=orange)](https://github.com/fmschulz/bester-ytm/releases)
[![Docs](https://img.shields.io/badge/docs-fmschulz.github.io-blue.svg)](https://fmschulz.github.io/bester-ytm/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

A local terminal YouTube Music companion: search, queue, and play music
through `mpv` with DJ-style dual-deck crossfades, build playlists from plain
English briefs with the AI provider of your choice, and publish them to your
YouTube Music account.

![bester-ytm TUI](docs/assets/screenshot.png)

- **Terminal player** — a Textual TUI with search, album browsing, an
  editable queue, local playlists, favorites, and audio-reactive visuals.
- **DJ transitions** — the next track is prebuffered on a second silent
  `mpv` deck and blended in with an equal-power crossfade.
- **Playlist builder** — turn seed songs or a prose brief ("15 songs in the
  style of Blind Guardian, save as powermetal-15") into a reviewed plan,
  then create the real playlist in your account.
- **AI, your way** — briefs and similar-track suggestions run through the
  Codex CLI, any OpenAI-compatible endpoint (OpenRouter, Ollama, vLLM), the
  Anthropic API, or a fully offline heuristic.
- **Local-first** — credentials, plans, playlists, and settings live under
  your home directory; nothing leaves your machine except requests to
  YouTube Music and the AI provider you configure.

Runs on **Linux and macOS** (mpv is controlled over a Unix socket; on
Windows use WSL2).

## Quick start

Install the dependencies (`uv`, `mpv`, `yt-dlp`):

```bash
brew install uv mpv yt-dlp                  # macOS
sudo apt-get install -y mpv yt-dlp          # Ubuntu/Debian (uv: astral.sh/uv)
sudo pacman -S --needed uv mpv yt-dlp       # Arch Linux
```

Then, from a clone of this repository:

```bash
./install.sh    # registers the bester-ytm command (uv tool install)
bester-ytm      # launch the TUI
```

Search and playback work immediately — no account needed:

```bash
bester-ytm search "Beach House Myth"
bester-ytm play search "Beach House Myth" --seconds 20
```

## Logging in (for account features)

Library playlists and playlist create/edit/delete need a login. The default
takes about a minute and **no Google Cloud setup**: run
`bester-ytm auth login` and paste request headers copied from a logged-in
[music.youtube.com](https://music.youtube.com) tab — the command walks you
through it. Prefer a self-refreshing token instead? Create free Google OAuth
credentials once and use `bester-ytm auth login --oauth`.

Both flows, step by step:
[Getting Started](https://fmschulz.github.io/bester-ytm/getting-started/).

## Documentation

Full documentation lives at
**[fmschulz.github.io/bester-ytm](https://fmschulz.github.io/bester-ytm/)**:

- [Getting Started](https://fmschulz.github.io/bester-ytm/getting-started/) — install and login
- [Usage](https://fmschulz.github.io/bester-ytm/usage/) — TUI keys, search syntax, CLI commands
- [Playlist Builder & AI](https://fmschulz.github.io/bester-ytm/builder/) — plans, briefs, AI providers
- [Configuration](https://fmschulz.github.io/bester-ytm/configuration/) — `config.toml`, data locations
- [Architecture](https://fmschulz.github.io/bester-ytm/architecture/) — the dual-deck engine

## Development

```bash
uv sync
uv run pytest -q     # fast: no network, no mpv
uv run ruff check .
uv run mypy src
```

CI gates lint, types, and 80% test coverage on Python 3.11 and 3.13. See
[Development](https://fmschulz.github.io/bester-ytm/development/) for layout
and conventions, and [CONTRIBUTING.md](CONTRIBUTING.md) for how to propose
changes.

## License

MIT — see [LICENSE](LICENSE).
