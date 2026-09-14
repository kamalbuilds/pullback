#!/bin/bash
# Break the guardrail, watch the suite go red, put it back.
cd "$(dirname "$0")/.."
cp agent/pullback_agent.py /tmp/veto.bak
python3 - <<'PY'
import pathlib
p = pathlib.Path('agent/pullback_agent.py')
p.write_text(p.read_text().replace("hooks=[RemedyVeto(ledger, log)],", "hooks=[],"))
PY
echo "$ # the veto hook is now deleted"
.venv/bin/python -m pytest tests/test_veto.py -q 2>&1 | tail -4
cp /tmp/veto.bak agent/pullback_agent.py
echo
echo "$ # restored"
.venv/bin/python -m pytest tests -q 2>&1 | tail -2
