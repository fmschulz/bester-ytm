# Troubleshooting

**`mpv is not installed or not on PATH`**

Install `mpv`, open a new terminal, and retry.

**`yt-dlp is not installed or not on PATH`**

Install `yt-dlp`; `mpv` uses it to open YouTube Music streams.

**`auth status` fails but search works**

Search needs no login; library playlists and playlist editing do. Run
`bester-ytm auth login`. A browser login that stops working has expired; run
the same command again.

**`auth login` cannot read my browser**

Check that the browser is signed in at <https://music.youtube.com>. On macOS,
a Chromium browser needs the one-time "Chrome Safe Storage" keychain prompt
approved with `Always Allow`, and Safari needs your terminal to have Full Disk
Access. Otherwise use `bester-ytm auth login --paste` with a `Copy as cURL`
request, or `--cookies-file` with an exported cookies file (see
[Getting Started: Logging in](getting-started.md#logging-in)).

**Browser login keeps expiring**

YouTube rotates cookies on open YouTube tabs, so a login read from a browser
you use for YouTube expires sooner. Export cookies from a private window (log
in, open `https://www.youtube.com/robots.txt`, export, close the window) and
run `bester-ytm auth login --cookies-file`, or keep a separate browser profile
for YouTube Music that you never open.

**`Error 403: access_denied` during OAuth login**

The Google OAuth app is likely still in testing. Add your Google account as a
test user on the OAuth consent screen, or publish the app.

**`n` cuts instead of crossfading**

A manual `next` blends only when the next track is already prebuffered, which
happens in the last fade length plus 12 seconds of a track. Earlier, `n` cuts.

**AI builds fail with `codex exec failed`**

The status line shows codex's last error. Usually the codex login expired
(`codex logout && codex login`) or the CLI is not installed; in that case set
another provider in [`config.toml`](builder.md#ai-providers).
