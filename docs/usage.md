# Usage

## The TUI

Launch with `bester-ytm`. Search and browse on the left, arrange the queue
in the center, and use the workspace on the right for playlists, the builder,
and crossfade settings. The stage fills the width below the panes, and the
player sits under it. Each pane's border shows its name and its main keys.
On narrow terminals, `F2` or **Tools** switches between the queue and workspace.
The top bar opens Favorites, Playlists, Radio, and Help.

Press `F1` from any input, or `?` outside an input, to open the keyboard guide.
Filter it by key or action, such as `favorite` or `volume`. `Esc` or `F1` closes
it and returns to the previous view.

### Keys

Pane-scoped keys act only while their pane has focus: `x`, `Shift+Space`,
`a`, `A`, and `Enter`-on-results need the results pane; `j`/`k`, `c`, and
`w` need the queue pane; `s`, `d`, `Space`-as-select, and `Enter`-on-queue
work from either list pane. The footer shows the main keys for the focused
pane; the keyboard guide lists every key.

```text
/          focus search
Enter      play selected search result, playlist, or queue item
x          mark/unmark the highlighted search result
Shift+Space  range-select: mark every song from the first marked one
           through the highlighted row (shift+click does the same)
a          add the highlighted song or album to the queue, or every row
           marked with x (keeps what is already queued)
A          play now, replacing the queue: the highlighted or marked songs
           in song results, or the album/highlighted song in album
           searches (shift+a)
Ctrl+Space pause/resume from any pane, including while typing
Space      play/pause; in the results pane it marks the highlighted
           song instead (same as x)
n          next track
p or b     previous track
s          shuffle playlist/queue
c          clear the queue (keeps the playing track)
d          remove the highlighted queue track (the playing row is kept;
           press n to skip it); in search results, delete the highlighted
           playlist (local or YouTube) after a confirming second press
j / k      move the highlighted queue track down / up
w          save the queue as a local playlist (also the Save button)
g          add 5 AI-suggested similar tracks to the queue; type digits
           right after g to change the count (g11 adds 11), Esc cancels
i          build a playlist from the builder prompt (right pane)
t          toggle transition style (cut / crossfade)
[ / ]      shorten / lengthen the crossfade (1-15s)
v          next stage scene (Astra, Pulsar, Bars, Scope)
V          full-screen stage (Shift+v; clicking the stage does the same); Esc returns
F2         open the workspace tools on a narrow terminal
Left/Right seek -10s/+10s
,/.        seek -30s/+30s
- / = / +  volume down / up (both = and + raise it)
m          mute/unmute
f          toggle the focused song's local favorite; otherwise the playing song
           ★ marks saved songs; radio favorites resolve the live song
Ctrl+F     browse favorites (also the Favorites button)
Ctrl+P     show playlists (local first, then your YouTube library)
Ctrl+A     show auth status
Tab / Shift+Tab  cycle panes forwards / backwards
F1 / ?     open the searchable keyboard guide (Esc or F1 closes it)
q          quit
```

### Search syntax

The search box understands structured queries:

```text
song:metallica                      songs ranked by relevance (songs: also works)
album:metallica                     albums by name (albums: also works)
album:metallica,year:1986           albums from a given year
artist:sepultura                    popular songs by the artist
artist:sepultura,albums             the artist's albums
artist:sepultura,year:1998,songs    tracks from the artist's 1998 releases
playlist:                           your local playlists (playlists: also works)
playlist:indie                      community playlists on YouTube Music
favs:                               your faved songs (favorites: and liked: too)
favs:sepultura                      faved songs matching the text
radio:                              web radio stations (ByteFM, KALX, your own)
local:~/Music                       audio files under a local folder
/home/you/Music/song.mp3            a pasted path also works (/, ~, or ./)
```

`song:` lists individual tracks; `album:` shows a tree of album names in the
left pane. Each album title is a branch you expand to its songs:

```text
left pane (album search)
- Enter on an album title    expand/collapse it (songs load on first expand)
- Enter on a song            play it now (or queue it if something is playing)
- Space / x                  mark/unmark the highlighted row (marked *)
                               on an album title this marks all its songs
- Shift+Space                range-select from the first marked song to the
                               highlighted one (shift+click does the same)
- a                          add to the queue (keeps what is already there):
                               album title -> all its songs
                               song        -> that one song
                               any selected -> every selected song, in order
- A (shift+a)                play now, replacing the whole queue:
                               album title -> the whole album from the top
                               song        -> the album from that song on
                               any selected -> the selected songs
```

`a` keeps the current queue and appends; `A` clears it and starts the album
immediately. With an empty queue, `a` (or Enter on a song) also starts
playback; with a loaded but stopped queue it only appends. `artist:...,albums`
still lists albums in the normal results pane, where `Enter` loads the whole
album into the queue. Selecting a playlist loads its tracks into the center
queue pane. `Ctrl+P` lists all your playlists in one place: locally saved
playlists (marked `LOCAL PLAYLIST`) first, then your YouTube Music library
playlists when logged in.

### Building a queue from search

In song results, mark songs with `x` or `Space` (marked rows show a `*`);
`Shift+Space` or shift+click marks the whole range from the first marked
song through the highlighted one. Press `a` to add every marked song to the
queue in list order, or `Enter` to do the same. While something is playing
(or a loaded queue is stopped), the songs are appended without interrupting
it; with an empty queue the first one starts and auto-advance plays the
rest.

### Playback and transitions

The playing track carries `▶` in the queue, and tracks already played are
dimmed. When a track nears its end and the transition style is crossfade
(the default, 6 seconds), the next queued track is prebuffered on a second
silent mpv deck and blended in DJ-style with an equal-power fade; set the
transition to cut for instant switches. The crossfader in the player
(`A ━━━━●━━━━ B`) shows the live deck, and its knob slides to the other
deck while two tracks blend. A dotted rail means the transition is cut.

The seek bar draws how loud each stretch of the current track was when it
played, so the played part shows the shape of the song. Stretches skipped
by seeking stay flat. Click the bar to seek to that position. A web radio
stream has no end, so the bar shows its recent loudness instead.

The stage shows an audio-reactive scene in the colors of the active theme:

- **Astra**: a black hole whose accretion disk heats up and spins faster
  with the music; sudden onsets flare the photon ring.
- **Pulsar**: a ridgeline plot of recent loudness, drawn like the pulsar
  plot on the cover of Joy Division's *Unknown Pleasures*. The front ridge
  moves live; older ridges recede.
- **Bars**: a loudness skyline with the newest sample on the right.
- **Scope**: a Lissajous figure on a phosphor screen that swells with
  loudness and leaves fading trails.

The scenes react to the loudness that mpv reports; they have no frequency
data. Pausing freezes the scene; with nothing playing, the stage shows a dim
still.

Choose a scene from the stage dropdown or press `v`. Press `V` (Shift+v) or
click the stage for full screen, and press `Esc` or click again to return.
The player stays visible. Open the command palette with `Ctrl+Shift+P` to
choose a theme; the stage takes its colors from it.
On slow or remote terminals, lower `ui.visual_fps`, or set it to `0` for
still frames. At `0` the seek bar shows progress without the loudness shape.

### Favorites

Press `f` to toggle the highlighted song in results, an expanded album, or
the queue. Outside those lists, it acts on the playing track. The star
button in the player always acts on the current track.

Saved tracks show `★` in results, the queue, and album trees, and the
player's star fills while a saved track plays. Open
**Favorites** or press `Ctrl+F` to browse them. `Enter` plays or queues a
song; `a` queues it; `f` removes it. Removal keeps the cursor on a remaining
row. Edit the search to `favs:sepultura` to filter by text. `favorites:` and
`liked:` are aliases for this local list.

Favorites are stored in `favorites.json` under the app's data directory.
They work without a login and do not change YouTube Music likes.

### Web radio

Type `radio:` in the search box to list the web radio stations (rows are
labelled `RADIO`): ByteFM and KALX ship built in, and you can add your own
in the config (see [Configuration](configuration.md)). `Enter` on a station
tunes to it: whatever is playing stops with a hard cut (no crossfade), the
station starts, and it becomes the queue's only row — selecting another
station switches the same way, so there is never more than one station in
the queue. While a station plays, the Now Playing label shows the live
track (`ByteFM · Artist - Song`), refreshed every ~20 seconds from the
station's metadata, and `g` finds songs similar to that live track (not to
the station) and queues them after it.

Pressing `f` while radio plays favs the song the station is playing, not the
station: the track is looked up on YouTube Music and saved to local favorites.
The status line names the match. Radio playback and local favorites work
without a login.

To add a station without hunting for its stream URL yourself, type
`add radio station <name>` (e.g. `add radio station WFMU`) into the playlist
builder box and press Build: the configured AI provider looks up the
station's direct stream URL, bester-ytm verifies the URL actually serves
audio, and the station is written to `[radio.stations]` in `config.toml` —
it then shows up under `radio:`. If the AI cannot find a working stream, the
status line says so and nothing is written; you can always add a station
manually in the config (see [Configuration](configuration.md)).

### Local files

Type `local:` followed by a path — or just paste a path starting with `/`,
`~`, or `./` — into the search box to list local audio files in the left
pane. A folder is scanned recursively (`.mp3`, `.flac`, `.ogg`, `.opus`,
`.m4a`, `.wav`, `.aac`, `.aiff`, `.wma`); a single file lists just that
file. The rows behave like any song result: `Enter` plays, `a` queues, `f`
favs, and crossfade transitions work between local and YouTube tracks alike.
Local tracks can be saved into local playlists, but they cannot be added to
YouTube playlists.

To try it without pointing at your own library, download three
public-domain example songs (Musopen recordings) and list them:

```bash
./scripts/download-example-songs.sh
```

Then search `local:examples/music` from the repo directory (or paste the
absolute path).

### Local playlists

Local playlists are independent of YouTube playlists — useful for collecting
tracks before creating a real YouTube playlist.

The workspace's **Playlist** section manages the queue as a named playlist.
It holds the playlist name field, the **New playlist**, **Save queue**,
**Add track**, and **Remove track** buttons, and **Shuffle** and
**Clear queue**. The **Mix style** and **Fade −** / **Fade +** controls are
in the **Crossfade** section.

- **New playlist** starts a fresh playlist: the queue is cleared (a playing
  track keeps playing and stays as the first row), the loaded playlist is
  detached, and the name field is emptied and focused so you can name the
  new one.
- **Save queue** (also `w`) saves the queue exactly as a local playlist
  under the typed name, falling back to the loaded playlist's title, then
  `Saved Queue`, so removals and reordering done with `d`/`j`/`k` persist.
- **Add track** adds the selected track (the highlighted queue row, else
  the highlighted search song, else the playing track) to the local
  playlist named in the field; without a name it uses the loaded local
  playlist, or creates `TUI Playlist`.
- **Remove track** removes the selected track (chosen the same way as for
  **Add track**) from the loaded playlist: local playlists are edited on
  disk, YouTube playlists in your account.

## The CLI

```bash
bester-ytm                          # launch the TUI
bester-ytm search "Artist Song" --limit 15    # search songs (1-25, default 10)
bester-ytm play search "Artist Song" --seconds 20
bester-ytm play video VIDEO_ID --seconds 20
bester-ytm play playlist PLAYLIST_ID --transition crossfade --fade 8

bester-ytm playlist build --from seeds.md --name "My Mix" --count 30 \
    --brief "high-energy openers" --allow-variants
bester-ytm playlist create PLAN_ID --privacy PRIVATE
bester-ytm playlist export PLAN_ID --format md

bester-ytm favorites import-tuiradio path/to/favs.md

bester-ytm auth login [--oauth] [--no-browser]
bester-ytm auth status
bester-ytm auth logout --yes
bester-ytm config show
```

- `--seconds` on the `play` commands plays a sample of that length, then
  exits.
- `playlist build` takes `--brief` for a free-form prompt or constraints and
  `--allow-variants` to permit obvious live/remix/cover candidates.
- `auth login --no-browser` (with `--oauth`) skips opening the web browser
  automatically; `auth logout --yes` skips the confirmation prompt.
- `play playlist` requires a login even for public playlist ids, because it
  fetches the playlist through the authenticated client.
- `--transition` and `--fade` override the saved configuration for one run;
  without them, `play playlist` uses the settings from
  [`config.toml`](configuration.md).
