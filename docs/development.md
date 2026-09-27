# Development

## Setup and checks

```bash
uv sync                          # install with dev dependencies
uv run bester-ytm                # run the TUI from the working tree
uv run pytest -q                 # tests: no network, no mpv, no sleeps
uv run pytest -q --cov=bester_ytm --cov-report=term   # coverage report
uv run ruff check .              # lint
uv run mypy src                  # type check
```

CI runs lint, the type check, and the tests with an 80% coverage gate
(`--cov-fail-under=80`) on every push and pull request, on Python 3.11 and
3.13. Contribution rules are in
[CONTRIBUTING.md](https://github.com/fmschulz/bester-ytm/blob/main/CONTRIBUTING.md).

## Releasing

Set the new version in `pyproject.toml` and `src/bester_ytm/__init__.py`, add a
`## [X.Y.Z] - YYYY-MM-DD` section to `CHANGELOG.md`, commit, and push a
`vX.Y.Z` tag. The `Release` workflow stops unless the tag, both version
strings, and the changelog section agree; then it re-runs all checks and
publishes a GitHub release with notes from the changelog.

## Layout and conventions

```text
src/bester_ytm/
├── cli.py, cli_play.py, cli_config.py   Typer commands (thin; no API logic)
├── tui.py + tui_*.py                    Textual app shell and action mixins
├── tui_canvas.py, tui_stage.py,         the stage: pixel canvas, widget,
│   tui_visuals.py, tui_astra.py         audio signal, and scenes
├── tui_player.py, tui_rows.py           player deck and list rows
├── playback.py                          PlaybackController: queue, history, mpv
├── transitions.py, deck.py, fader.py    dual-deck crossfade engine
├── playback_status.py, transition_settings.py   shared dataclasses
├── mpv_ipc.py                           mpv JSON IPC transport
├── ytm_client.py + ytm_*.py             YouTube Music access: facade over
│                                        session, search, library, models
├── auth.py, config.py, config_options.py   logins, paths, config.toml
├── playlist_plan.py, playlist_builder.py, playlist_create.py, resolver.py
├── stores.py, search_query.py, similar.py
└── intelligence/                        AI providers (heuristic, codex,
                                         claude, openai, anthropic)
```

- The UI layers (`cli*`, `tui*`) never call ytmusicapi or spawn mpv; they use
  `ytm_client.py` and `playback.py`.
- Modules stay under about 300 lines and functions under about 30, with full
  type hints.
- Errors are `ConfigError`, `PlaybackError`, or `YTMClientError` with messages
  that say what to do.
- Tests fake mpv at the `subprocess.Popen` and IPC seams and inject clocks.

[Architecture](architecture.md) explains the dual-deck engine and the stage;
[Manual Testing](manual-testing.md) lists the checks that need audio or a
login.

## Documentation

The site is built with MkDocs Material:

```bash
uv sync --group docs
uv run mkdocs serve    # preview at http://127.0.0.1:8000
```

Every push to `main` deploys it to GitHub Pages.
