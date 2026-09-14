#!/bin/bash
# Terminal footage, recorded off-screen.
#
# asciinema captures the pty, not the display, so nothing bleeds in from
# whatever else is on this machine and no other agent's window can appear in a
# frame. Every command here is real and runs against live data; none of the
# output is written by hand.
set -u
cd "$(dirname "$0")/.."
mkdir -p video/casts

export AWS_PROFILE=palimpsest AWS_DEFAULT_REGION=us-east-1
unset AWS_BEARER_TOKEN_BEDROCK
set -a && . ./.env && set +a
export PS1='$ '

rec() {
  local name="$1"; shift
  local out="video/casts/${name}.cast"
  [ -f "$out" ] && { echo "  ${name} cached"; return; }
  asciinema rec "$out" --overwrite --cols 100 --rows 28 --command "$*" >/dev/null 2>&1
  echo "  ${name} $(python3 -c "import json,sys; d=[json.loads(l) for l in open('${out}') if l.startswith('[')]; print(f'{d[-1][0]:.1f}s')" 2>/dev/null || echo '?')"
}

echo "01 the live feed"
rec 01_feed ".venv/bin/python scripts/measure_feed.py"

echo "03 one pair, side by side"
rec 03_pair ".venv/bin/python scripts/show_pair.py"

echo "04+05 a real run, ending at the approval gate"
rec 04_run ".venv/bin/python -m agent.run --only amz-2026-0412 --days 400"

echo "07 the veto, attempted the way a misbehaving model would"
rec 07_veto ".venv/bin/python -m pytest tests/test_veto.py -v --no-header -q"

echo "08 the same check failing on purpose"
rec 08_mutation "bash video/mutate.sh"

echo "09 the unattended run, in production"
rec 09_unattended "bash video/unattended.sh"

echo "10 vehicles and food"
rec 10_breadth ".venv/bin/python scripts/show_breadth.py"

echo "11 reading a label off a photograph"
rec 11_label ".venv/bin/python scripts/show_label.py"

echo "12 what the company wrote back"
rec 12_reply ".venv/bin/python scripts/show_reply.py"
