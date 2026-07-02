# Architecture

`bester-ytm` is a layered, local-first application. UI layers stay thin and
testable; all external systems (YouTube Music, mpv) are isolated behind one
module each.

```text
CLI (cli.py, cli_play.py, cli_config.py)      TUI (tui.py + mixins)
        \                                        /
         services: playlist_builder, playlist_create, resolver, stores
                  |                          |
          ytm_client.py                 playback.py
        (only YouTube Music access)   (only mpv process control)
                                            |
                            transitions.py / deck.py / fader.py / mpv_ipc.py
```

Every ytmusicapi response is normalized into local dataclasses at the
`ytm_client.py` boundary; nothing above it depends on raw API shapes.

## Playback: the dual-deck transition engine

Playback uses mpv with `--no-video --ytdl-format=bestaudio`, controlled over
a JSON IPC unix socket (`mpv_ipc.py`). DJ-style transitions come from running
up to two mpv processes at once, like a two-deck DJ setup:

- **Deck** (`deck.py`): one mpv process plus its own IPC socket. The deck
  lifecycle is: spawned paused at volume 0 (prebuffering) -> ready ->
  promoted to live -> draining (fading out) -> stopped.
- **TransitionEngine** (`transitions.py`): tick-driven; `PlaybackController.
  status()` calls `tick()`, so the TUI's 0.75s refresh loop and the CLI wait
  loop both drive it without threads of their own. Within the prebuffer
  window (`effective_fade + 12s` before track end) it spawns the idle deck
  for the next queued track. At `effective_fade` remaining it promotes the
  prebuffered deck: the queue advances, controller `process`/`ipc_socket`
  swap atomically to the new live deck, and the fade starts.
- **Fader** (`fader.py`): equal-power crossfade (`gain_out = cos(t*pi/2)`,
  `gain_in = sin(t*pi/2)`) scaled by the controller's master volume,
  stepped every 100ms on a short-lived daemon thread. The clock and sleep
  functions are injected so tests run the whole ramp synchronously.
- **effective_fade** = `max(1, min(fade_seconds, duration / 3))`, so short
  tracks never spend most of their runtime mid-mix.

### Invariants

1. **No double-advance.** The TUI keeps a fallback auto-advance for cut mode:
   when the live mpv process dies with tracks still queued, it calls
   `next()`. The engine therefore guarantees `status().running` never dips
   during a crossfade (the live process swaps atomically inside `tick()`),
   and the engine itself never advances when the live process is dead -
   `tick()` returns before reading timing. Dead-process handling always
   belongs to the frontends, mixing always belongs to the engine.
2. **Transactional promotion.** Queue mutation, deck swap, and fade start
   happen together or not at all; a failed prebuffer or IPC error aborts the
   promotion and the track ends with a plain cut.
3. **Failed fades restore volume.** If a fader thread errors, the live deck's
   volume is restored to the master volume so playback is never left quiet.
4. **Both decks are always reaped.** `stop()` (and TUI quit) shuts down the
   engine, terminating live and prebuffer decks and unlinking their sockets.

Manual `next` during crossfade mode performs a quick-mix (ramp capped at 2s);
`previous` and pause snap the mix immediately before acting. Mute is mirrored
to the draining deck so a muted mix stays silent.

## Playlist planning pipeline

```text
seeds (favorites, pasted text) -> intelligence provider (heuristic | codex)
  -> resolver (search candidates, penalize live/cover/remix, confidence)
  -> plan JSON/Markdown in ~/.local/share/bester-ytm/plans/
  -> playlist create/update via ytm_client -> verification against the plan
```

Low-confidence resolutions are recorded in the plan for review rather than
silently accepted.

## Storage and configuration

```text
~/.config/bester-ytm/config.toml   [playback] transition + fade_seconds
~/.config/bester-ytm/oauth*.json   OAuth client and token (0600, never in git)
~/.local/share/bester-ytm/         plans, favorites, local playlists
```

`config.py` owns all paths (XDG-aware) and enforces private file modes.
`save_transition_settings` refuses to rewrite a config file containing
sections it does not own, so user edits are never destroyed.

## Testing strategy

The suite (200+ tests, a few seconds, no network/mpv/sleeps) fakes mpv at the
`subprocess.Popen` and IPC seams, drives the fader with injected clocks, and
exercises the Textual app through `run_test()` pilots. Manual, audio-producing
checks live in [Manual Testing](manual-testing.md).
