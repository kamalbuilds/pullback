#!/bin/bash
# Turn each source screenshot into a clipping.
#
# A whole 3840x2160 web page scaled into a 1920x1080 frame renders its standfirst
# at about ten pixels and nobody can read it. So each source is cropped to the
# band that carries its masthead and the sentence being quoted, then set on the
# film's own background with a margin. It reads as a cutting pinned to a board,
# which is what it is.
set -euo pipefail
cd "$(dirname "$0")"

SRC=/Users/kamal/Desktop/devpost/assets/sources/recalls
OUT=cards
mkdir -p "$OUT"
BG=0x0a0e14

# name | source file | crop w:h:x:y   (coordinates in the original 3840x2160)
CLIPS="
nbc_head|nbc-rocknplay-less-than-10-percent.png|2688:760:576:28
nbc_photo|nbc-rocknplay-less-than-10-percent.png|1930:1420:1152:662
cpsc_after|cpsc-rocknplay-reannounce-8-deaths-after-recall.png|3320:530:380:170
senate_six|senate-commerce-cantwell-6-percent-participation.png|2840:1132:500:48
cr_seventy|consumer-reports-when-recalls-fail.png|2320:720:780:10
"

for row in $CLIPS; do
  name="${row%%|*}"; rest="${row#*|}"
  file="${rest%%|*}"; crop="${rest#*|}"
  ffmpeg -y -loglevel error -i "$SRC/$file" \
    -vf "crop=${crop},scale=1760:1000:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=${BG}" \
    -frames:v 1 "$OUT/${name}.png"
  echo "  ${name}  $(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$OUT/${name}.png")"
done
