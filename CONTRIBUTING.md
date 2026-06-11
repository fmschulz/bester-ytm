# Contributing

Thanks for your interest in improving bester-ytm. Issues and pull requests
are welcome.

## Setup

```bash
git clone https://github.com/fmschulz/bester-ytm
cd bester-ytm
uv sync
uv run bester-ytm        # run the TUI from the working tree
```

## Before you open a pull request

All of these must pass — CI enforces them:

```bash
uv run ruff check .                                   # lint
uv run mypy src                                       # type check
uv run pytest -q --cov=bester_ytm --cov-fail-under=80 # tests + coverage gate
```

## Ground rules

- **Layering**: UI layers (`cli*`, `tui*`) never call ytmusicapi or spawn
  mpv directly — they go through `ytm_client.py` and `playback.py`.
  `ytm_client.py` is the only module that talks to YouTube Music;
  `playback.py` is the only module that controls mpv.
- **Size**: modules under ~300 lines, functions under ~30, nesting ≤ 3.
  Full type hints, `from __future__ import annotations`, double quotes.
- **Errors**: raise `ConfigError` / `PlaybackError` / `YTMClientError` with
  actionable messages; never swallow exceptions silently.
- **Tests**: every change comes with tests. No network, no real mpv
  processes, no real sleeps — fake mpv at the `subprocess.Popen` / IPC
  seams and inject clocks (see `tests/test_fader.py`). The whole suite must
  stay under ~15 seconds.
- **Security**: never commit credentials or weaken the permission checks in
  `config.py`. Auth material lives only under `~/.config/bester-ytm/`.
- **Commits**: [Conventional Commits](https://www.conventionalcommits.org/)
  — `type(scope): subject` with types feat / fix / docs / refactor / test /
  chore / perf / ci.

## Releases (maintainers)

1. Bump the version in `pyproject.toml` **and**
   `src/bester_ytm/__init__.py`, and add a `## [X.Y.Z] - YYYY-MM-DD`
   section to `CHANGELOG.md`.
2. Commit, then tag: `git tag vX.Y.Z && git push origin main vX.Y.Z`.
3. The `Release` workflow verifies that the tag, both version strings, and
   the changelog section agree, re-runs all checks, and publishes the
   GitHub release with notes taken from the changelog.

See the [Development docs](https://fmschulz.github.io/bester-ytm/development/)
for the module map and the
[Architecture docs](https://fmschulz.github.io/bester-ytm/architecture/) for
the dual-deck engine invariants.
