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
    find_note "- \`$repo\`: branch \`$b\` upstream GONE and not contained in $default — verify contents, then delete or push"
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
done < "$REPOS"

# --- Tier 1: cheap model ---
ESCALATIONS="$WORKDIR/escalations.txt"; : > "$ESCALATIONS"
if [ -s "$FINDINGS" ] && [ "$DRY_RUN" -eq 0 ]; then
  log "Tier 1 ($TIER1_MODEL) on $(wc -l < "$FINDINGS" | tr -d ' ') finding(s)"
  T1_PROMPT="You are the daily git hygiene watchdog (Tier 1, cheap model). Load the github-autopilot skill and follow its decision-policy and safety boundaries exactly. Findings from the deterministic sweep:

$(cat "$FINDINGS")

Do ONLY bounded, obviously-safe cleanup: push stranded/ahead branches to origin with -u (same name); delete remote branches whose commits are verifiably contained in the default branch and have no open PR; delete gone-upstream local branches after containment verification. NEVER: force-push, delete unmerged work, touch backup/archive/rescue branches, commit dirty files, or mutate report-only (client) repos.

For anything needing real judgment — parked-branch integration, unmerged-and-gone branches, duplicate PRs, conflicts, ambiguous authority — do NOT attempt it; instead output a line starting exactly with 'ESCALATE: ' describing it. End with a short summary of actions taken."
  T1_OUT=$(cd "$HOME" && timeout 900 claude -p --model "$TIER1_MODEL" "$T1_PROMPT" 2>>"$WORKDIR/t1.err") || log "Tier 1 run failed (see t1.err)"
  echo "$T1_OUT" | grep '^ESCALATE: ' > "$ESCALATIONS" || true
  echo "$T1_OUT" > "$WORKDIR/t1.out"
fi

# --- Tier 2: strong model (only on escalation) ---
if [ -s "$ESCALATIONS" ] && [ "$DRY_RUN" -eq 0 ]; then
  log "Tier 2 ($TIER2_MODEL) on $(wc -l < "$ESCALATIONS" | tr -d ' ') escalation(s)"
  T2_PROMPT="You are the git hygiene watchdog Tier 2 (escalation). Load the github-autopilot skill; follow its decision-policy, merge policy, and safety boundaries. The cheap tier escalated these cases:

$(cat "$ESCALATIONS")

Handle them with full judgment: selective integration of parked agent branches (work in a temporary worktree, never move a checkout the automation depends on off its default branch), duplicate-PR disposition, unmerged-and-gone triage. Hard limits unchanged: no force-push, no unmerged deletion, no backup/archive/rescue deletion, report-only (client) repos untouched, no user-dirty-file commits. If a case still needs the human (product decision, missing credentials), say so explicitly in your summary. End with a summary of what you did and anything left for the human."
  T2_OUT=$(cd "$HOME" && timeout 2400 claude -p --model "$TIER2_MODEL" "$T2_PROMPT" 2>>"$WORKDIR/t2.err") || log "Tier 2 run failed (see t2.err)"
  echo "$T2_OUT" > "$WORKDIR/t2.out"
fi

# --- report (only when something happened) ---
if [ -s "$ACTIONS" ] || [ -s "$FINDINGS" ]; then
  mkdir -p "$REPORT_DIR"
  {
    echo "# Git hygiene watchdog — $STAMP"
    echo
    if [ -s "$ACTIONS" ]; then echo "## Tier 0 deterministic actions"; cat "$ACTIONS"; echo; fi
    if [ -s "$WORKDIR/t1.out" ]; then echo "## Tier 1 ($TIER1_MODEL)"; cat "$WORKDIR/t1.out"; echo; fi
    if [ -s "$WORKDIR/t2.out" ]; then echo "## Tier 2 ($TIER2_MODEL)"; cat "$WORKDIR/t2.out"; echo; fi
    if [ ! -s "$WORKDIR/t1.out" ] && [ -s "$FINDINGS" ]; then echo "## Findings (unprocessed$( [ "$DRY_RUN" -eq 1 ] && echo ', dry run'))"; cat "$FINDINGS"; fi
  } > "$REPORT_DIR/$STAMP.md"
  log "report: $REPORT_DIR/$STAMP.md"
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
  [ -s "$ESCALATIONS" ] && [ ! -s "$WORKDIR/t2.out" ] && cat "$ESCALATIONS" >> "$LEFTOVERS"
  [ -s "$FINDINGS" ] && [ ! -s "$WORKDIR/t1.out" ] && { echo "Tier 1 never ran/failed; unprocessed findings:"; cat "$FINDINGS"; } >> "$LEFTOVERS"
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
