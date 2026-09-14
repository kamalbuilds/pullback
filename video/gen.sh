#!/bin/bash
# One voice for the whole film: the same seed on every line. VoiceStudio's
# instruct field is a description, not an identity, so two calls with identical
# instruct text and no seed can return audibly different voices.
set -e
SEED=7317
INSTRUCT="female, middle-aged, moderate pitch, american accent"
cd "$(dirname "$0")"
while IFS='|' read -r num slug text; do
  [ -z "$num" ] && continue
  out="narration/${num}_${slug}.wav"
  [ -f "$out" ] && { echo "${num}_${slug}  cached"; continue; }
  curl -s -X POST http://localhost:3900/generate \
    -F "text=${text}" -F "instruct=${INSTRUCT}" \
    -F "effect_preset=broadcast" -F "seed=${SEED}" -o "$out"
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out" 2>/dev/null || echo FAIL)
  echo "${num}_${slug}  ${dur}s"
done < script.txt
echo "--- total ---"
ffprobe -v error -show_entries format=duration -of csv=p=0 narration/*.wav 2>/dev/null | paste -sd+ - | bc
