# Development

## Setup and checks

```bash
uv sync                          # install with dev dependencies
uv run bester-ytm                # run the TUI from the working tree
uv run pytest -q                 # tests (fast: no network, no mpv, no sleeps)
uv run pytest -q --cov=bester_ytm --cov-report=term   # coverage (CI gate: 80%)
uv run ruff check .              # lint
uv run mypy src                  # type check
```

CI runs the same lint, type check, and coverage gate on every push and pull
request, on Python 3.11 and 3.13. Contribution rules live in
[CONTRIBUTING.md](https://github.com/fmschulz/bester-ytm/blob/main/CONTRIBUTING.md).

## Releasing

Bump the version in `pyproject.toml` and `src/bester_ytm/__init__.py`, add a
`## [X.Y.Z]` section to `CHANGELOG.md`, commit, and push a `vX.Y.Z` tag. The
`Release` workflow fails unless tag, both version strings, and the changelog
section agree; it then re-runs all checks and publishes the GitHub release
with notes extracted from the changelog.

## Layout and conventions

```text
src/bester_ytm/
├── cli.py, cli_play.py, cli_config.py   Typer commands (thin; no API logic)
├── tui.py + tui_*.py                    Textual app shell and action mixins
├── playback.py                          PlaybackController: queue, history, mpv
├── transitions.py, deck.py, fader.py    dual-deck crossfade engine
├── mpv_ipc.py                           mpv JSON IPC transport
├── ytm_client.py                        the ONLY module that talks to YouTube Music
├── auth.py, config.py, config_options.py   logins, paths, config.toml
├── playlist_plan.py, playlist_builder.py, playlist_create.py, resolver.py
├── stores.py, search_query.py, similar.py
└── intelligence/                        AI providers (heuristic, codex, openai, anthropic)
```

- UI layers (`cli*`, `tui*`) never call ytmusicapi or spawn mpv directly;
  they go through `ytm_client.py` and `playback.py`.
- Modules stay under ~300 lines, functions under ~30, full type hints.
- Errors are raised as `ConfigError` / `PlaybackError` / `YTMClientError`
  with actionable messages.
- Tests fake mpv at the `subprocess.Popen` / IPC seams and inject clocks;
  the whole suite must stay under ~15 seconds.

See [Architecture](architecture.md) for the dual-deck engine design and its
invariants, and [Manual Testing](manual-testing.md) for the credentialed,
audio-producing checks that unit tests intentionally skip.

## Documentation

This site is built with MkDocs Material:

```bash
uv sync --group docs
uv run mkdocs serve    # live preview at http://127.0.0.1:8000
```

It deploys to GitHub Pages automatically on every push to `main`.
