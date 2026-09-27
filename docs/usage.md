# Usage

## The TUI

Run `bester-ytm`. The left pane searches and browses, the center pane holds the
queue, and the right pane (the workspace) holds playlist tools, the playlist
builder, and crossfade settings. The stage spans the width below the panes,
with the player under it. Each pane's border shows its name and main keys. On
narrow terminals, `F2` or **Tools** switches between the queue and the
workspace. The top bar opens Favorites, Playlists, Radio, and Help.

`F1` (from anywhere) or `?` (outside an input) opens the keyboard guide. Type
to filter it, such as `favorite` or `volume`; `Esc` or `F1` closes it.

### Keys

`x`, `Shift+Space`, `a`, and `A` act in the results pane; `j`/`k`, `c`, and
`w` act in the queue. The footer shows the keys for the focused pane.

```text
/          focus search
Enter      play the selected result, playlist, or queue row
x          mark or unmark the highlighted result
Shift+Space  mark every song from the first marked one to the highlighted row
           (shift+click does the same)
a          add the highlighted song or album, or every marked row, to the queue
A          play now, replacing the queue (shift+a): the highlighted or marked
           songs, or in album results the album or the album from that song on
Ctrl+Space pause or resume from any pane, including while typing
Space      pause or resume; in the results pane it marks the highlighted song
n          next track
p or b     previous track
s          shuffle the queue
c          clear the queue (the playing track stays)
d          remove the highlighted queue row (not the playing one; press n to
           skip it); on a playlist result, delete that playlist after a second d
j / k      move the highlighted queue row down / up
w          save the queue as a local playlist
g          queue 5 AI-suggested similar tracks; digits after g set the count
           (g11 adds 11); Esc cancels
i          build a playlist from the builder box
t          switch the transition between cut and crossfade
[ / ]      shorten / lengthen the crossfade (1-15 s)
v          next stage scene: Astra, Pulsar, Bars, Scope
V          full-screen stage (a click on the stage does the same); Esc returns
F2         show or hide the workspace on a narrow terminal
Left/Right seek -10 s / +10 s
, / .      seek -30 s / +30 s
- / = / +  volume down / up
m          mute or unmute
f          favorite or unfavorite the focused song, else the playing song
Ctrl+F     browse favorites
Ctrl+P     browse playlists (local first, then your YouTube library)
Ctrl+A     show the login status
Tab / Shift+Tab  next / previous pane
F1 / ?     keyboard guide
q          quit
```

### Search syntax

```text
song:metallica                      songs by relevance (songs: also works)
album:metallica                     albums by name (albums: also works)
album:metallica,year:1986           albums from one year
artist:sepultura                    the artist's popular songs
artist:sepultura,albums             the artist's albums
artist:sepultura,year:1998,songs    tracks from the artist's 1998 releases
playlist:                           your local playlists (playlists: also works)
playlist:indie                      community playlists on YouTube Music
favs:                               your favorites (favorites: and liked: too)
favs:sepultura                      favorites that match the text
radio:                              web radio stations
local:~/Music                       audio files under a folder
/home/you/Music/song.mp3            a pasted path (starting with /, ~, or ./)
```

Result rows show the title, the artist and album, and the duration. Albums,
playlists, local playlists, and stations carry a tag instead of a duration
(`album`, `playlist`, `local`, `radio`); playlists from your YouTube library
carry `youtube`.

`album:` searches show a tree: each album is a branch that opens to its songs.

```text
Enter on an album     open or close it (songs load the first time)
Enter on a song       play it, or queue it if something is playing
Space or x            mark or unmark the row (●); on an album, all its songs
Shift+Space           mark from the first marked song to the highlighted one
a                     add to the queue: the album, the song, or every marked song
A (shift+a)           replace the queue and play: the album from the top, the
                      album from that song on, or the marked songs
```

`a` appends to the queue and `A` replaces it. With an empty queue, `a` or
`Enter` on a song also starts playback; with a loaded but stopped queue, `a`
only appends. In `artist:...,albums` results, `Enter` on an album loads it
into the queue. Selecting a playlist loads its tracks into the queue.

To queue several songs, mark them with `x` or `Space` (`●`), or a range with
`Shift+Space` or shift+click, then press `a` or `Enter`. They join the queue in
list order; with an empty queue, the first one starts playing.

### Playback and transitions

The playing track shows `▶` in the queue, and played tracks are dimmed. In
crossfade mode (the default, 6 seconds), the next track is prebuffered on a
second mpv deck and blended in with an equal-power fade; in cut mode, tracks
switch instantly. The player's crossfader (`A ━━━━●━━━━ B`) marks the live
deck, its knob slides across during a blend, and a dotted rail means cut mode.

The seek bar draws how loud each stretch of the track was when it played;
stretches skipped by seeking stay flat. Click it to seek. For web radio, it
shows the recent loudness.

### The stage

The stage draws one of four scenes in the colors of the active theme:

- **Astra**: a black hole whose accretion disk brightens and spins faster with
  the music; sudden onsets flare the photon ring.
- **Pulsar**: a ridgeline plot of recent loudness, after the pulsar plot on
  Joy Division's *Unknown Pleasures*. The front ridge moves live.
- **Bars**: a loudness skyline with the newest sample on the right.
- **Scope**: a Lissajous figure that swells with loudness and leaves fading
  trails.

The scenes use the loudness mpv reports; they have no frequency data. Pausing
freezes the scene, and with nothing playing the stage shows a dim still.

Pick a scene with the stage dropdown or `v`. `V` or a click on the stage
toggles full screen (`Esc` also returns); the player stays visible. Themes,
and with them the stage colors, change in the command palette
(`Ctrl+Shift+P`). On slow or remote terminals, lower `ui.visual_fps`; `0`
gives still frames and a seek bar without the loudness shape.

### Favorites

`f` saves or removes the highlighted song in results, an open album, or the
queue; outside those lists, it acts on the playing track. The star button in
the player always acts on the playing track.

Saved songs show `★` in results, the queue, and album trees, and the player's
star fills while one plays. **Favorites** or `Ctrl+F` lists them: `Enter` plays
or queues a song, `a` queues it, and `f` removes it. Type `favs:sepultura` to
filter; `favorites:` and `liked:` are aliases.

Favorites live in `favorites.json` in the data directory. They need no login
and do not change your YouTube Music likes.

### Web radio

`radio:` lists the stations: ByteFM and KALX are built in, and you can add
more in the [configuration](configuration.md). `Enter` on a station cuts to it
and makes it the only row in the queue. The player shows the live track
(`ByteFM · Artist - Song`), refreshed about every 20 seconds; `g` queues songs
similar to it, and `f` looks it up on YouTube Music and saves it to your
favorites. Radio needs no login.

To add a station, type `add radio station <name>` (for example
`add radio station WFMU`) in the builder box and press **Build playlist**. The
AI provider finds the stream URL, bester-ytm checks that it serves audio, and
the station is saved to `[radio.stations]` in `config.toml`. If no working
stream is found, the status line says so.

### Local files

Type `local:` and a path, or paste a path that starts with `/`, `~`, or `./`.
Folders are searched recursively for `.mp3`, `.flac`, `.ogg`, `.opus`, `.m4a`,
`.wav`, `.aac`, `.aiff`, and `.wma` files. The rows work like song results:
`Enter` plays, `a` queues, `f` saves a favorite, and crossfades work between
local and YouTube tracks. Local tracks can go into local playlists, not
YouTube playlists.

To try it, download three public-domain songs (Musopen recordings), then
search `local:examples/music` from the repository directory:

```bash
./scripts/download-example-songs.sh
```

### Local playlists

Local playlists live on this machine, apart from your YouTube playlists. The
workspace's **Playlist** section treats the queue as a named playlist:

- **New playlist** clears the queue (a playing track keeps playing as the first
  row), detaches the loaded playlist, and focuses the empty name field.
- **Save queue** (`w`) saves the queue as a local playlist under the typed
  name, else the loaded playlist's title, else `Saved Queue`. Removals and
  reordering are kept.
- **Add track** adds the highlighted queue row (else the highlighted search
  song, else the playing track) to the playlist named in the field, else to
  the loaded local playlist, else to a new `TUI Playlist`.
- **Remove track** removes that track from the loaded playlist: a local
  playlist on disk, or a YouTube playlist in your account.

**Shuffle** and **Clear queue** sit in the same section. The **Crossfade**
section holds **Mix style** (cut or crossfade) and **Fade −** / **Fade +**.

## The CLI

```bash
bester-ytm                                     # start the TUI
bester-ytm search "Artist Song" --limit 15     # search songs (1-25, default 10)
bester-ytm play search "Artist Song" --seconds 20
bester-ytm play video VIDEO_ID --seconds 20
bester-ytm play playlist PLAYLIST_ID --transition crossfade --fade 8

bester-ytm playlist build --from seeds.md --name "My Mix" --count 30 \
    --brief "high-energy openers" --allow-variants
bester-ytm playlist create PLAN_ID --privacy PRIVATE
bester-ytm playlist export PLAN_ID --format md

bester-ytm favorites import-tuiradio path/to/favs.md

bester-ytm auth login [--browser NAME | --paste | --cookies-file PATH | --oauth [--no-browser]]
bester-ytm auth status
bester-ytm auth logout --yes
bester-ytm config show
```

- `--seconds` plays a sample of that length, then exits.
- `playlist build --brief` adds a free-form prompt; `--allow-variants` allows
  obvious live, remix, and cover versions.
- `auth login --oauth --no-browser` does not open the browser;
  `auth logout --yes` skips the confirmation.
- `play playlist` needs a login, even for public playlists.
- `--transition` and `--fade` override [`config.toml`](configuration.md) for
  one run.
