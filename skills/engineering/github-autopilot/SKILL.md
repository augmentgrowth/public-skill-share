---
name: github-autopilot
version: 1.1.0
description: Own GitHub closeout end-to-end — commit, push, PR, merge, branch/worktree cleanup, CI, review feedback, and credential routing. Invoke UNPROMPTED at the end of any session that changed files in a git repo; also on any commit/push/PR/merge/cleanup request.
triggers:
  - own this PR
  - get this branch green
  - resolve this merge conflict
  - push this work
  - open or update the PR
  - address PR feedback
  - fix failing CI
  - GitHub closeout
  - merge this PR
  - clean up branches
  - end-of-session with changed files in a git repo
mutating: true
---

# GitHub Autopilot

Own GitHub stewardship after meaningful work. Continue through branch sync, credential checks, commits, PR updates, CI failures, review feedback, and merge/rebase conflicts until the work is done or a stop condition fires.

Load this root file first. It is a router, not a full workflow. Read only the reference needed for the current state.

Enforcement (optional): a Stop hook (`scripts/stop-closeout-guard.py`) can block turn-end once per session+repo when uncommitted/unpushed work exists and point here. You register it yourself in `settings.json` (see the README and the comment block in the script). If that guard fired, run the Default Closeout Loop now instead of asking the user what to do.

## Autonomy Contract

- Treat GitHub closeout as part of the session when files changed, a PR exists, CI is red, review feedback is pending, a merge/rebase is in progress, or the user asks to ship/push. Run it UNPROMPTED — a bare "commit", "push", or "merge" from the user means closeout failed to self-start. The user should never be the trigger.
- Closeout is end-to-end: commit → push → PR → CI green → review resolved → **merged** → head branch deleted → hygiene sweep. A green PR left unmerged is unfinished work unless a stop condition or profile gate applies (see `references/pr-owner.md` Merge Policy).
- Operational judgment calls (auto-sync-swept edits, orphaned branches, duplicate PRs, scope pollution) follow `references/decision-policy.md`: act on the codified default and report, don't present option menus. Ask only for the genuine stops listed there.
- Every closeout ends with the hygiene sweep in `references/branch-hygiene.md` (prune `[gone]`/merged branches and prunable worktrees; drain any parked-branch queue a repo profile defines).
- Preserve unrelated dirty work. Stage only files that belong to the current task.
- In long autonomous sessions, commit at logical checkpoints (a feature lands, tests go green, a refactor completes) — not one giant commit at closeout. A session crossing hours of work with zero commits is losing recovery points.
- Resolve conflicts and CI failures directly when local evidence, PR context, and tests make the fix bounded.
- Optional engine layer — if you use the compound-engineering plugin, its skills slot in here (skip these lines otherwise):
  - `compound-engineering:ce-commit-push-pr` for commit, push, and PR creation/update.
  - `compound-engineering:ce-code-review` before PRs or when review is requested.
  - `compound-engineering:ce-resolve-pr-feedback` for unresolved PR review threads.
- Some repos have an automated sync process that owns default-branch content (auto-commit/auto-push on a schedule). Define that in a repo profile (`references/profiles/README.md`) so closeout knows what it owns and what the automation owns.
- Switch back to the default GitHub identity after repo-specific writes.

## Stop Conditions

Stop and report a blocker before any network write or destructive action when:

- A required GitHub account is not already authenticated in `gh`.
- The remote owner or repo authority is genuinely unknown (no profile, no remote signal) — not merely "I didn't check yet".
- A command would force-push, rewrite shared history, or delete UNMERGED branches/content without explicit user authorization. (Deleting merged/contained branches and pruning dead worktrees is normal hygiene — see `references/decision-policy.md`.)
- Unrelated dirty work could be swept into a commit.
- A secret, credential file, token, generated junk, cache, or stale rescue/archive branch content would be committed.
- Conflict resolution requires a product decision or source intent cannot be recovered.
- External communication is required.

Before asking ANY other question, check `references/decision-policy.md` — if the situation is in its default-action table, act instead of asking.

When stopped, include the repo path, branch, intended action, blocker, and the exact safe next command or decision needed.

## Routing Order

1. Confirm the current directory is inside a Git repo. If not, no GitHub stewardship applies.
2. Read `references/safety-boundaries.md` before destructive operations, force-pushes, branch deletion, or any prompt that asks to bypass safeguards.
3. Read `references/credentials.md` before `git fetch`, `git push`, `gh pr`, branch deletion, or any GitHub network write.
4. If the repo matches a repo profile you have defined (path, remote owner, or markers), read that profile under `references/profiles/` (see `references/profiles/README.md`).
5. If a merge, rebase, cherry-pick, or apply conflict is active, read `references/merge-conflicts.md`.
6. If a PR exists or should be opened/updated, read `references/pr-owner.md`.
7. If CI is failing, read `references/ci-repair.md`.
8. If review feedback is unresolved, read `references/review-feedback.md`.
9. If branch cleanup, upstream setup, stale branches, or agent branch integration is needed, read `references/branch-hygiene.md`.
10. Before asking the user any operational question, read `references/decision-policy.md`.

## Route Table

| State or Prompt | Reference |
|---|---|
| `git status` shows merge/rebase/cherry-pick conflicts | `references/merge-conflicts.md` |
| "own this PR", "ship this", "push this", open/update PR | `references/pr-owner.md` |
| `gh pr checks` failing or CI red | `references/ci-repair.md` |
| Unresolved PR comments or review threads | `references/review-feedback.md` |
| Untracked/dirty branch cleanup, upstream setup, agent branches | `references/branch-hygiene.md` |
| Path/remote/marker matches a defined repo profile | that profile under `references/profiles/` |
| Any GitHub network write | `references/credentials.md` |
| Force-push, branch delete, archive/rescue branch, secrets, unknown remote | `references/safety-boundaries.md` |
| About to ask the user an operational question | `references/decision-policy.md` |

## Default Closeout Loop

1. Inspect `git status --short`, current branch, remotes, upstream, and open PR state.
2. Choose the repo profile (if any) and credential route before network calls.
3. Protect unrelated work by building an explicit file list for the current task.
4. Commit logical changes, push, open or update the PR, and watch CI when a PR exists.
5. Address actionable review feedback and re-run checks.
6. Merge when the `pr-owner.md` Merge Policy is satisfied; delete the head branch.
7. Run the closeout hygiene sweep (`references/branch-hygiene.md`): prune `[gone]`/merged branches and dead worktrees; in auto-synced repos, drain any parked-branch queue the profile defines.
8. Switch back to the default GitHub identity if it was switched.
9. Report the full ledger — committed, pushed, PR, CI, merged or why not, branches/worktrees cleaned, identity used, judgment calls made per `decision-policy.md`, and any blockers. The report must preempt "was everything pushed and merged?"

## Gotchas

- **Squash merges blind ancestry checks.** `git branch --merged` and `git cherry` report fully-landed branches as unmerged when the PR was squash-merged. Always prove containment via the ladder in `references/branch-hygiene.md` — ancestry, then merged-PR `headRefOid` evidence, then `git merge-tree` content equivalence — before deleting or reporting "unmerged work".
- **A no-upstream branch with zero commits ahead of default is not stranded work.** Scratch and worktree branches trip "no upstream" constantly; check `git rev-list --count <default>..HEAD` before flagging or pushing.
- **Enforcement layers are harness-specific.** The Stop hook fires only in Claude Code; other harnesses reach this skill via their own routing (e.g. AGENTS.md) and nothing blocks their turn-end with dirty state. The daily watchdog is the cross-harness backstop.
- **Copy-pasted shell in references must be executed-verified.** A double-escaped sed in an earlier version of credentials.md output literal `\1` for every remote; any snippet a weaker model will run verbatim gets tested at edit time.
