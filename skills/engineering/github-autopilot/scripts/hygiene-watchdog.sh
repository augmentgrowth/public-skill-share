#!/usr/bin/env bash
# Daily git hygiene watchdog — three-tier sweep across local repos.
#
#   Tier 0 (this script, deterministic, free):
#     fetch --prune, delete local branches contained in default, prune dead
#     worktrees, collect findings that need judgment.
#   Tier 1 (cheap model): bounded cleanup of the findings via the
#     github-autopilot skill (push stranded branches, delete merged remote
#     branches, close obvious duplicates). Emits "ESCALATE: ..." for anything
#     judgment-heavy.
#   Tier 2 (strong model): runs only when Tier 1 escalated — parked-branch
#     integration, unmerged-and-gone triage, conflict-y merges.
#
# Safety posture: never force-push, never delete unmerged work, never touch
# backup/archive/rescue branches, never commit user dirty files; repos
# matching REPORT_ONLY_PATTERNS (e.g. client repos) get NO mutations at all.
#
# Configuration (environment variables, all optional):
#   REPOS_ROOT            root scanned for repos            (default: $HOME/code)
#   EXTRA_REPOS           extra repo paths, comma/space-sep (default: empty)
#   REPORT_DIR            where daily reports are written
#                         (default: $HOME/.local/state/github-autopilot/hygiene-reports)
#   REPORT_ONLY_PATTERNS  comma/space-separated glob patterns matched against
#                         each repo path; matches are report-only (no mutations).
#                         Example: REPORT_ONLY_PATTERNS="*/code/client-*,*acme*"
#   TIER1_MODEL           cheap model id for Tier 1  (default: claude-haiku-4-5)
#   TIER2_MODEL           strong model id for Tier 2 (default: claude-opus-4-6)
#   ESCALATE_CMD          optional hook command, default OFF. When set and
#                         unresolved leftovers remain, it is invoked with one
#                         argument: the path to a leftovers file. Wire it to
#                         your issue tracker, notifier, whatever.
#                         Example: ESCALATE_CMD="$HOME/bin/file-hygiene-ticket"
#
# Kill switch: touch ~/.config/github-autopilot/watchdog.off
# Dry run: hygiene-watchdog.sh --dry-run   (Tier 0 prints instead of acting;
# agent tiers are skipped)
#
# Scheduling: run daily via cron or launchd, e.g.
#   40 7 * * * REPOS_ROOT=$HOME/code /path/to/hygiene-watchdog.sh >> /tmp/git-hygiene-watchdog.log 2>&1
set -uo pipefail

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

KILL_SWITCH="$HOME/.config/github-autopilot/watchdog.off"
[ -f "$KILL_SWITCH" ] && { echo "watchdog disabled via $KILL_SWITCH"; exit 0; }

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
REPOS_ROOT="${REPOS_ROOT:-$HOME/code}"
EXTRA_REPOS="${EXTRA_REPOS:-}"
REPORT_DIR="${REPORT_DIR:-$HOME/.local/state/github-autopilot/hygiene-reports}"
REPORT_ONLY_PATTERNS="${REPORT_ONLY_PATTERNS:-}"
TIER1_MODEL="${TIER1_MODEL:-claude-haiku-4-5}"
TIER2_MODEL="${TIER2_MODEL:-claude-opus-4-6}"
ESCALATE_CMD="${ESCALATE_CMD:-}"

STAMP=$(date +%Y-%m-%d)
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/git-hygiene-watchdog.XXXXXX")
FINDINGS="$WORKDIR/findings.md"
ACTIONS="$WORKDIR/actions.md"
: > "$FINDINGS"; : > "$ACTIONS"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
act() { echo "- $*" >> "$ACTIONS"; log "ACTION: $*"; }
find_note() { echo "$*" >> "$FINDINGS"; }

is_report_only() {
  # Repos matching REPORT_ONLY_PATTERNS (comma/space-separated globs): never mutate.
  local repo="$1" pat
  [ -z "$REPORT_ONLY_PATTERNS" ] && return 1
  for pat in $(echo "$REPORT_ONLY_PATTERNS" | tr ',' ' '); do
    # shellcheck disable=SC2254
    case "$repo" in $pat) return 0 ;; esac
  done
  return 1
}

# --- discover repos (dedupe by toplevel; skip worktree checkouts, mirrors) ---
REPOS="$WORKDIR/repos.txt"
{
  find "$REPOS_ROOT" -maxdepth 3 -type d -name .git 2>/dev/null | sed 's#/\.git$##'
  [ -n "$EXTRA_REPOS" ] && echo "$EXTRA_REPOS" | tr ',' '\n'
} | sed '/^[[:space:]]*$/d' | sort -u > "$REPOS"

while IFS= read -r repo; do
  [ -d "$repo" ] || continue
  git -C "$repo" rev-parse --show-toplevel >/dev/null 2>&1 || continue
  RO=0; is_report_only "$repo" && RO=1
  default=$(git -C "$repo" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
  [ -z "$default" ] && default=$(git -C "$repo" rev-parse --quiet --verify main >/dev/null 2>&1 && echo main || echo master)
  branch=$(git -C "$repo" branch --show-current 2>/dev/null)

  # fetch --prune (network read; skip repo's remote ops on failure = wrong creds/offline)
  NET=1
  if [ "$RO" -eq 0 ]; then
    git -C "$repo" fetch --prune --quiet 2>/dev/null || NET=0
    [ "$NET" -eq 0 ] && find_note "- \`$repo\`: fetch failed (credentials/offline) — remote state may be stale, no remote ops attempted"
  fi

  # Tier 0a: delete local branches fully contained in default (not current, not
  # checked out in any worktree, not protected names, not backup/archive/rescue).
  # Skipped entirely in report-only repos.
  worktree_branches=$(git -C "$repo" worktree list --porcelain 2>/dev/null | awk '/^branch /{print substr($2,12)}')
  [ "$RO" -eq 1 ] && worktree_branches="__REPORT_ONLY__"
  while IFS= read -r b; do
    [ "$RO" -eq 1 ] && break
    b=$(echo "$b" | sed 's/^[* +]*//')
    [ -z "$b" ] && continue
    case "$b" in "$default"|main|master|"$branch") continue ;; esac
    case "$b" in backup/*|archive/*|rescue/*) continue ;; esac
    echo "$worktree_branches" | grep -qx "$b" && continue
    if [ "$DRY_RUN" -eq 1 ]; then
      log "DRY: would delete contained local branch $repo $b"
    else
      git -C "$repo" branch -d "$b" >/dev/null 2>&1 && act "$repo: deleted local branch \`$b\` (contained in $default)"
    fi
  done < <(git -C "$repo" branch --merged "$default" 2>/dev/null)

  # Tier 0b: prune dead worktree records (not in report-only repos)
  prunable=$(git -C "$repo" worktree list --porcelain 2>/dev/null | grep -c '^prunable' || true)
  if [ "${prunable:-0}" -gt 0 ] && [ "$RO" -eq 0 ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      log "DRY: would worktree-prune $repo ($prunable prunable)"
    else
      git -C "$repo" worktree prune 2>/dev/null && act "$repo: pruned $prunable dead worktree record(s)"
    fi
  fi

  # Tier 0c: collect judgment-needing findings for the agent tiers
  gone=$(git -C "$repo" branch -vv 2>/dev/null | grep '\[gone\]' | sed 's/^[* +]*//' | awk '{print $1}')
  for b in $gone; do
    # Squash-merge check: ancestry says unmerged, but if merging the branch
    # into default changes nothing (tree oid identical), its content already
    # landed — a false alarm that would otherwise re-escalate daily.
    mt=$(git -C "$repo" merge-tree --write-tree "$default" "$b" 2>/dev/null | head -1)
    dt=$(git -C "$repo" rev-parse "$default^{tree}" 2>/dev/null)
    if [ -n "$mt" ] && [ "$mt" = "$dt" ]; then
      find_note "- \`$repo\`: branch \`$b\` upstream GONE but content-contained in $default (squash-merged) — tag \`autopilot/trash/$(date +%Y%m%d)/$b\` then delete"
    else
      find_note "- \`$repo\`: branch \`$b\` upstream GONE and not contained in $default — verify contents, then delete or push"
    fi
  done
  while IFS= read -r line; do
    b=$(echo "$line" | sed 's/^[* +]*//' | awk '{print $1}')
    case "$b" in "$default"|main|master|backup/*|archive/*|rescue/*) continue ;; esac
    if echo "$line" | grep -q 'ahead'; then
      find_note "- \`$repo\`: branch \`$b\` has unpushed commits ($(echo "$line" | grep -o 'ahead [0-9]*'))"
    elif ! echo "$line" | grep -q '\['; then
      find_note "- \`$repo\`: branch \`$b\` has no upstream — stranded work?"
    fi
  done < <(git -C "$repo" branch -vv 2>/dev/null)
  if [ "$NET" -eq 1 ] && [ "$RO" -eq 0 ]; then
    for rb in $(git -C "$repo" branch -r 2>/dev/null | grep -E 'origin/(claude|codex)/' | sed 's/^ *//'); do
      find_note "- \`$repo\`: remote agent branch \`$rb\` — check integration state, delete if merged"
    done
  fi
  dirty=$(git -C "$repo" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  if [ "$dirty" -gt 0 ]; then
    find_note "- \`$repo\`: $dirty dirty file(s) (report-only — watchdog never commits user work)"
  fi
  [ "$RO" -eq 1 ] && [ "$dirty" -gt 0 ] && find_note "  (report-only repo: no mutations permitted)"

  # Track every checkout (repo + its worktrees) for stale-WIP aging.
  # Line-preserving read: worktree paths may contain spaces.
  git -C "$repo" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p' | \
    while IFS= read -r co; do [ -d "$co" ] && echo "$co" >> "$WORKDIR/checkouts.txt"; done
done < "$REPOS"

# --- Stale-WIP aging: dirty checkouts whose content stopped changing get escalated.
# Fingerprint = status + unstaged diff + staged diff + untracked content (size-guarded);
# mtime alone is unreliable. A checkout escalates only after its fingerprint is
# unchanged for >= WIP_STALE_DAYS (default 3). Requires jq; skipped without it.
# Nothing is ever auto-committed or discarded — the escalation is a decision prompt.
WIP_STATE="${WIP_STATE:-$HOME/.local/state/github-autopilot/wip-state.json}"
WIP_STALE_DAYS="${WIP_STALE_DAYS:-3}"
if command -v jq >/dev/null 2>&1; then
  mkdir -p "$(dirname "$WIP_STATE")"
  [ -f "$WIP_STATE" ] || echo '{}' > "$WIP_STATE"
  NOW=$(date +%s)
  NEW_STATE="$WORKDIR/wip-state.json"; cp "$WIP_STATE" "$NEW_STATE"
  if [ -s "$WORKDIR/checkouts.txt" ]; then
    sort -u "$WORKDIR/checkouts.txt" | while IFS= read -r co; do
      st=$(git -C "$co" status --porcelain 2>/dev/null)
      if [ -z "$st" ]; then
        jq --arg p "$co" 'del(.[$p])' "$NEW_STATE" > "$NEW_STATE.tmp" && mv "$NEW_STATE.tmp" "$NEW_STATE"
        continue
      fi
      fpfile="$WORKDIR/fp.tmp"
      { echo "$st"; git -C "$co" diff 2>/dev/null; git -C "$co" diff --cached 2>/dev/null; \
        git -C "$co" ls-files --others --exclude-standard -z 2>/dev/null | \
        while IFS= read -r -d '' f; do
          sz=$(stat -f%z "$co/$f" 2>/dev/null || stat -c%s "$co/$f" 2>/dev/null || echo 0)
          if [ "$sz" -le 5242880 ]; then
            h=$(git hash-object -- "$co/$f" 2>/dev/null)
            [ -n "$h" ] && printf '%s %s\n' "$h" "$f" || echo "HASHFAIL:$f"
          else echo "big:$f:$sz"; fi
        done; } > "$fpfile"
      # Any constituent hash failure poisons the fingerprint — skip aging entirely
      # rather than risk two failure states comparing equal.
      grep -q '^HASHFAIL:' "$fpfile" && continue
      fp=$(git hash-object --stdin < "$fpfile" 2>/dev/null)
      [ -z "$fp" ] && continue   # hashing failed — never age on an empty fingerprint
      prev_fp=$(jq -r --arg p "$co" '.[$p].fingerprint // ""' "$NEW_STATE")
      first=$(jq -r --arg p "$co" '.[$p].first_seen // 0' "$NEW_STATE")
      changed=$(jq -r --arg p "$co" '.[$p].last_changed // 0' "$NEW_STATE")
      if [ "$fp" != "$prev_fp" ]; then
        [ "$first" = "0" ] && first=$NOW
        jq --arg p "$co" --arg f "$fp" --argjson n "$NOW" --argjson fs "$first" \
          '.[$p]={fingerprint:$f,first_seen:$fs,last_changed:$n}' "$NEW_STATE" > "$NEW_STATE.tmp" && mv "$NEW_STATE.tmp" "$NEW_STATE"
      else
        age_days=$(( (NOW - changed) / 86400 ))
        if [ "$age_days" -ge "$WIP_STALE_DAYS" ]; then
          echo "STALE-WIP[fp:${fp:0:12}]: \`$co\` — uncommitted work unchanged for ${age_days} day(s). Decide: finish it, commit it to a WIP branch, or discard. Never auto-commit or discard$( is_report_only "$co" && echo '; report-only repo')." >> "$WORKDIR/stale-wip.txt"
        fi
      fi
    done
  fi
  [ -s "$WORKDIR/stale-wip.txt" ] && { echo "" >> "$FINDINGS"; echo "Stale WIP (fingerprint unchanged >= ${WIP_STALE_DAYS}d):" >> "$FINDINGS"; cat "$WORKDIR/stale-wip.txt" >> "$FINDINGS"; }
  # Atomic, validated state replace — a half-written state file would disable aging.
  if [ "$DRY_RUN" -eq 0 ] && jq empty "$NEW_STATE" 2>/dev/null; then
    cp "$NEW_STATE" "$WIP_STATE.tmp" && mv "$WIP_STATE.tmp" "$WIP_STATE"
  fi
else
  log "stale-WIP aging skipped (jq not installed)"
fi

# --- Tier 1: cheap model ---
ESCALATIONS="$WORKDIR/escalations.txt"; : > "$ESCALATIONS"
if [ -s "$FINDINGS" ] && [ "$DRY_RUN" -eq 0 ]; then
  log "Tier 1 ($TIER1_MODEL) on $(wc -l < "$FINDINGS" | tr -d ' ') finding(s)"
  T1_PROMPT="You are the daily git hygiene watchdog (Tier 1, cheap model). Load the github-autopilot skill and follow its decision-policy and safety boundaries exactly. Findings from the deterministic sweep:

$(cat "$FINDINGS")

Do ONLY bounded, obviously-safe cleanup: push stranded/ahead branches to origin with -u (same name); delete remote branches whose commits are verifiably contained in the default branch and have no open PR; delete gone-upstream local branches after containment verification. NEVER: force-push, delete unmerged work, touch backup/archive/rescue branches, commit dirty files, or mutate report-only (client) repos.

For anything needing real judgment — parked-branch integration, unmerged-and-gone branches, duplicate PRs, conflicts, ambiguous authority — do NOT attempt it; instead output a line starting exactly with 'ESCALATE: ' describing it. End with a short summary of actions taken."
  T1_OUT=$(cd "$HOME" && timeout 900 claude -p --model "$TIER1_MODEL" "$T1_PROMPT" 2>>"$WORKDIR/t1.err"); T1_STATUS=$?
  # claude -p can print auth failures to STDOUT and exit 0.
  case "$T1_OUT" in *"Failed to authenticate"*) T1_STATUS=1 ;; esac
  if [ "$T1_STATUS" -ne 0 ]; then
    log "Tier 1 run failed (status $T1_STATUS, see t1.err)"
    printf '%s' "$T1_OUT" >> "$WORKDIR/t1.err"   # partial/errant stdout is evidence, not results
    : > "$WORKDIR/t1.out"                        # empty = failed; -s checks depend on this
  else
    printf '%s' "$T1_OUT" > "$WORKDIR/t1.out"
    printf '%s\n' "$T1_OUT" | grep '^ESCALATE: ' > "$ESCALATIONS" || true
  fi
fi

# --- Tier 2: strong model (only on escalation) ---
if [ -s "$ESCALATIONS" ] && [ "$DRY_RUN" -eq 0 ]; then
  log "Tier 2 ($TIER2_MODEL) on $(wc -l < "$ESCALATIONS" | tr -d ' ') escalation(s)"
  T2_PROMPT="You are the git hygiene watchdog Tier 2 (escalation). Load the github-autopilot skill; follow its decision-policy, merge policy, and safety boundaries. The cheap tier escalated these cases:

$(cat "$ESCALATIONS")

Handle them with full judgment: selective integration of parked agent branches (work in a temporary worktree, never move a checkout the automation depends on off its default branch), duplicate-PR disposition, unmerged-and-gone triage. Hard limits unchanged: no force-push, no unmerged deletion, no backup/archive/rescue deletion, report-only (client) repos untouched, no user-dirty-file commits. If a case still needs the human (product decision, missing credentials), say so explicitly in your summary. End with a summary of what you did and anything left for the human."
  T2_OUT=$(cd "$HOME" && timeout 2400 claude -p --model "$TIER2_MODEL" "$T2_PROMPT" 2>>"$WORKDIR/t2.err"); T2_STATUS=$?
  case "$T2_OUT" in *"Failed to authenticate"*) T2_STATUS=1 ;; esac
  if [ "$T2_STATUS" -ne 0 ]; then
    log "Tier 2 run failed (status $T2_STATUS, see t2.err)"
    printf '%s' "$T2_OUT" >> "$WORKDIR/t2.err"
    : > "$WORKDIR/t2.out"
  else
    printf '%s' "$T2_OUT" > "$WORKDIR/t2.out"
  fi
fi

# --- report (only when something happened) ---
if [ -s "$ACTIONS" ] || [ -s "$FINDINGS" ]; then
  mkdir -p "$REPORT_DIR"
  REPORT_OUT="$REPORT_DIR/$STAMP.md"
  # A dry run must never clobber a real report.
  [ "$DRY_RUN" -eq 1 ] && REPORT_OUT="$REPORT_DIR/$STAMP.dry-run.md"
  {
    echo "# Git hygiene watchdog — $STAMP"
    echo
    if [ -s "$ACTIONS" ]; then echo "## Tier 0 deterministic actions"; cat "$ACTIONS"; echo; fi
    if [ -s "$WORKDIR/t1.out" ]; then echo "## Tier 1 ($TIER1_MODEL)"; cat "$WORKDIR/t1.out"; echo; fi
    if [ -s "$WORKDIR/t2.out" ]; then echo "## Tier 2 ($TIER2_MODEL)"; cat "$WORKDIR/t2.out"; echo; fi
    if [ ! -s "$WORKDIR/t1.out" ] && [ -s "$FINDINGS" ]; then echo "## Findings (unprocessed$( [ "$DRY_RUN" -eq 1 ] && echo ', dry run'))"; cat "$FINDINGS"; fi
    # Preserve tier failure causes — t1.err/t2.err die with WORKDIR otherwise.
    for tier in t1 t2; do
      if [ -s "$WORKDIR/$tier.err" ] && [ ! -s "$WORKDIR/$tier.out" ]; then
        echo "## ${tier} FAILURE (stderr)"; tail -20 "$WORKDIR/$tier.err"; echo
      fi
    done
  } > "$REPORT_OUT"
  log "report: $REPORT_OUT"
  # Rolling plain-English ledger: one line per deterministic action, one file
  # across all days (daily reports remain the detailed record).
  if [ -s "$ACTIONS" ] && [ "$DRY_RUN" -eq 0 ]; then
    sed "s/^- /[$STAMP] watchdog: /" "$ACTIONS" >> "$REPORT_DIR/LEDGER.md"
  fi
else
  log "clean sweep — nothing to do, no report written"
fi

# --- close the loop: hand unresolved leftovers to an optional escalation hook ---
# Only genuine residue counts: escalations Tier 2 never handled, whole tiers
# that failed to run, or agent output explicitly leaving items for the human.
# Dirty-file findings are excluded on purpose (usually live WIP; the Stop hook
# owns those at session end). The hook is OFF unless ESCALATE_CMD is set; it
# receives one argument, the path to a leftovers file — wire it to your issue
# tracker or notifier.
LEFTOVERS="$WORKDIR/leftovers.md"; : > "$LEFTOVERS"
if [ "$DRY_RUN" -eq 0 ]; then
  # Stale WIP always reaches the escalation hook — it is the one dirty-file
  # class the Stop hook can never see (the owning session never ended a turn).
  [ -s "$WORKDIR/stale-wip.txt" ] && cat "$WORKDIR/stale-wip.txt" >> "$LEFTOVERS"
  [ -s "$ESCALATIONS" ] && [ ! -s "$WORKDIR/t2.out" ] && cat "$ESCALATIONS" >> "$LEFTOVERS"
  [ -s "$FINDINGS" ] && [ ! -s "$WORKDIR/t1.out" ] && { echo "Tier 1 never ran/failed; unprocessed findings:"; cat "$FINDINGS"; echo "Tier 1 stderr (cause):"; tail -10 "$WORKDIR/t1.err" 2>/dev/null; } >> "$LEFTOVERS"
  for f in t1.out t2.out; do
    [ -s "$WORKDIR/$f" ] && grep -iE "left for the human|blocker|needs (the )?human|missing credential|product decision" "$WORKDIR/$f" >> "$LEFTOVERS" || true
  done
fi

if [ -s "$LEFTOVERS" ] && [ -n "$ESCALATE_CMD" ]; then
  if $ESCALATE_CMD "$LEFTOVERS"; then
    log "escalation hook handled $(grep -c . "$LEFTOVERS") leftover item(s)"
  else
    log "WARN: escalation hook failed; leftovers remain in the report"
  fi
elif [ -s "$LEFTOVERS" ]; then
  log "leftovers exist ($(grep -c . "$LEFTOVERS") item(s)); no ESCALATE_CMD configured — see the report"
fi
rm -rf "$WORKDIR"
