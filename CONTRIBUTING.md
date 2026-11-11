# Contributing

Issues and pull requests are welcome.

## Setup

```bash
git clone https://github.com/fmschulz/bester-ytm
cd bester-ytm
uv sync
uv run bester-ytm        # run the TUI from the working tree
```

## Before you open a pull request

CI requires all four:

```bash
uv run ruff check .                                   # lint
uv run ruff format --check .                          # format (fix: uv run ruff format .)
uv run mypy src                                       # type check
uv run pytest -q --cov=bester_ytm --cov-fail-under=80 # tests and coverage gate
```

## Ground rules

- **Layering**: the UI layers (`cli*`, `tui*`) never call ytmusicapi or spawn
  mpv. They reach YouTube Music only through `ytm_client.py` (a facade over
  the `ytm_*` modules; the login setup in `auth.py` and `auth_capture.py` is
  the one exception) and mpv only through `playback.py` (with its engine in
  `transitions.py`, `deck.py`, `fader.py`, and `mpv_ipc.py`; status reads and
  failure checks live in `playback_monitor.py`). Config writes belong in
  `config_writer.py`, brief parsing in `playlist_brief.py`, and CLI AI calls
  in `intelligence/cli_providers.py`, with shared types in `intelligence/settings.py`.
- **TUI seams**: `tui_shell.py` holds workspace actions, `tui_favorites.py`
  holds the favorites view, `tui_focus.py` holds focus bookkeeping, and
  `tui_queue_render.py` draws the queue. `tui_selection.py` owns marked song
  IDs and the range anchor for both result rows and album trees.
- **Size**: modules under about 300 lines, functions under about 30, nesting
  at most 3 levels. Full type hints, `from __future__ import annotations`,
  double quotes.
- **Errors**: raise the layer's own error (`ConfigError`, `PlaybackError`,
  `YTMClientError`, `IntelligenceError`, `RadioError`) with a message that
  says what to do; never swallow exceptions.
- **Tests**: every change comes with tests. No network, no real mpv, and no
  real sleeps: fake mpv at the `subprocess.Popen` and IPC seams and inject
  clocks (see `tests/test_fader.py`). Keep the suite fast.
- **Security**: never commit credentials or weaken the permission checks in
  `config.py`. Login files live only under `~/.config/bester-ytm/`.
- **Commits**: [Conventional Commits](https://www.conventionalcommits.org/),
  `type(scope): subject` with the types feat, fix, docs, refactor, test,
  chore, perf, and ci.

## Releases (maintainers)

1. Set the version in `pyproject.toml` and `src/bester_ytm/__init__.py`, and
   add a `## [X.Y.Z] - YYYY-MM-DD` section to `CHANGELOG.md`.
2. Commit, then tag and push: `git tag vX.Y.Z && git push origin main vX.Y.Z`.
3. The `Release` workflow checks that the tag, both version strings, and the
   changelog section agree, re-runs all checks, and publishes the GitHub
   release with notes from the changelog.

The [Development docs](https://fmschulz.github.io/bester-ytm/development/)
have the module map, and the
[Architecture docs](https://fmschulz.github.io/bester-ytm/architecture/)
explain the dual-deck engine.
