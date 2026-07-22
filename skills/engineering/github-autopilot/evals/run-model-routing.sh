#!/usr/bin/env bash
# Model-in-the-loop routing eval: does model M, given only SKILL.md and a
# situation, invoke the skill and pick the right reference?
#
# Usage: run-model-routing.sh [--model <id>]... [--cases <n>] [--case <id>]
# Default model: claude-haiku-4-5-20251001 (the weakest tier that consumes
# this skill in production — the watchdog's Tier 1). Structural checks are
# run-checks.sh; this script costs real model tokens (~15 short calls/model).
set -uo pipefail
cd "$(dirname "$0")/.."

MODELS=()
LIMIT=0
ONLY_CASE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODELS+=("$2"); shift 2 ;;
    --cases) LIMIT="$2"; shift 2 ;;
    --case)  ONLY_CASE="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ ${#MODELS[@]} -eq 0 ] && MODELS=("claude-haiku-4-5-20251001")

SKILL_BODY=$(cat SKILL.md)
TMPERR=$(mktemp)
trap 'rm -f "$TMPERR"' EXIT
overall_fail=0

for MODEL in "${MODELS[@]}"; do
  echo "== model: $MODEL =="
  pass=0; fail=0; n=0
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    id=$(echo "$line" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
    [ -n "$ONLY_CASE" ] && [ "$id" != "$ONLY_CASE" ] && continue
    n=$((n+1)); [ "$LIMIT" -gt 0 ] && [ "$n" -gt "$LIMIT" ] && break
    prompt_text=$(echo "$line" | python3 -c 'import json,sys;print(json.load(sys.stdin)["prompt"])')
    exp_skill=$(echo "$line" | python3 -c 'import json,sys;v=json.load(sys.stdin)["expected_skill"];print(v or "null")')
    exp_route=$(echo "$line" | python3 -c 'import json,sys;v=json.load(sys.stdin)["expected_route"];print(v or "null")')

    OUT=$(timeout 120 claude -p --model "$MODEL" 2>"$TMPERR" "You are an agent with the following skill available. Read it, then decide how to handle the situation.

<skill name=\"github-autopilot\">
$SKILL_BODY
</skill>

SITUATION: $prompt_text

Respond with ONLY a JSON object, no prose: {\"invoke\": <true if you would run this skill for the situation, false if it does not apply>, \"route\": <the single references/*.md path you would read first for this state per the skill's Routing Order and Route Table, or null if invoke is false>}")
    STATUS=$?

    if [ "$STATUS" -ne 0 ] || [ -z "$OUT" ] || echo "$OUT" | grep -qi "failed to authenticate\|oauth"; then
      printf '%-32s %-4s %s\n' "$id" "ERR" "claude CLI failed (status=$STATUS; auth expired? run: claude login): $(tail -1 "$TMPERR" 2>/dev/null | cut -c1-80)"
      fail=$((fail+1)); continue
    fi
    got=$(echo "$OUT" | python3 -c '
import json,sys,re
t=sys.stdin.read()
m=re.search(r"\{.*\}",t,re.S)
try:
    d=json.loads(m.group(0)) if m else {}
    inv="github-autopilot" if d.get("invoke") else "null"
    route=d.get("route") or "null"
    print(inv+"\t"+str(route))
except Exception:
    print("PARSE_ERROR\tPARSE_ERROR")')
    got_skill=$(echo "$got" | cut -f1); got_route=$(echo "$got" | cut -f2)

    verdict=FAIL
    if [ "$got_skill" = "$exp_skill" ]; then
      if [ "$exp_skill" = "null" ] || [ "$got_route" = "$exp_route" ]; then verdict=PASS; fi
      # Profile cases: the profile file and its Routing Order prerequisite both count.
      case "$exp_route" in references/profiles/*)
        [ "$got_route" = "$exp_route" ] || [ "$got_route" = "references/credentials.md" ] && verdict=PASS ;;
      esac
    fi
    [ "$verdict" = "PASS" ] && pass=$((pass+1)) || fail=$((fail+1))
    printf '%-32s %-4s expect=%s got=%s/%s\n' "$id" "$verdict" "$exp_route" "$got_skill" "$got_route"
  done < evals/routing-cases.jsonl
  echo "-- $MODEL: $pass pass / $fail fail"
  [ "$fail" -gt 0 ] && overall_fail=1
  # Zero executed cases is a harness failure (bad --case id, empty file), not a pass.
  [ $((pass+fail)) -eq 0 ] && { echo "-- $MODEL: ERROR — no cases executed"; overall_fail=1; }
done
exit $overall_fail
