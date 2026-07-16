# Safety Boundaries

Read this before destructive Git/GitHub actions, force-pushes, branch deletion, secret-adjacent diffs, archive/rescue branch handling, or any prompt asking to bypass safeguards.

## Hard Stops

Stop before acting when the operation would:

- Print, copy, commit, or move secrets. Secret values stay hidden; use the repo's secret management contract instead of hand-copying.
- Delete, archive, or overwrite user content without explicit authorization.
- Force-push, reset a shared branch, or rewrite remote history without explicit authorization and a verified target.
- Commit unrelated dirty work, generated junk, caches, dependency folders, pyc files, build outputs, or stale tooling.
- Push to a remote when the expected GitHub account is not authenticated or repo authority is unclear.
- Merge a stale archive/rescue branch wholesale into a content repo.

## Required Preflight

Run or inspect the equivalent state:

```bash
git rev-parse --show-toplevel
git branch --show-current
git status --short
git remote -v
git log --oneline --decorate -10
```

Before network writes, also follow `credentials.md`.

## Dirty Work Rule

Classify every changed path before staging:

- Current task: files explicitly changed for this work.
- User work: existing unrelated edits or untracked files.
- Generated or unsafe: caches, build outputs, secrets, logs, local runtime files.

Stage only current-task files. Report user work and unsafe files as preserved, not "cleaned up."

## Destructive Action Rule

Allowed without asking:

- Delete any local or remote branch whose commits are verifiably contained in the default branch (merged/`[gone]`-and-contained), regardless of who created it, when it is not protected/default and has no open PR. Containment is the safety property, not authorship.
- Prune worktrees git marks `prunable` when they carry no dirty files.
- Merge a PR that satisfies the Merge Policy in `pr-owner.md`.
- Abort a local merge/rebase only when no resolution has been made and the operation was started by this workflow.

Ask first:

- Force-push.
- Delete branches whose commits are NOT contained in default or any other ref (unmerged work would be lost).
- Delete timestamped `backup/*`, `archive/*`, `rescue/*` branches (list them with age instead).
- Drop commits.
- Reset, checkout, or clean paths that contain user work.
- Archive or delete user-authored content.

## Stop Report

When blocked, report:

- Repo path and branch.
- Intended action.
- Stop rule that fired.
- Evidence observed.
- Smallest safe next decision or command.
