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
t          toggle transition style (cut / crossfade)
[ / ]      shorten / lengthen the crossfade (1-15s)
v          cycle the visualizer (Mythos, Bars, Wave, Pulse, Scope)
Left/Right seek -10s/+10s
,/.        seek -30s/+30s
- / =      volume down / up
m          mute/unmute
r          cycle the selected track's rating (0 to 3, then back to 0)
Ctrl+P     show playlists (local first, then your YouTube library)
Tab        cycle panes
q          quit
```

### Search syntax

The search box understands structured queries:

```text
song:sepultura                      songs with the text in the title
artist:sepultura                    popular songs by the artist
artist:sepultura,albums             the artist's albums
artist:sepultura,year:1998,songs    tracks from the artist's 1998 releases
playlist:                           your local playlists
playlist:indie                      community playlists on YouTube Music
```

Selecting an album or playlist loads its tracks into the center queue pane.
`Ctrl+P` lists all your playlists in one place: locally saved playlists
(marked `LOCAL PLAYLIST`) first, then your YouTube Music library playlists
when logged in.

### Building a queue from search

Mark songs with `x` (marked rows show a `*`), then press Enter: all marked
songs move to the queue in list order and play with auto-advance. While
something is playing, marked songs are appended without interrupting it.

### Playback and transitions

The current track is marked `NOW`. When a track nears its end and the
transition style is crossfade (the default, 6 seconds), the next queued
track is prebuffered on a second silent mpv deck and blended in DJ-style
with an equal-power fade; set the transition to cut for instant switches.
The `DECK` line in the right pane shows the active deck and becomes a `MIX`
meter while two tracks blend. While audio plays, an audio-reactive visual
runs beneath the queue; pick a style with the `Visuals` dropdown or cycle
with `v`.

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
