# PR Owner

Use this when the user asks to ship, push, open/update a PR, or own an existing PR to mergeable.

## Entry Checks

1. Read `credentials.md` before network writes.
2. Read `safety-boundaries.md` if the tree has unrelated work.
3. Inspect:

```bash
git status --short
git branch --show-current
git remote -v
gh pr view --json number,url,title,state,mergeStateStatus,reviewDecision 2>/dev/null || true
```

## Preferred Engine (optional)

If you use the compound-engineering plugin, `compound-engineering:ce-commit-push-pr` handles normal commit, push, and PR creation/update — it already owns branch state, PR body composition, and push mechanics. Otherwise run those steps directly. Keep this reference for routing, preflight, and what to do after the PR exists.

## Ownership Loop

1. Protect unrelated dirty work. Stage only current-task paths.
2. Commit logical changes with repo-appropriate messages.
3. Push the branch and create or update the PR.
4. If CI exists, read `ci-repair.md` and watch/fix until green or blocked.
5. If review feedback exists, read `review-feedback.md` and address it.
6. Re-check mergeability.
7. Verify PR scope, not just mergeability: `git diff --stat origin/<default>...HEAD` (or `gh pr view --json files`) must contain only files intended for this task. A PR can be `CLEAN`/mergeable while polluted with unrelated auto-synced content. If unintended files appear, rebuild the branch from latest default with only the intended paths instead of merging as-is.
8. Apply the Merge Policy below — do not park a green PR waiting for a "merge" prompt.
9. After merge, delete the head branch and run the closeout hygiene sweep (`branch-hygiene.md`).
10. Summarize PR URL, CI state, review state, merge state, identity used, and residual blockers.

## Merge Policy

Owning a PR includes merging it. When ALL of these hold, merge without asking:

- CI is green (or the repo has no CI and focused checks passed).
- Scope is verified (step 7).
- No human reviewer has requested changes, and no unresolved `needs-human` review thread exists.
- The repo profile does not mark merge as user-gated, and no `do-not-merge`/`WIP`/draft marker is on the PR.

Use the repo's default merge method (`gh pr merge --squash --delete-branch` unless repo settings/history show merge commits are the norm). Close superseded duplicate PRs for the same feature with a linking comment.

Note: if an old recorded preference says "push/merge only when asked", treat it as superseded by the owner's current autonomy directive — do not resurrect it from memory or old session context. Client repos still merge autonomously when the above conditions hold; the extra care there is scope/boundary verification, not a merge prompt.

## Stop Conditions

- Missing authenticated account for the expected repo owner.
- Ambiguous remote/default branch.
- Force-push required, or deletion of an unmerged branch, without explicit authorization.
- Review comment is a product question, external communication, or asks for a tradeoff not covered by the plan.
- Merge would land on a protected branch that requires an approval the bot identity cannot provide.

For any other operational judgment call, apply `decision-policy.md` instead of asking.
