# Troubleshooting

**`mpv is not installed or not on PATH`**

Install `mpv`, then open a new terminal and retry.

**`yt-dlp is not installed or not on PATH`**

Install `yt-dlp`. `mpv` uses it to resolve YouTube Music streams.

**`auth status` fails but search works**

Search uses unauthenticated YouTube Music access; library playlists and
playlist editing require a login (`bester-ytm auth login`). A browser
login that stops working means the saved session has expired — run
`bester-ytm auth login` again.

**`auth login` cannot read my browser**

Make sure that browser is actually signed in at <https://music.youtube.com>.
On macOS, a Chromium browser needs you to approve the one-time "Chrome Safe
Storage" keychain prompt (click `Always Allow`); Safari needs your terminal to
have Full Disk Access. If nothing works, fall back to
`bester-ytm auth login --paste` and paste a `Copy as cURL` request, or export a
cookies file and use `--cookies-file` (see
[Getting Started → Logging in](getting-started.md#logging-in)).

**Browser login keeps expiring**

YouTube rotates account cookies on open YouTube tabs, so a login read from a
browser you actively use there can expire sooner. For a longer-lived session,
export cookies from a private/incognito window (log in, open
`https://www.youtube.com/robots.txt`, export, close the window) and pass the
file to `bester-ytm auth login --cookies-file`, or dedicate a separate browser
profile to YouTube Music that you never open interactively.

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
