# Getting Started

## Requirements

- Linux or macOS
- Python 3.11 or later and [`uv`](https://docs.astral.sh/uv/)
- `mpv` and `yt-dlp` on `PATH` (`youtube-dl` also works)

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
./install.sh    # installs the bester-ytm command with `uv tool install`
bester-ytm      # starts the TUI
```

Run `./install.sh` again after `git pull` to update the installed command.
To run from the working tree without installing:

```bash
uv sync
uv run bester-ytm
```

## First run

Search and playback need no account:

```bash
bester-ytm search "Beach House Myth"
bester-ytm play search "Beach House Myth" --seconds 20
```

In the TUI, two more sources work without an account:

- **Local files**: type a path such as `~/Music` or `local:~/Music` into the
  search box. `./scripts/download-example-songs.sh` fetches three
  public-domain songs into `examples/music/` to try it. See
  [Usage: Local files](usage.md#local-files).
- **Web radio**: type `radio:` to list the stations (ByteFM and KALX are
  built in) and press `Enter` to tune in. See
  [Usage: Web radio](usage.md#web-radio).

## Logging in

A login unlocks your library playlists, playlist creation and editing,
removing tracks from YouTube playlists, and liking songs on YouTube Music
with `f`, including the song a radio station is playing.

### Option 1 (recommended): browser login

Sign in at <https://music.youtube.com> in a browser on this machine, then run:

```bash
bester-ytm auth login
```

The command lists the browsers it finds, asks which one is signed in (`Enter`
picks the first), reads the login, checks it against YouTube Music, and saves
it. To name the browser directly:

```bash
bester-ytm auth login --browser firefox   # or chrome, chromium, brave, edge, ...
```

Firefox needs no prompts. Other browsers:

- **Chrome, Chromium, Brave, or Edge on macOS**: approve the one-time
  "Chrome Safe Storage" keychain dialog with `Always Allow`. The browser can
  stay open.
- **Any Chromium browser on Linux**: approve the keyring prompt if one appears.
- **Safari**: give your terminal Full Disk Access (System Settings, Privacy &
  Security, Full Disk Access), or use Firefox or Chrome.
- **Windows**: app-bound encryption locks Chrome cookies; use Firefox.

Check the login with:

```bash
bester-ytm auth status
```

The saved session expires after weeks, or when you log out of YouTube in that
browser. When account features stop working, run `bester-ytm auth login`
again.

#### Fallback: paste a request

If the command cannot read your browser, paste one logged-in request instead.
A blank line ends the paste; no `Ctrl-D` is needed.

```bash
bester-ytm auth login --paste
```

1. Open <https://music.youtube.com> while logged in.
2. Open developer tools (`F12`), select the `Network` tab, and filter for
   `/browse`.
3. Click a song so a `browse` request appears, then right-click it and choose
   `Copy`, `Copy as cURL` ("Copy as fetch" drops the cookie).
4. Paste into the terminal and press `Enter` on an empty line.

#### Headless machines: a cookies file

Export cookies for `music.youtube.com` with the "Get cookies.txt LOCALLY"
browser extension (the one whose name ends in `LOCALLY`), copy the file to the
server, and run:

```bash
bester-ytm auth login --cookies-file cookies.txt
```

For the longest-lived session, export from a private window: log in, open
`https://www.youtube.com/robots.txt`, export, and close the window. YouTube
rotates cookies on open tabs, so an isolated session lasts longer.

### Option 2: Google OAuth (self-refreshing token)

An OAuth token refreshes itself, so you never paste a login again, but YouTube
requires each app to bring its own OAuth credentials. Creating them is free
and takes about three minutes:

1. Open <https://console.cloud.google.com/> and create or select a project.
2. Enable the API: `APIs & Services`, `Library`, search `YouTube Data API v3`,
   `Enable`.
3. Configure consent: `APIs & Services`, `OAuth consent screen`, choose
   `External`, enter the app name and your email, and add the scope
   `https://www.googleapis.com/auth/youtube`. While the app is in `Testing`,
   add your Google account under `Test users`.
4. Create the client: `APIs & Services`, `Credentials`, `Create credentials`,
   `OAuth client ID`, application type `TVs and Limited Input devices`. Keep
   the client ID and secret at hand.

Then run:

```bash
bester-ytm auth login --oauth
```

It asks for the client ID and secret once, then opens the Google device-login
page in your browser.

### Where logins are stored

Logins are saved with mode `0600` under `~/.config/bester-ytm/`. When both
logins exist, the OAuth token wins. `bester-ytm auth logout` removes the saved
logins but keeps the OAuth client credentials, so the next `--oauth` login goes
straight to the browser step.
