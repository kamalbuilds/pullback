#!/bin/bash
# Assemble the film.
#
# One beat is one narration file and one visual, and the visual is cut to the
# narration's length rather than the other way round. Padding narration to fit
# footage is exactly how dead air gets shipped.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p clips out

W=1920
H=1080

# beat | visual sources, comma separated, split evenly across the beat
MANIFEST="
01_feed|casts/01_feed.cast
02_gap|cards/02_gap.png
03_pair|casts/03_pair.cast
04_run|casts/04_run.cast
05_gate|casts/04_run.cast
06_console|../console/shots/queue.png,../console/shots/case.png
07_veto|casts/07_veto.cast
08_mutation|casts/08_mutation.cast
09_unattended|casts/09_unattended.cast
10_breadth|casts/10_breadth.cast
11_label|../data/labels/luum_upc_label.png,casts/11_label.cast
12_reply|casts/12_reply.cast
13_close|cards/13_close.png
"

render_cast() {
  local cast="$1" gif="$2"
  [ -f "$gif" ] && return
  agg --theme monokai --font-size 20 --idle-time-limit 1 \
      --last-frame-duration 2 --fps-cap 30 "$cast" "$gif" >/dev/null 2>&1
}

# A still or a short gif becomes a clip of exactly DURATION seconds by cloning
# its last frame. Everything is scaled into the same 1920x1080 box first, so
# concat never sees a resolution change.
make_clip() {
  local src="$1" duration="$2" out="$3"
  ffmpeg -y -loglevel error \
    $([ "${src##*.}" = "png" ] || [ "${src##*.}" = "jpg" ] && echo "-loop 1 -t $duration") \
    -i "$src" \
    -vf "scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2:color=0x0a0e14,setsar=1,fps=30,tpad=stop_mode=clone:stop_duration=${duration}" \
    -t "$duration" -an -c:v libx264 -pix_fmt yuv420p -preset veryfast "$out"
}

segments=()
for row in $MANIFEST; do
  beat="${row%%|*}"
  sources="${row##*|}"
  narration="narration/${beat}.wav"
  [ -f "$narration" ] || { echo "missing $narration"; exit 1; }
  total=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$narration")

  IFS=',' read -ra parts <<< "$sources"
  share=$(echo "scale=3; $total / ${#parts[@]}" | bc)

  i=0
  pieces=()
  for src in "${parts[@]}"; do
    if [ "${src##*.}" = "cast" ]; then
      gif="clips/$(basename "${src%.cast}").gif"
      render_cast "$src" "$gif"
      src="$gif"
    fi
    piece="clips/${beat}_${i}.mp4"
    make_clip "$src" "$share" "$piece"
    pieces+=("$piece")
    i=$((i + 1))
  done

  # video for this beat, then marry it to its own narration line
  if [ "${#pieces[@]}" -gt 1 ]; then
    printf "file '%s'\n" "${pieces[@]/#/$PWD/}" > "clips/${beat}.txt"
    ffmpeg -y -loglevel error -f concat -safe 0 -i "clips/${beat}.txt" -c copy "clips/${beat}_v.mp4"
  else
    cp "${pieces[0]}" "clips/${beat}_v.mp4"
  fi

  ffmpeg -y -loglevel error -i "clips/${beat}_v.mp4" -i "$narration" \
    -c:v copy -c:a aac -b:a 192k -shortest "clips/${beat}_av.mp4"
  segments+=("clips/${beat}_av.mp4")
  echo "  ${beat}  ${total}s"
done

printf "file '%s'\n" "${segments[@]/#/$PWD/}" > clips/all.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i clips/all.txt \
  -c:v libx264 -pix_fmt yuv420p -preset medium -crf 20 -c:a aac -b:a 192k out/pullback.mp4

echo
echo "runtime: $(ffprobe -v error -show_entries format=duration -of csv=p=0 out/pullback.mp4)s"
echo "silence check (any gap over 1.5s is a defect):"
ffmpeg -i out/pullback.mp4 -af silencedetect=noise=-35dB:d=1.5 -f null - 2>&1 | grep -i "silence_duration" || echo "  none"
