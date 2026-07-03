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
about one minute:

```bash
bester-ytm auth login
```

The command walks you through it:

1. Open <https://music.youtube.com> and make sure you are logged in.
2. Open developer tools (`F12`) → `Network` tab and filter for `/browse`.
3. Click a song so a `browse` request appears (the request only shows up
   after you interact with the page), then select it.
4. Copy its request headers (Firefox: right-click → `Copy` →
   `Copy Request Headers`; Chrome: select and copy the whole
   `Request Headers` block).
5. Paste into the terminal, then press `Enter` and `Ctrl-D`.

Verify with:

```bash
bester-ytm auth status
```

The copied session eventually expires (typically after weeks, or when you
log out of YouTube in that browser). When account features stop working, run
`bester-ytm auth login` again and paste fresh headers.

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
