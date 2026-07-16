# Branch Hygiene

Use this for upstream setup, branch sync, stale branch inspection, agent branch integration, worktree cleanup, and the closeout hygiene sweep.

## Branch Preflight

```bash
git branch --show-current
git status --short
git branch -vv
git remote -v
git worktree list
git fetch --prune
```

Run `credentials.md` before `fetch`, `push`, or remote deletion.

## Rules

- Feature work belongs on a meaningful branch. Do not commit directly to default unless the user explicitly authorized it (an automated sync process that owns default-branch content per a repo profile is the one standing exception).
- Preserve unrelated dirty work.
- Prefer rebase for local feature branches when no shared history rewrite is involved.
- Do not force-push without explicit authorization.
- A branch with no upstream that carries real work gets pushed with `-u`, not left stranded.

## Closeout Hygiene Sweep (mandatory)

Run this sweep as part of every closeout in the repo, without being asked. It is cheap, and without it `[gone]` branches, prunable worktrees, and month-old parked branches quietly accumulate across every repo you touch.

1. `git fetch --prune`
2. Delete local branches whose upstream is `[gone]` after confirming their commits are contained in default (`git branch -vv` + `git branch --merged <default>` or `git cherry <default> <branch>`). Unmerged-and-gone → report, don't delete.
3. Delete local and remote branches fully merged into default (skip protected/default branches and branches with an open PR).
4. `git worktree prune`; remove worktrees git marks `prunable` when they have no dirty files.
5. In repos with an automated sync process, drain the parked agent-branch queue the repo profile defines.
6. Timestamped `backup/*`, `archive/*`, `rescue/*` branches: never delete autonomously; list them with age in the report and recommend disposal.

Deleting a merged/contained branch is allowed regardless of who created it — containment in default is the safety property, not authorship.

## Agent Branches

For agent branches (`claude/*`, `codex/*`, etc.), inspect before merging:

1. Branch name and age.
2. Commit list.
3. Changed file list.
4. Whether files are useful content, stale tooling, generated junk, or unrelated work.

Then integrate (merge/cherry-pick), preserve selectively, or skip with a stated reason — and delete the remote branch once integrated. Preserve useful content selectively; avoid whole-branch merges for stale archive/rescue branches.

## Summary

Report branches fetched, integrated, skipped, deleted (with containment evidence), worktrees pruned, and anything flagged for user disposal.
