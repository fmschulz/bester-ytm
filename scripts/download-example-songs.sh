#!/usr/bin/env bash
# Download three public-domain example songs (Musopen recordings hosted on
# Wikimedia Commons) into examples/music/ for trying local-file playback:
# search "local:examples/music" (or paste the absolute path) in the TUI.
set -euo pipefail

dest="$(cd "$(dirname "$0")/.." && pwd)/examples/music"
mkdir -p "$dest"
agent="bester-ytm-example-fetch/1.0"
base="https://upload.wikimedia.org/wikipedia/commons"

declare -A songs=(
  ["Beethoven - Piano Sonata No 28 - II Lebhaft.ogg"]="$base/b/bb/Beethoven_-_Piano_Sonata_No._28_in_A_Major%2C_Op._101_-_II._Lebhaft._Marschm%C3%A4%C3%9Fig.ogg"
  ["Mozart - Piano Sonata No 10 K330 - I Allegro.mp3"]="$base/9/97/Mozart%2C_Wolfgang_Amadeus_%E2%80%94_Piano_Sonata_No._10_in_C_major%2C_K._330_%E2%80%94_1st_movement_%E2%80%94_Bui-Nguyen_Trieu-Tuong_%E2%80%94_MusOpen_Project.mp3"
  ["Mozart - Piano Sonata No 10 K330 - III Allegretto.mp3"]="$base/b/b5/Mozart%2C_Wolfgang_Amadeus_%E2%80%94_Piano_Sonata_No._10_in_C_major%2C_K._330%2C_3rd_movement_%E2%80%94_Vadim_Chaimovich_%E2%80%94_Musopen_-8825.mp3"
)

for name in "${!songs[@]}"; do
  if [[ -s "$dest/$name" ]]; then
    echo "exists: $name"
    continue
  fi
  echo "downloading: $name"
  curl -fsSL -A "$agent" -o "$dest/$name" "${songs[$name]}"
done

echo "done: $dest"
