# Safety Boundaries

Read this before destructive Git/GitHub actions, force-pushes, branch deletion, secret-adjacent diffs, archive/rescue branch handling, or any prompt asking to bypass safeguards.

## Hard Stops

Stop before acting when the operation would:

- Print, copy, commit, or move secrets. Secret values stay hidden; use the repo's secret management contract instead of hand-copying.
  - **Encrypted-at-rest files are the exception, and only while they stay encrypted.** A committed `*.sops.*` / `*.env.sops` file is the repo's intended tracked state — landing a rotated ciphertext through a PR is the sync contract working, not a secret leak. Before staging one, verify every assignment line is `ENC[...]`-wrapped; a single plaintext value makes it a hard stop again. Never print a decrypted value, and never stage a `.env`, keyfile, or token that is not encrypted.
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

- Delete any local or remote branch verifiably contained in the default branch — proven via the Containment Verification ladder in `branch-hygiene.md` (ancestry, merged PR, or merge-tree content equivalence; ancestry checks alone miss squash merges) — regardless of who created it, when it is not protected/default and has no open PR. Containment is the safety property, not authorship. Content-proven (non-ancestry) deletions require the local `autopilot/trash/<date>/<branch>` recovery tag first.
- Prune worktrees git marks `prunable` when they carry no dirty files.
- Remove a non-prunable worktree whose branch is contained in default, after adjudicating any dirty paths per `branch-hygiene.md` → *Adjudicating worktree dirt*. A worktree pins its branch, so leaving it standing makes that branch undeletable forever.
- Delete a timestamped `backup/*`, `archive/*`, `rescue/*` branch **once its commits are provably preserved elsewhere** — contained in default, or reachable from a tag on the remote whose peeled target matches the branch tip. When neither holds, create and push that tag first and verify it resolves before deleting. This is the same containment property as the rule above, not an exception to it: the preservation intent attaches to the commits, and a tag preserves them at least as well as a branch. Deleting the ref without one of those proofs remains a hard stop.
- Merge a PR that satisfies the Merge Policy in `pr-owner.md`.
- Abort a local merge/rebase only when no resolution has been made and the operation was started by this workflow.

Ask first:

- Force-push.
- Delete branches whose commits are NOT contained in default or any other ref (unmerged work would be lost).
- Delete a timestamped `backup/*`, `archive/*`, `rescue/*` branch that carries unique content and **cannot** be tagged (no push rights, remote unknown). List it with age instead. When it *can* be tagged, the ladder above covers it — no question needed.
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
