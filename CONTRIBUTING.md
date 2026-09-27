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

CI requires all three:

```bash
uv run ruff check .                                   # lint
uv run mypy src                                       # type check
uv run pytest -q --cov=bester_ytm --cov-fail-under=80 # tests and coverage gate
```

## Ground rules

- **Layering**: the UI layers (`cli*`, `tui*`) never call ytmusicapi or spawn
  mpv. `ytm_client.py` is the only module that talks to YouTube Music, and
  `playback.py` the only one that controls mpv.
- **Size**: modules under about 300 lines, functions under about 30, nesting
  at most 3 levels. Full type hints, `from __future__ import annotations`,
  double quotes.
- **Errors**: raise `ConfigError`, `PlaybackError`, or `YTMClientError` with a
  message that says what to do; never swallow exceptions.
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
