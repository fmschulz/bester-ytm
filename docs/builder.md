# Playlist Builder & AI

## The pipeline

The builder turns songs you like ("seeds") or a prose brief into a playlist
plan, then creates the playlist in your YouTube Music account.

1. **Seeds**: `Artist - Title` lines from a file, pasted text, or your
   imported favorites. Numbered lists and `Artist | Title` also work. A prose
   brief replaces seeds.
2. **Plan**: the builder keeps your seeds and fills the remaining slots with
   related tracks, recording a reason for each.
3. **Resolve**: each planned track is matched to a YouTube Music video ID.
   Obvious variants (live, cover, remix, karaoke, demo, instrumental,
   remaster, sped-up or slowed, tribute, lyric video) are skipped unless the
   CLI gets `--allow-variants`; TUI builds always skip them. "27/30 resolved"
   means 3 tracks had no confident match; the plan file lists them.
4. **Save**: each plan is written as JSON and Markdown to
   `~/.local/share/bester-ytm/plans/`, so you can review or edit it before
   anything touches your account.
5. **Create**: `bester-ytm playlist create <plan-id>` creates the playlist
   (private by default) and re-fetches it to confirm every track landed. This
   step needs a login.

## Building in the TUI

Use the **Playlist builder** box in the workspace. Type `Artist - Title` lines,
or describe what you want; for a prose brief, `Enter` starts the build:

```text
create a playlist with 15 songs in style similar to blind guardian
and include at least 3 blind guardian songs, save it as powermetal-15
```

A brief that starts with `add`, `queue`, or `append` extends the current queue
instead: `Add 5 songs similar to Four Tet` appends five matching tracks, like
the `g` key. An explicit count is used; the default is 5. The queue's mood is
passed along, so "add 5 more like this" works.

`add radio station <name>` asks the AI provider for the station's stream URL,
checks that it plays, and saves it to `[radio.stations]` in `config.toml` (see
[Usage: Web radio](usage.md#web-radio)).

Builds run in the background while music plays. The result becomes a named
local playlist and loads into the queue, after the current song if one is
playing. A count in the brief ("15 songs") is used; the default is 30. The name
comes from the brief: "save it as X" sets it, and the AI providers may refine
it into a short title.

`i` or **Build playlist** with an empty box builds from your favorites file:
set `[builder] favorites_file` in `config.toml` to a seeds file. A sibling
`../tuiradio/favs.md` is used when present.

The queue is then your editable working playlist: `d` removes, `j`/`k` move,
`g` adds suggestions, and `w` saves back to the local playlist.
`bester-ytm playlist create <plan-id>` publishes the plan as it was built;
queue edits stay in the local playlist.

## AI providers

`g` (similar tracks) and brief-only builds use an AI provider, set in
`~/.config/bester-ytm/config.toml`:

```toml
[intelligence]
provider = "auto"   # auto | heuristic | codex | claude | openai | anthropic
```

- `auto` (default): the `codex` CLI if installed, else the `claude` CLI, else
  the offline heuristic (YouTube Music related tracks).
- `codex`: runs [Codex CLI](https://developers.openai.com/codex)
  (`codex exec`, read-only sandbox) with your existing codex login. Set
  `model = "..."` to choose the model.
- `claude`: runs [Claude Code](https://claude.com/claude-code) (`claude -p`)
  with your existing claude login; no API key needed. Set `model = "..."`
  (for example `sonnet`) to choose the model.
- `openai`: any OpenAI-compatible chat-completions endpoint, such as
  OpenRouter, vLLM, Ollama, llama.cpp, or OpenAI:

  ```toml
  [intelligence]
  provider = "openai"
  model = "deepseek/deepseek-chat"             # required
  base_url = "https://openrouter.ai/api/v1"    # default
  api_key_env = "OPENROUTER_API_KEY"           # env var that holds the key
  ```

  For Ollama, use `base_url = "http://localhost:11434/v1"` and any non-empty
  key in the named env var.
- `anthropic`: the Anthropic API through the official SDK. Set
  `ANTHROPIC_API_KEY`; `model` defaults to a recent Claude model.

API keys are read from environment variables only; they are never written to
disk or logged. Every suggestion is resolved against YouTube Music before it is
queued, so the AI can only pick songs that exist there.
