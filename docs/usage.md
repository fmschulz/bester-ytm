# Usage

## The TUI

Launch with `bester-ytm`. The layout has three panes: search results on the
left, the playlist/queue in the center, and playback, metadata, and the
playlist builder on the right. The footer shows the shortcuts for the
focused pane.

### Keys

```text
/          focus search
Enter      play selected search result, playlist, or queue item
x          select/deselect the highlighted search result (also shift+click)
a          add the highlighted song or album to the queue, or every row
           marked with x (keeps what is already queued)
A          play now, replacing the queue (album searches; shift+a)
Space      play/pause
n          next track
p or b     previous track
s          shuffle playlist/queue
c          clear the queue (keeps the playing track)
d          remove the highlighted queue track; in search results, delete the
           highlighted playlist (local ones immediately, YouTube ones from
           your account after a confirming second press)
j / k      move the highlighted queue track down / up
w          save the queue as a local playlist (also the Save button)
g          add AI-suggested similar tracks to the queue
i          build a playlist from the builder prompt (right pane)
t          toggle transition style (cut / crossfade)
[ / ]      shorten / lengthen the crossfade (1-15s)
v          cycle the visualizer (Mythos, Oracle, Bars, Wave, Pulse, Scope)
Left/Right seek -10s/+10s
,/.        seek -30s/+30s
- / =      volume down / up
m          mute/unmute
r          cycle the selected track's rating (0 to 3, then back to 0)
f          save the current track to favorites
Ctrl+P     show playlists (local first, then your YouTube library)
Ctrl+A     show auth status
Tab        cycle panes
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
```

`song:` lists individual tracks; `album:` shows a tree of album names in the
left pane. Each album title is a branch you expand to its songs:

```text
left pane (album search)
- Enter on an album title    expand/collapse it (songs load on first expand)
- Enter on a song            play it now (or queue it if something is playing)
- x                          select/deselect the highlighted row (marked *)
                               on an album title this selects all its songs
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

In song results, mark songs with `x` (marked rows show a `*`), then press
`a` to add every marked song to the queue in list order, or `Enter` to do the
same. While something is playing, the songs are appended without interrupting
it; otherwise the first one starts and auto-advance plays the rest.

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

### Ratings, tags, and local playlists

The right pane edits the highlighted queue row, selected search song, or
current track. Local playlists are independent of YouTube playlists — useful
for collecting tracks before creating a real YouTube playlist.

## The CLI

```bash
bester-ytm                          # launch the TUI
bester-ytm search "Artist Song"     # search songs
bester-ytm play search "Artist Song"
bester-ytm play video VIDEO_ID
bester-ytm play playlist PLAYLIST_ID --transition crossfade --fade 8

bester-ytm playlist build --from seeds.md --name "My Mix" --count 30
bester-ytm playlist create PLAN_ID --privacy PRIVATE
bester-ytm playlist export PLAN_ID --format md

bester-ytm favorites import-tuiradio path/to/favs.md

bester-ytm auth login | status | logout
bester-ytm config show
```

`--transition` and `--fade` override the saved configuration for one run;
without them, `play playlist` uses the settings from
[`config.toml`](configuration.md).
