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

## Containment Verification (before any branch deletion)

Squash-merged PRs are invisible to ancestry checks: `git branch --merged` and `git cherry`
report a fully-landed branch as unmerged. Verify containment in this order and stop at the
first proof:

1. **Ancestry:** branch appears in `git branch --merged <default>`. Delete freely.
2. **Merged PR:** `gh pr list --state merged --head <branch> --base <default> --json
   number,headRefOid` shows a merged PR whose `headRefOid` equals `git rev-parse <branch>`
   exactly. Both filters matter: a name-only match proves nothing (a reused or advanced
   branch can match an older merged PR while carrying new work), and without `--base
   <default>` a PR merged into some other branch (e.g. `release/*`) does not prove
   containment in default. Missing either → fall through to level 3. On full match: tag
   then delete.
3. **Content equivalence:** `git merge-tree --write-tree <default> <branch>` succeeds and the
   resulting tree oid equals `git rev-parse <default>^{tree}` — the branch adds nothing to
   default. Tag then delete.

No proof at any level → the branch carries unique work: report it, never delete.

For deletions proven by level 2 or 3 (content, not ancestry), first drop a local recovery tag:
`git tag autopilot/trash/$(date +%Y%m%d)/<branch> <branch>`. Never push these tags; prune tags
older than 30 days during the hygiene sweep. The reflog is only a fallback (unreachable
entries can expire in ~30 days) — the tag is the guarantee.

## Rules

- Feature work belongs on a meaningful branch. Do not commit directly to default unless the user explicitly authorized it (an automated sync process that owns default-branch content per a repo profile is the one standing exception).
- Preserve unrelated dirty work.
- Prefer rebase for local feature branches when no shared history rewrite is involved.
- Do not force-push without explicit authorization.
- A branch with no upstream that carries real work gets pushed with `-u`, not left stranded.

## Closeout Hygiene Sweep (mandatory)

Run this sweep as part of every closeout in the repo, without being asked. It is cheap, and without it `[gone]` branches, prunable worktrees, and month-old parked branches quietly accumulate across every repo you touch.

1. `git fetch --prune`
2. Delete local branches whose upstream is `[gone]` after proving containment via the
   Containment Verification ladder above (ancestry, merged PR, or merge-tree content
   equivalence — never `--merged`/`git cherry` alone; squash merges blind them). No proof →
   report, don't delete.
3. Delete local and remote branches proven contained in default by the same ladder (skip
   protected/default branches and branches with an open PR).
4. `git worktree prune`; remove worktrees git marks `prunable` when they have no dirty files.
   Prune `autopilot/trash/*` tags older than 30 days.
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
