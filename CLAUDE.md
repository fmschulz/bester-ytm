# CLAUDE.md

## Project

**bester-ytm**: Local terminal/TUI YouTube Music companion with playlist
planning, authenticated playlist creation, and mpv playback featuring
DJ-style dual-deck crossfade transitions.

**Stack**: Python 3.11+, uv, Typer (CLI), Textual (TUI), ytmusicapi,
pydantic, mpv + yt-dlp (external binaries), pytest.

## Commands

```bash
uv sync                          # install (dev)
uv run bester-ytm                # launch the TUI
uv run pytest -q                 # test suite (fast: no network, no mpv)
uv run pytest -q --cov=bester_ytm --cov-report=term   # coverage (gate: 80%)
uv run ruff check .              # lint
uv run mypy src                  # type check
./install.sh                     # install/refresh the global CLI command
```

## Structure

```text
src/bester_ytm/
├── cli.py, cli_play.py, cli_config.py   # Typer commands (thin; no API logic)
├── tui.py                               # Textual app shell (bindings, compose)
├── tui_*.py                             # TUI action mixins (playback, library,
│                                        #   album, metadata, playlists, queue,
│                                        #   selection, builder, events, options)
│                                        # plus rendering/layout/CSS (tui_effects,
│                                        #   tui_layout, tui_styles, tui_visuals,
│                                        #   tui_splitter, tui_theme, tui_help)
├── playback.py                          # PlaybackController: queue, history, mpv
├── transitions.py, deck.py, fader.py    # dual-deck crossfade engine
├── mpv_ipc.py                           # mpv JSON IPC transport
├── playback_status.py, transition_settings.py    # shared dataclasses
├── ytm_client.py                        # YouTube Music facade over ytm_*.py
├── ytm_session.py, ytm_search.py, ytm_library.py, ytm_models.py
├── auth.py, config.py, config_options.py  # OAuth flow, paths, config.toml
├── playlist_plan.py, playlist_builder.py, playlist_create.py, resolver.py
├── stores.py, search_query.py, similar.py
└── intelligence/                        # playlist plan providers (heuristic, codex)
```

See `docs/architecture.md` for the dual-deck engine design and invariants.
User docs are a MkDocs site (`mkdocs.yml`, `docs/`), deployed to GitHub Pages
by `.github/workflows/docs.yml`.

## Conventions

- Modules under ~300 lines, functions under ~30 lines, nesting <= 3 levels.
- `from __future__ import annotations`, full type hints, dataclasses,
  double quotes, self-documenting names.
- UI layers (cli*, tui*) never call ytmusicapi or spawn mpv directly; they go
  through `ytm_client.py` and `playback.py`.
- Errors: raise `ConfigError` / `PlaybackError` / `YTMClientError` with
  actionable messages; never swallow exceptions silently.
- Tests: no network, no real mpv processes, no real sleeps. Fake mpv at the
  `subprocess.Popen` / `_send_ipc` seams; time via injected clocks
  (see `tests/test_fader.py`). Whole suite must stay under ~15 seconds.
- No emojis in code, output, or docs.

## Security

- Secrets live only under `~/.config/bester-ytm/` (`oauth-client.json`,
  `oauth.json`, `browser.json`, mode 0600; directory 0700). Never read them into output,
  never commit them, never weaken the permission checks in `config.py`.
- Never print token or cookie contents; `auth status` reports state only.

## Git

- Never commit or push without explicit user approval.
- Conventional commits: `type(scope): subject`.
