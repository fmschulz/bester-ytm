# Usage

## The TUI

Launch with `bester-ytm`. The layout has three panes: search results on the
left, the playlist/queue in the center, and playback, playlist controls, and
the playlist builder on the right. The footer shows the shortcuts for the
focused pane; `?` opens an overlay with every binding.

### Keys

```text
/          focus search
Enter      play selected search result, playlist, or queue item
x          mark/unmark the highlighted search result
Shift+Space  range-select: mark every song from the first marked one
           through the highlighted row (shift+click does the same)
a          add the highlighted song or album to the queue, or every row
           marked with x (keeps what is already queued)
A          play now, replacing the queue (album searches; shift+a)
Space      play/pause; in the results pane it marks the highlighted
           song instead (same as x)
n          next track
p or b     previous track
s          shuffle playlist/queue
c          clear the queue (keeps the playing track)
d          remove the highlighted queue track; in search results, delete
           the highlighted playlist (local or YouTube) after a confirming
           second press
j / k      move the highlighted queue track down / up
w          save the queue as a local playlist (also the Save button)
g          add AI-suggested similar tracks to the queue
i          build a playlist from the builder prompt (right pane)
t          toggle transition style (cut / crossfade)
[ / ]      shorten / lengthen the crossfade (1-15s)
v          cycle the visualizer (Mythos, Oracle, Bars, Wave, Pulse, Scope)
Left/Right seek -10s/+10s
,/.        seek -30s/+30s
- / = / +  volume down / up (both = and + raise it)
m          mute/unmute
f          fav/unfav the highlighted song (or the playing track); faved
           songs show a trailing * and pressing f again removes them
Ctrl+P     show playlists (local first, then your YouTube library)
Ctrl+A     show auth status
Tab / Shift+Tab  cycle panes forwards / backwards
?          show all key bindings in an overlay (Escape, q, or ? closes it)
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
playlist:                           your local playlists
playlist:indie                      community playlists on YouTube Music
favs:                               your faved songs (favorites: also works)
favs:sepultura                      faved songs matching the text
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
immediately. When nothing is playing, `a` (or Enter on a song) also starts
playback. `artist:...,albums`
still lists albums in the normal results pane, where `Enter` loads the whole
album into the queue. Selecting a playlist loads its tracks into the center
queue pane. `Ctrl+P` lists all your playlists in one place: locally saved
playlists (marked `LOCAL PLAYLIST`) first, then your YouTube Music library
playlists when logged in.

### Building a queue from search

In song results, mark songs with `x` or `Space` (marked rows show a `*`);
`Shift+Space` or shift+click marks the whole range from the first marked
song through the highlighted one. Press `a` to add every marked song to the
queue in list order, or `Enter` to do the same. While something is playing,
the songs are appended without interrupting it; otherwise the first one
starts and auto-advance plays the rest.

### Playback and transitions

The current track is marked `NOW`. When a track nears its end and the
transition style is crossfade (the default, 6 seconds), the next queued
track is prebuffered on a second silent mpv deck and blended in DJ-style
with an equal-power fade; set the transition to cut for instant switches.
The `DECK` line in the right pane shows the active deck and becomes a `MIX`
meter while two tracks blend. While audio plays, glowing audio-reactive
panels run in the bottom of every pane; pick a style with the `Visuals`
dropdown or cycle with `v`, and choose a theme from the command palette (the
circle in the header). On slow or remote terminals, lower `ui.visual_fps` in
the config (or set it to `0`) to ease the rendering load.

### Favorites

`f` favs the highlighted song in the queue or search results — or, when
neither pane has a song highlighted, the track that is playing. Faved songs
show a trailing `*` in the queue, in search results, and on the Now Playing
label; pressing `f` on a faved song removes it again. Type `favs:` in the
search box to list your favorites (add text, e.g. `favs:sepultura`, to
filter); the rows behave like any song result, so `Enter`, `a`, and `f` all
work there. Favorites live in `favorites.json` under the app's data
directory.

### Local playlists

Local playlists are independent of YouTube playlists — useful for collecting
tracks before creating a real YouTube playlist.

The right-pane `Playlist / Queue` section manages the queue as a named
playlist. It holds the playlist name field, the New / Save / Add / Remove
buttons, and the Shuffle / Clear controls (the Mix and Fade- / Fade+
transition controls sit under Now Playing, next to the volume row):

- `New` starts a fresh playlist: the queue is cleared (a playing track keeps
  playing and stays as the first row), the loaded playlist is detached, and
  the name field is emptied and focused so you can name the new one.
- `Save` (also `w`) saves the queue exactly as a local playlist under the
  typed name — falling back to the loaded playlist's title, then
  `Saved Queue` — so removals and reordering done with `d`/`j`/`k` persist.
- `Add` adds the current track to the local playlist named in the field;
  without a name it uses the loaded local playlist, or creates
  `TUI Playlist`.
- `Remove` removes the current track from the loaded playlist: local
  playlists are edited on disk, YouTube playlists in your account.

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
