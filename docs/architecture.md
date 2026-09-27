# Architecture

`bester-ytm` is a layered, local-first application. The UI layers stay thin,
and each external system (YouTube Music, mpv) sits behind one module.

```text
CLI (cli.py, cli_play.py, cli_config.py)      TUI (tui.py + tui_* mixins)
        \                                        /
   services: playlist_builder, playlist_create, resolver, similar, stores,
             local_files, radio
                  |                          |
          ytm_client.py                 playback.py
   (YouTube Music access: a facade    (only mpv process control)
    over ytm_session / ytm_search /         |
    ytm_library / ytm_models)  transitions.py / deck.py / fader.py / mpv_ipc.py
```

Every ytmusicapi response is converted to pydantic models (`ytm_models.py`) at
the `ytm_client` boundary, so nothing above it depends on raw API shapes. The
only other module that uses ytmusicapi is `auth.py`, for login setup.

## Playback: the dual-deck transition engine

Playback runs mpv with `--no-video --ytdl-format=bestaudio`, controlled over a
JSON IPC Unix socket (`mpv_ipc.py`). Transitions run up to two mpv processes at
once, like two decks on a DJ mixer:

- **Deck** (`deck.py`): one mpv process and its IPC socket. Its lifecycle:
  spawned paused at volume 0 (prebuffering), ready, promoted to live, draining
  (fading out), stopped.
- **TransitionEngine** (`transitions.py`): driven by `tick()`, which
  `PlaybackController.status()` calls, so the TUI's 0.75 s refresh and the CLI
  wait loop drive it without extra threads. From `effective_fade + 12 s`
  before the end of a track, it spawns the idle deck for the next queued
  track. At `effective_fade` remaining, it promotes that deck: the queue
  advances, the controller's `process` and `ipc_socket` switch to the new live
  deck in one step, and the fade starts.
- **Fader** (`fader.py`): an equal-power crossfade (`gain_out = cos(t*pi/2)`,
  `gain_in = sin(t*pi/2)`) scaled by the master volume and stepped every
  100 ms on a short-lived daemon thread. Clock and sleep are injected, so tests
  run a whole ramp synchronously.
- **effective_fade** = `max(1, min(fade_seconds, duration / 3))`, so a short
  track never spends most of its runtime in a mix.

### Invariants

1. **No double advance.** For cut mode, the TUI calls `next()` when the live
   mpv process dies with tracks still queued. The engine therefore keeps
   `status().running` true through a crossfade (the live process switches
   inside `tick()`), and it never advances when the live process is dead:
   `tick()` returns before reading timing. Dead processes are the frontends'
   job; mixing is the engine's.
2. **Transactional promotion.** Queue change, deck switch, and fade start
   happen together or not at all. A failed prebuffer or IPC error cancels the
   promotion, and the track ends with a plain cut.
3. **Failed fades restore volume.** If a fader thread fails, the live deck
   returns to the master volume.
4. **Both decks are always reaped.** Retiring a deck never blocks `tick()`:
   the `DeckReaper` (`deck.py`) sends SIGTERM, unlinks the socket, polls the
   process on later ticks, and sends SIGKILL after 5 seconds. `stop()` (and
   quitting the TUI) shuts the engine down and ends with a blocking flush, so
   no mpv outlives the app.

When the next deck is already prebuffered, a manual `next` in crossfade mode
runs a quick mix (at most 2 s); otherwise it cuts. `previous` and pause finish
a mix at once before acting. Mute is mirrored to the draining deck, so a muted
mix stays silent. `PlaybackStatus.process_id` names the live mpv process; each
start and each promotion brings a new one.

## The stage

The stage (`tui_stage.py`) draws on a pixel canvas (`tui_canvas.py`) with two
pixels per cell: the upper one is the foreground of `▀`, the lower one its
background. Scenes (`tui_visuals.py`, `tui_astra.py`) write light intensities
from an `AudioFrame` (level, onset, a motion clock that runs faster when the
music is loud, and the level history). The canvas maps them to a 40-step ramp
of the theme's colors and emits Textual strips directly. `AudioSignal` samples
mpv's RMS loudness once per frame, delayed about 0.25 s to match the speakers;
the seek bar (`tui_player.py`) records each track's loudness on a fixed -42 to
-12 dB scale.

## Playlist planning pipeline

```text
seeds (favorites, pasted text) or a prose brief
  -> intelligence provider (heuristic | codex | claude | openai | anthropic)
  -> resolver (search candidates, penalize live/cover/remix, confidence)
  -> plan JSON and Markdown in ~/.local/share/bester-ytm/plans/
  -> playlist create or update through ytm_client -> check against the plan
```

Low-confidence matches are recorded in the plan for review, not accepted
silently.

## Storage and configuration

```text
~/.config/bester-ytm/config.toml   [playback], [ui], [builder], [intelligence]
~/.config/bester-ytm/browser.json  browser login (0600, never in git)
~/.config/bester-ytm/oauth*.json   OAuth client and token (0600, never in git)
~/.local/share/bester-ytm/         plans, favorites, local playlists
```

`config.py` owns all paths (XDG-aware) and enforces private file modes.
`save_transition_settings` refuses to rewrite a config file that contains
sections it does not own, so it never destroys user edits.

## Testing

The tests fake mpv at the `subprocess.Popen` and IPC seams, drive the fader
with injected clocks, and run the Textual app through `run_test()` pilots, with
no network, real mpv, or real sleeps. `tests/conftest.py` gives every test its
own XDG config and data directories and shortens Textual's idle polling so
pilot tests run fast. Checks that need audio or a login are in
[Manual Testing](manual-testing.md).
