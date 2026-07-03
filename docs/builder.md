# Playlist Builder & AI

## The pipeline

The playlist builder turns a handful of songs you like ("seeds") or a prose
brief into a full playlist plan, then creates that playlist in your YouTube
Music account:

1. **Seeds in** — `Artist - Title` lines from a file, pasted text, or your
   imported favorites. Numbered lists and `Artist | Title` separators work
   too. A prose brief skips seeds entirely.
2. **Plan** — the builder keeps your seeds and fills the remaining slots with
   related tracks, recording a reason for every pick.
3. **Resolve** — each planned track is matched to a concrete YouTube Music
   video ID; obvious variants (live, cover, remix, karaoke, demo,
   instrumental, remaster, sped-up/slowed, tribute, lyric video) are skipped
   unless you pass `--allow-variants` (CLI builds only; TUI builds always
   filter variants). "27/30 resolved" means 3 tracks found no confident
   match — open the plan file to review them.
4. **Plan saved** — every plan is written as JSON and Markdown under
   `~/.local/share/bester-ytm/plans/` so you can inspect or edit it before
   anything touches your account.
5. **Create** — `bester-ytm playlist create <plan-id>` builds the real
   playlist (private by default), then re-fetches it to verify every track
   landed. Requires login.

## Building in the TUI

Use the `Playlist Builder` box in the right pane. Type `Artist - Title` seed
lines, or simply describe what you want — for a prose brief, pressing Enter
builds immediately:

```text
create a playlist with 15 songs in style similar to blind guardian
and include at least 3 blind guardian songs, save it as powermetal-15
```

Briefs that start with `add`, `queue`, or `append` grow the current queue
instead of building a new playlist: `Add 5 songs similar to Four Tet`
appends five matching tracks after what is already queued, exactly like the
`g` key (an explicit count is honored; the default is 5). The queue's mood
is passed along as context, so "add 5 more like this" also works.

The builder box understands one non-playlist request too: `add radio
station <name>` asks the AI provider for the station's direct stream URL,
verifies it plays, and saves it to `[radio.stations]` in `config.toml`
(see [Usage → Web radio](usage.md#web-radio)).

Builds run in the background while music keeps playing. When the build
finishes, it becomes a new named local playlist and loads into the queue
(after the current song, if one is playing). An explicit count in the brief
("15 songs") is honored; the default is 30. The playlist name comes from the
brief: an explicit "save it as X" seeds the name (a few words, trimmed at
filler words), and the AI providers may refine it into a short fitting title.

Pressing `i` (or Build) with an empty builder box builds from your favorites
file instead: set `[builder] favorites_file` in `config.toml` to a seeds
markdown file (a sibling `../tuiradio/favs.md` is picked up automatically
when present).

From there the queue is your editable working playlist: `d` removes, `j`/`k`
move, `g` adds AI suggestions, and `w` saves back to the named local
playlist. `bester-ytm playlist create <plan-id>` publishes the saved plan's
resolved tracks to your account — queue edits live in the local playlist,
not the plan, so publish reflects the plan as built.

## AI providers

Two features use an AI provider: `g` (add similar tracks based on what is
playing) and brief-only playlist building. Configure it in
`~/.config/bester-ytm/config.toml`:

```toml
[intelligence]
provider = "auto"   # auto | heuristic | codex | openai | anthropic
```

- `auto` (default): uses the `codex` CLI when installed, then the `claude`
  CLI, otherwise the offline heuristic (YouTube Music related tracks).
- `codex`: shells out to [Codex CLI](https://developers.openai.com/codex)
  (`codex exec`, read-only sandbox). Uses your existing codex login; set
  `model = "..."` to override the model.
- `claude`: shells out to [Claude Code](https://claude.com/claude-code)
  (`claude -p`). Uses your existing claude login — no API key; set
  `model = "..."` (e.g. `sonnet`) to override the model.
- `openai`: any OpenAI-compatible chat-completions endpoint — OpenRouter,
  self-hosted vLLM, Ollama, llama.cpp, or OpenAI itself:

  ```toml
  [intelligence]
  provider = "openai"
  model = "deepseek/deepseek-chat"             # required
  base_url = "https://openrouter.ai/api/v1"    # default; point at your host
  api_key_env = "OPENROUTER_API_KEY"           # env var holding the key
  ```

  For a self-hosted model: `base_url = "http://localhost:11434/v1"` (Ollama)
  with any non-empty key in the named env var.
- `anthropic`: the Anthropic API via the official SDK. Set
  `ANTHROPIC_API_KEY` in your environment; `model` defaults to a recent
  Claude model.

API keys are read from environment variables only and never written to disk
or logged. Suggestions are always resolved against YouTube Music before
anything is queued, so the AI can only pick songs that actually exist.
