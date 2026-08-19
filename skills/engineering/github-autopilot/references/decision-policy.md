# Decision Policy — Act, Don't Ask

Read this whenever you are about to ask the user an operational GitHub question. Most such questions have a codified default below. Asking is reserved for the narrow cases in "Still ask."

## The Rule

If every candidate action is reversible with local git evidence (reflog, remote branch, revert commit) and the decision is operational rather than product-level, pick the safest composite default, act, and report what you chose and why in the closeout summary. Do not present option menus for operational git states.

Rationale: agents chronically wait for the user to say "commit"/"merge"/"push" or arbitrate option menus for states that have one obviously safe answer. Those interjections are almost never corrections of a wrong autonomous choice — they are the agent failing to act. Codify the defaults instead; asking is the failure mode, not acting.

## Default Action Table

| Situation | Default action (no question) |
|---|---|
| Work finished, changes uncommitted | Commit current-task paths, push, open/update PR per `pr-owner.md`. Never wait for "commit". |
| PR green, scope verified, no human reviewer requested changes | Merge it and delete the head branch. See `pr-owner.md` Merge Policy. |
| An automated sync process swept an in-flight edit to the default branch before its PR | Revert it on the default branch, re-land it through the intended PR with the rest of the unit, and note the guard gap in the report (propose a fix as a follow-up item, don't block on it). |
| Local branch upstream is `[gone]` (remote merged/deleted) | Verify its commits are contained in default (`git branch --merged` / `git cherry`), then delete the local branch and prune. |
| Worktree marked `prunable`, no dirty files | `git worktree prune` / remove it. |
| Remote-only branch (no local counterpart) proven contained in default | Delete the remote branch. It is invisible to every local-keyed check, so nothing else will ever catch it. |
| Worktree holding a branch that is contained in default | Remove the worktree, then delete the branch. If the worktree is dirty, adjudicate each dirty path first (`branch-hygiene.md` → Adjudicating worktree dirt); never force past it, never leave it standing because of it. |
| `backup/*`/`archive/*`/`rescue/*` branch whose tip is already reachable from a tag on the remote | Delete the branch. The tag is the backup ref; the branch duplicates it. |
| `backup/*`/`archive/*`/`rescue/*` branch with unique content and no tag | Tag it at the tip with a message saying what it is and why it never merged, push, verify the tag resolves on the remote at the expected SHA, then delete the branch. Tagging is what makes this non-destructive — never delete first. |
| Open PR untouched 14+ days whose target path no longer exists on default | Close it with a comment naming the commit that retired the path and where the content lives now. Verify that preservation before closing; if the content exists nowhere else, the PR is unique work — leave it open and report. |
| PR merged but `git ls-remote --heads origin <branch>` still shows the ref | Delete the ref explicitly. `--delete-branch` fails independently of the merge; the flag is not proof. |
| A path an auto-sync process deliberately refuses to commit (an infra/secrets hold) sitting dirty | Branch, commit that path alone, open the PR, report the link. The hold exists to force review, so opening the PR satisfies it; do not merge it yourself. |
| Remote agent branch fully integrated into default | Delete the remote branch. |
| Duplicate PRs for the same feature (e.g. plan PR + impl PR) | Keep the implementation PR, close the superseded one with a comment linking to the survivor. |
| PR scope polluted with unrelated auto-synced files | Rebuild the branch from latest default with only intended paths (per `pr-owner.md` step 7). Don't ask which files belong — the task context defines them. |
| Dirty unrelated content at closeout in an auto-synced repo | Leave it; the sync process owns default-branch content there (see the repo profile). Report as preserved. |
| Feature branch ahead of remote with no upstream | Push with `-u` to origin under the same name. |
| Repo has no remote at all, or only a deliberately fetch-only upstream | Do NOT create a remote or push — where the code lives is the user's call. Commit locally, then mark it `git config --local githubAutopilot.localOnly true` so the Stop guard stops demanding a push. See "Local-only repos" below. |
| Merge conflict with recoverable intent on both sides | Resolve per `merge-conflicts.md` and continue. |
| A recorded old preference (e.g. "push/merge only when asked") conflicts with the owner's current autonomy directive | Follow the current directive and the repo profile, not the stale preference. |

## Local-only repos

Some repos are deliberately local: no remote, or an upstream that is fetch-only by design. For those, the safety net is the commit, not the push. Commit current-task work locally, set `githubAutopilot.localOnly true`, and report the repo as local-only rather than "unpushed".

## Still Ask (genuine stops)

- Force-push or history rewrite on a shared branch.
- Deleting branches/content whose commits are NOT contained anywhere else (unmerged, no backup ref).
- Product/business decisions: what behavior is correct, external communication, pricing/positioning content.
- Client repo boundary ambiguity (unknown remote owner, possible public exposure of client work).
- Credentials missing (never log in or create accounts).
- A repo profile explicitly marks an action as user-gated.

When you do ask, ask exactly one question with a recommended default, and bundle every related decision into it — never serial option menus.

## Report Instead of Ask

Every autonomous judgment call goes in the closeout report: what state was found, which default fired, what was done, and how to reverse it. This preempts "was everything pushed?" verification questions — the report must always answer: committed? pushed? PR? merged? branches cleaned? identity switched back?
