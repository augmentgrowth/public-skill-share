# github-autopilot

A Claude Code skill that owns GitHub closeout end-to-end, unprompted: commit → push → PR → CI green → review resolved → merged → head branch deleted → hygiene sweep. It exists so the agent never needs to be told "commit", "push", or "merge" — those words from the user are treated as a failure signal, not a trigger.

## The four layers

1. **Closeout loop** (`SKILL.md`) — a router that detects the current git/GitHub state and loads only the reference file for that state (PR ownership, CI repair, review feedback, merge conflicts, branch hygiene, credential routing).
2. **Decision policy** (`references/decision-policy.md`) — a default-action table for recurring operational judgment calls. Rule: if every candidate action is reversible with local git evidence and the decision is operational rather than product-level, act and report; never present option menus. A short "Still Ask" list covers the genuine stops (force-push, unmerged deletion, product decisions, missing credentials).
3. **Stop hook** (`scripts/stop-closeout-guard.py`, optional) — blocks turn-end once per session+repo when uncommitted or unpushed work exists, instructing the agent to run closeout. Fail-open, loop-guarded, and configurable per repo via `git config` flags.
4. **Daily watchdog** (`scripts/hygiene-watchdog.sh`, optional) — a scheduled three-tier sweep across all local repos: Tier 0 deterministic bash (fetch --prune, delete contained branches, prune worktrees), Tier 1 a cheap model for bounded cleanup, Tier 2 a strong model only on explicit escalations. Client repos can be marked report-only.

## Install

Copy this directory to your personal skills folder:

```bash
cp -R skills/github-autopilot ~/.claude/skills/github-autopilot
```

That alone enables the closeout loop and decision policy — Claude Code auto-loads the skill at the end of sessions that changed files in a git repo.

### Optional: Stop hook (enforcement)

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/github-autopilot/scripts/stop-closeout-guard.py"
          }
        ]
      }
    ]
  }
}
```

Per-repo tuning via git config:

```bash
git config --local githubAutopilot.localOnly true   # repo has no push target; only uncommitted work is flagged
git config --local githubAutopilot.autoSynced true  # an automated sync process owns default-branch content; dirty/unpushed checks are exempt there
```

### Optional: daily watchdog

Schedule `scripts/hygiene-watchdog.sh` via cron or launchd. Cron example (daily 07:40):

```cron
40 7 * * * REPOS_ROOT=$HOME/code REPORT_ONLY_PATTERNS="*/code/client-*" $HOME/.claude/skills/github-autopilot/scripts/hygiene-watchdog.sh >> /tmp/git-hygiene-watchdog.log 2>&1
```

Configuration is via environment variables (`REPOS_ROOT`, `REPORT_DIR`, `REPORT_ONLY_PATTERNS`, `TIER1_MODEL`, `TIER2_MODEL`, `ESCALATE_CMD`); see the header comment in the script. Kill switch: `touch ~/.config/github-autopilot/watchdog.off`. Test with `--dry-run` first.

### Repo profiles

Repos with special rules (client boundaries, separate GitHub accounts, automated sync processes) get a profile file under `references/profiles/`. See `references/profiles/README.md` for the pattern and a worked example.

## Philosophy

Agents chronically wait for the user to say "commit", "push", or "merge" — even when the work is done, CI is green, and nobody requested changes. Every one of those nudges is friction the agent created. This skill codifies the defaults instead: closeout is part of the task, operational git questions have codified answers, and the user is interrupted only for genuine stops (force-pushes, unmerged deletions, product decisions, missing credentials). The agent should never need to be told "commit", "push", or "merge".
