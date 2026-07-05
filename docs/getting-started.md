# Getting Started

## Requirements

- Linux or macOS
- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- `mpv` and `yt-dlp` on `PATH` (`youtube-dl` is accepted as a fallback)

```bash
# macOS (Homebrew)
brew install uv mpv yt-dlp

# Ubuntu/Debian
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt-get install -y mpv yt-dlp

# Arch Linux
sudo pacman -S --needed uv mpv yt-dlp
```

## Install

From a clone of the repository:

```bash
./install.sh    # registers the bester-ytm command via `uv tool install`
bester-ytm      # launch the TUI
```

For development without installing globally:

```bash
uv sync
uv run bester-ytm
```

Search and playback work immediately, no account needed:

```bash
bester-ytm search "Beach House Myth"
bester-ytm play search "Beach House Myth" --seconds 20
```

Local audio files play without any account too: in the TUI, type a path
(e.g. `~/Music` or `local:~/Music`) into the search box and the files appear
as results. `./scripts/download-example-songs.sh` fetches three
public-domain example songs into `examples/music/` to try it; see
[Usage → Local files](usage.md#local-files).

Web radio also needs no account: type `radio:` in the search box to list the
stations (ByteFM and KALX built in) and press Enter to tune in — the Now
Playing label shows the live song; see [Usage → Web radio](usage.md#web-radio).

## Logging in

Logging in unlocks account features: your library playlists, playlist
create/update/delete, removing tracks, and liking songs on YouTube Music
with `f` — including the song a radio station is playing. There are two ways.

### Option 1 (recommended): browser login

Use your existing YouTube Music account directly — no Google Cloud Console,
no copy-paste. Just make sure a browser on this machine is signed in at
<https://music.youtube.com>, then run:

```bash
bester-ytm auth login
```

It finds the browsers you have installed, asks which one is logged in
(press `Enter` for the first), reads the login from that browser, checks it
against YouTube Music, and saves it. Target a specific browser directly with:

```bash
bester-ytm auth login --browser firefox   # or chrome, chromium, brave, edge, ...
```

Firefox is the smoothest (no prompts). Per-browser notes:

- **Chrome/Chromium/Brave/Edge on macOS**: a one-time "Chrome Safe Storage"
  keychain dialog appears the first time — click `Always Allow`. Chrome does
  not need to be closed.
- **Any Chromium browser on Linux**: if your keyring asks for access, approve it.
- **Safari**: give your terminal app Full Disk Access (System Settings →
  Privacy & Security → Full Disk Access), or just use Firefox/Chrome instead.
- **Windows**: Chrome cookies are locked by app-bound encryption; use Firefox.

Verify with:

```bash
bester-ytm auth status
```

The saved session eventually expires (typically after weeks, or when you log
out of YouTube in that browser). When account features stop working, run
`bester-ytm auth login` again.

#### Fallback: paste a request (no browser access)

If auto-detection cannot read your browser, paste one logged-in request instead
— no `Ctrl-D`, a blank line finishes it:

```bash
bester-ytm auth login --paste
```

1. Open <https://music.youtube.com> and make sure you are logged in.
2. Open developer tools (`F12`) → `Network` tab and filter for `/browse`.
3. Click a song so a `browse` request appears, then right-click it →
   `Copy` → `Copy as cURL` (not "Copy as fetch", which drops the cookie).
4. Paste into the terminal and press `Enter` on an empty line.

#### Headless machines: a cookies file

On a server with no local browser, export cookies for `music.youtube.com` with
the "Get cookies.txt LOCALLY" browser extension (pick the one whose name ends in
`LOCALLY`), copy the file over, and point the login at it:

```bash
bester-ytm auth login --cookies-file cookies.txt
```

For the longest-lived session, export from a private/incognito window: log in
there, visit `https://www.youtube.com/robots.txt`, export, then close the
window — YouTube rotates cookies on open tabs, so an isolated session lasts
longer.

### Option 2: Google OAuth (self-refreshing token)

The OAuth login never needs re-pasting, but YouTube requires every app to
bring its own OAuth credentials, so you create yours once (free, no billing,
about three minutes):

1. Open <https://console.cloud.google.com/> and create or select a project.
2. Enable the API: `APIs & Services` → `Library` → search
   `YouTube Data API v3` → `Enable`.
3. Configure consent: `APIs & Services` → `OAuth consent screen` → choose
   `External`, fill in the app name and your email, and add the scope
   `https://www.googleapis.com/auth/youtube`. While the app is in `Testing`,
   add your own Google account under `Test users`.
4. Create the client: `APIs & Services` → `Credentials` →
   `Create credentials` → `OAuth client ID` → application type
   `TVs and Limited Input devices`. Keep the client ID and secret ready.

Then run:

```bash
bester-ytm auth login --oauth
```

It prompts for the client ID and secret once, then opens the Google
device-login page in your browser.

### Notes for both options

Credentials and tokens are stored privately (mode `0600`) under
`~/.config/bester-ytm/`. If both logins exist, the OAuth token takes
precedence. `bester-ytm auth logout` removes the saved logins (the OAuth
client credentials are kept, so the next `--oauth` login skips straight to
the browser step).
