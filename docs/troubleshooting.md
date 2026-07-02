# Troubleshooting

**`mpv is not installed or not on PATH`**

Install `mpv`, then open a new terminal and retry.

**`yt-dlp is not installed or not on PATH`**

Install `yt-dlp`. `mpv` uses it to resolve YouTube Music streams.

**`auth status` fails but search works**

Search uses unauthenticated YouTube Music access; library playlists and
playlist editing require a login (`bester-ytm auth login`). A browser
login that stops working means the copied session has expired — run
`bester-ytm auth login` again and paste fresh headers.

**`Error 403: access_denied` during OAuth login**

The Google OAuth app is probably still in testing. Add the exact Google
account as a test user on the OAuth consent screen, or publish/verify the
app.

**Terminal display looks corrupted during playback**

Restart the app after updating. Playback launches `mpv` with terminal I/O
disabled, so `mpv` output should not draw over the TUI.

**AI builds fail with `codex exec failed`**

The status line shows codex's final error. Most commonly the codex login
expired — run `codex logout && codex login` — or the CLI is not installed,
in which case set a different provider in
[`config.toml`](builder.md#ai-providers).
