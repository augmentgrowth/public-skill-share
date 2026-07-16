# Merge and Rebase Conflicts

Use this when `git status` shows an active merge, rebase, cherry-pick, am, or apply conflict.

## Posture

Resolve the conflict when source intent is recoverable. Do not stop just because a conflict exists. Stop only when the decision is product-level, repo authority is unclear, or resolving would discard user work.

## Flow

1. Identify the operation:

```bash
git status
git diff --name-only --diff-filter=U
git branch --show-current
```

2. Recover both intents:
   - Read conflicted files.
   - Inspect local commits with `git log --oneline --decorate --graph --max-count=30`.
   - Inspect incoming branch commits when known.
   - Read PR, issue, or plan context when it explains why each side changed.
3. Resolve by preserving behavior from both sides when compatible.
4. Run focused checks for touched files. If no tests exist, run the smallest available static or structure check and record the exception.
5. Continue the operation:
   - `git merge --continue`
   - `git rebase --continue`
   - `git cherry-pick --continue`
6. Re-run `git status` and report the resolution, validation, and any residual risk.

## Conflict Rules

- Do not choose "ours" or "theirs" wholesale unless the other side is clearly stale generated output or duplicate content.
- Do not abort an operation started before the session unless resolution would be unsafe.
- Do not delete user-authored content to make a merge clean.
- For archive/rescue branches, prefer selective cherry-pick or manual preservation over whole-branch merge.

## Evidence to Report

- Conflicted files.
- Source intent for each side.
- Resolution choice.
- Check command and result.
- Operation completed or blocker.
