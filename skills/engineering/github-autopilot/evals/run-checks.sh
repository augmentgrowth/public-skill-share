#!/usr/bin/env bash
# Structural checks for the github-autopilot skill pack.
# Validates that every route referenced in routing-cases.jsonl and SKILL.md
# exists on disk, and that the eval cases parse. Agent-in-the-loop routing
# judgment still requires reading SKILL.md; this catches broken references.
set -euo pipefail
cd "$(dirname "$0")/.."

fail=0

# 1. Every expected_route in the eval cases must exist.
python3 - <<'PY' || fail=1
import json, os, sys
bad = 0
with open("evals/routing-cases.jsonl") as f:
    for i, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        case = json.loads(line)  # raises on malformed JSON
        for key in ("id", "prompt", "expected_skill", "expected_route", "expected_profile", "mutating"):
            if key not in case:
                print(f"case {i} ({case.get('id','?')}): missing key {key}")
                bad = 1
        route = case.get("expected_route")
        if route and not os.path.isfile(route):
            print(f"case {i} ({case['id']}): route file missing: {route}")
            bad = 1
sys.exit(bad)
PY

# 2. Every references/*.md path mentioned in SKILL.md must exist.
grep -oE 'references/[A-Za-z0-9_/-]+\.md' SKILL.md | sort -u | while read -r ref; do
    if [ ! -f "$ref" ]; then
        echo "SKILL.md references missing file: $ref"
        exit 1
    fi
done || fail=1

if [ "$fail" -eq 0 ]; then
    echo "OK: eval cases parse, all referenced routes exist."
else
    echo "FAIL: see messages above."
    exit 1
fi
