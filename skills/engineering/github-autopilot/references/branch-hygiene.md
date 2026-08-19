# Branch Hygiene

Use this for upstream setup, branch sync, stale branch inspection, agent branch integration, worktree cleanup, and the closeout hygiene sweep.

## Branch Preflight

```bash
git branch --show-current
git status --short
git branch -vv          # local branches
git branch -r           # remote-only branches — invisible to `-vv`, and they rot the longest
git remote -v
git worktree list
git fetch --prune
```

`git branch -vv` lists only local branches. A branch that exists solely on the remote — the
normal end state of a squash-merged PR whose delete half-failed, or of any branch created in
a worktree that has since gone — never appears there and is therefore invisible to any check
keyed on local state. **Enumerate both, always.**

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

**Containment is a claim about history, not about the current tree.** All three levels prove the
branch's commits are reachable from default — which is what makes deleting the *ref* lossless,
since the commits remain fetchable and the content recoverable from history. They do **not**
prove the content is still live at the same path today: it may have been moved, rewritten, or
deliberately deleted since, and a later revert leaves the original commits in history while
removing the content from the tree. That is fine for deletion (nothing is lost), but it means
containment alone never answers "does this content still exist on default?" — the question the
worktree-dirt and stale-PR rules ask. Those require a look at the current tree, not the ladder.

For deletions proven by level 2 or 3 (content, not ancestry), first drop a local recovery tag:
`git tag autopilot/trash/$(date +%Y%m%d)/<branch> <branch>`. Never push these tags; prune tags
older than 90 days during the hygiene sweep. The reflog is only a fallback (unreachable
entries can expire in ~30 days) — the tag is the guarantee, and 90 days is chosen to
outlive the reflog by a wide margin rather than expire alongside it. These are local refs
of a few dozen bytes covering the riskier deletion class (content-proven, not ancestry),
so a long window is close to free.

## Rules

- Feature work belongs on a meaningful branch. Do not commit directly to default unless the user explicitly authorized it (an automated sync process that owns default-branch content per a repo profile is the one standing exception).
- Preserve unrelated dirty work.
- Prefer rebase for local feature branches when no shared history rewrite is involved.
- Do not force-push without explicit authorization.
- A branch with no upstream that carries real work gets pushed with `-u`, not left stranded.

## Closeout Hygiene Sweep (mandatory)

Run this sweep as part of every closeout in the repo, without being asked. It is cheap, and without it `[gone]` branches, prunable worktrees, and month-old parked branches quietly accumulate across every repo you touch.

**Every ref reaches a terminal state.** The sweep's job is to *dispose*, not to *describe*.
A ref is terminal when it is deleted, or when it carries an open PR or unique unbacked work
that a named human decision now owns. "Listed in the report" is not terminal — it is the
same ref, still there, next closeout. **A report line that recurs unchanged across sessions
is a defect in this sweep, not a status update.** Contained branches, stale worktrees, dead
PRs, and held infra paths survive indefinitely when each has a report path and no disposal
path — the sweep inspects them every run and changes nothing.

1. `git fetch --prune`
2. Delete local branches whose upstream is `[gone]` after proving containment via the
   Containment Verification ladder above (ancestry, merged PR, or merge-tree content
   equivalence — never `--merged`/`git cherry` alone; squash merges blind them). No proof →
   report, don't delete.
3. Delete local and remote branches proven contained in default by the same ladder (skip
   protected/default branches and branches with an open PR).
   **Skip any branch checked out in a worktree** — `git worktree list` names them, the delete
   would fail anyway, and step 5 owns their full disposal including dirt adjudication.
   Deleting the *remote* half here while a worktree still holds the local branch is the
   subtle version of the same mistake: it destroys the branch's remote copy before its dirty
   files have been looked at. Leave both halves to step 5.
4. **Sweep remote-only branches.** Enumerate `git branch -r`, subtract the ones with a local
   counterpart already handled above, and run the same ladder on each remainder. This step
   exists because every other step keys on local state; without it a squash-merged branch
   whose delete half-failed is permanent debt. Delete each remote branch the ladder proves
   contained — `git push origin --delete <short-name>`.
   - **Carry two names, and never substitute one for the other.** `git branch -r` yields
     `origin/feat/foo`. Bind both forms up front:
     - `remote_ref=origin/feat/foo` — the remote-tracking ref. Use it for every **local**
       lookup: `git rev-parse $remote_ref`, `git merge-base --is-ancestor $remote_ref
       <default>`, `git merge-tree`. The ladder's SHA comparisons need this form; the short
       name does not resolve locally for a branch with no local counterpart.
     - `short_name=feat/foo` — the branch's real name on the remote. Use it for everything
       that talks to **the remote or GitHub**: `gh pr list --head $short_name`,
       `git push origin --delete $short_name`, `git push origin :refs/heads/$short_name`.

     Getting this backwards fails silently in both directions: `git rev-parse feat/foo`
     errors for a remote-only branch (so containment looks unprovable), and
     `gh pr list --head origin/feat/foo` matches nothing (so a merged PR looks absent). Both
     read as "no proof" and leave real debt in place.
5. **Free worktree-pinned branches.** A branch checked out in a worktree cannot be deleted
   while that worktree exists, and a worktree whose directory still exists is never
   `prunable` — so a merged branch held by a worktree is debt with no escape path. For each
   worktree other than the primary checkout, **complete the whole disposal here** (steps 2-4
   have already run; do not defer back to them):
   1. **Check liveness first — clean is not idle, and the window is deliberately wide.**
      A worktree belonging to a running session looks exactly like an abandoned one: no
      dirty files, branch possibly already merged, nothing in flight. It is simply between
      edits. Skip, and report as an active workspace, when **any** of these holds:

      - A running process has its working directory inside the worktree (on macOS/Linux,
        `lsof -a -d cwd +D <path>`). This is the only strong signal; when it is available
        and positive, skip regardless of age.
      - The worktree directory was modified in the **last 7 days**.
      - It sits under a harness-managed session root (`.claude/worktrees/`,
        `.codex/worktrees/`, or equivalent) and was modified in the **last 30 days**.

      **Do not tighten these windows.** The costs are wildly asymmetric: removing a live
      session's workspace breaks running work and is disruptive to recover from, while
      leaving a dead worktree one extra cycle costs nothing — the next sweep gets it.
      Modification time is a *weak* proxy for liveness: a session parked through a meeting,
      a long-running task, or a day of work in a parallel session is untouched but very much
      alive, and people routinely keep several sessions open for days. The windows above are
      sized for that reality, and they still catch real debt — the orphans that motivated
      this rule had been idle 27 to 70 days, so nothing tighter was ever buying anything.

      Harness-managed roots hold session workspaces the harness creates and is expected to
      reap. They remain disposable once genuinely stale, contained, and clean — a blanket
      exemption just recreates the never-disposed debt this sweep exists to prevent — but
      never force-remove one, and when the age is anywhere near the boundary, report instead
      of removing.
   2. Establish containment for its branch via the ladder above. A detached-HEAD worktree is
      contained when its HEAD commit is reachable from default.
   3. Not contained → leave the worktree alone and report it as active work. Stop.
   4. Contained and dirty → adjudicate every dirty path per *Adjudicating worktree dirt*
      before touching the worktree.
   5. Remove the worktree, then delete its branch (local and remote) in that order.
      **Worktree removal precedes branch deletion** — the reverse order simply fails with
      `branch is checked out at <path>`. A detached-HEAD worktree has no branch to delete:
      removing it is the whole disposal. Remove the now-empty worktree directory too if the
      tool leaves one behind.
6. `git worktree prune`; remove worktrees git marks `prunable` when they have no dirty files.
   Prune `autopilot/trash/*` tags older than 90 days.
7. In repos with an automated sync process, drain the parked agent-branch queue the repo profile defines.
8. **Dispose of timestamped `backup/*`, `archive/*`, `rescue/*` branches** via the ladder in
   *Disposing of preservation branches* below. These are not exempt from disposal — they are
   exempt from *unbacked* disposal.
9. **Sweep stale open PRs** per `pr-owner.md` → *Stale Open PR Sweep*.

Deleting a merged/contained branch is allowed regardless of who created it — containment in default is the safety property, not authorship.

### Adjudicating worktree dirt

Dirty files in an otherwise-disposable worktree are the one place real work hides. Do not
force-remove past them, and do not leave the worktree standing forever because of them.
For each dirty path, decide and record one of:

- **Already on default** (identical, or relocated identical) → drop it.
- **Superseded** — default's version is newer and subsumes it → drop it, naming what superseded it.
- **Unique** → land it before removing the worktree. Untracked new files can be copied over
  directly. Tracked modifications sitting on a stale base must be applied as a **three-way
  merge**, never a file copy: default may have moved many commits since, and a copy silently
  reverts all of it. If the apply conflicts, stop and resolve per hunk rather than taking
  either side wholesale.

**Then actually clear it — adjudication alone leaves the worktree dirty and unremovable.**

1. Save the state before touching anything, so every later step is recoverable even after the
   worktree is gone:

   ```bash
   scratch=$(mktemp -d)                                  # or the session's scratchpad dir
   name=$(basename <worktree>)                           # any stable label for this worktree
   git -C <worktree> diff > "$scratch/$name.patch"       # tracked modifications
   git -C <worktree> status --porcelain > "$scratch/$name.status"   # incl. untracked paths
   ```

   Report the `$scratch` path in the closeout ledger line for this worktree. It is a recovery
   aid, not an artifact to keep — the landed commits are the durable record, and the OS reclaims
   the directory on its own schedule.
2. For each path judged **unique**:
   - *Untracked new file* → copy it into the primary checkout, stage that one path, commit.
   - *Tracked modification* → apply the saved patch onto default with a three-way merge
     (`git apply --3way "$scratch/$name.patch"`). If it exits non-zero or `git ls-files -u`
     is non-empty, **stop and resolve per hunk** — read default's current version of each
     conflicting hunk and keep or drop it deliberately. Never resolve wholesale to either side.
   - Commit what landed, naming in the message which paths were dropped as superseded and why.
3. For paths judged already-on-default or superseded, nothing is landed — they are simply
   discarded with the worktree.
4. `git worktree remove --force <worktree>` — `--force` is correct here and only here: every
   dirty path has been adjudicated by name, so the flag discards nothing unexamined. Reaching
   for it *before* step 1 is the mistake this whole section exists to prevent.
5. `git worktree prune`, then delete the branch (step 5.4). Remove the leftover parent
   directory if the tool left an empty shell behind.

Landing work in step 2 does not invalidate the containment proof from step 5.1: that proof is
about the branch's *commits*, and these changes were never committed to it. They land on
default as new commits, which only strengthens containment.

### Disposing of preservation branches

`backup/*`, `archive/*`, `rescue/*` mean "someone wanted this recoverable" — which is a claim
about the *commits*, not about the *branch ref*. Once the commits are reachable from a tag,
the ref itself carries no value and deleting it loses nothing. Walk this in order:

1. **Contents already contained in default** (ladder above) → delete the branch. The
   preservation intent is satisfied by default itself.
2. **Tip already reachable from a tag on the remote** → delete the branch. The tag is the
   backup ref; the branch is a duplicate.
3. **Unique content, no tag** → create an annotated tag at the tip whose message says what the
   content is and why it was never merged, push the tag, **verify it resolves on the remote at
   the expected SHA**, and only then delete the branch. Tagging is what makes this
   non-destructive; the verify-before-delete ordering is the entire safety property.
4. **Cannot be tagged** (no push rights, remote unknown) → report once with age and a concrete
   recommendation, and record it per *Report-once items* below.

**Resolve what a remote tag actually points at — the two tag kinds differ.** An *annotated*
tag is its own object, so `git ls-remote --tags origin` prints two lines for it:
`refs/tags/<name>` (the tag object's SHA, which never equals the commit) and
`refs/tags/<name>^{}` (the commit it preserves). A *lightweight* tag prints one line, which
already is the commit. Comparing the wrong line fails in opposite ways: an annotated tag looks
like a mismatch, and a lightweight tag only matches by luck.

Take the peeled value when it exists, else the direct one:

```bash
# every tag on the remote, with what it ultimately points at
git ls-remote --tags origin

# for one candidate tag: peeled first, plain as fallback
tag_target=$(git ls-remote origin "refs/tags/<tag>^{}" | cut -f1)
[ -z "$tag_target" ] && tag_target=$(git ls-remote origin "refs/tags/<tag>" | cut -f1)

git rev-parse "$branch_ref"    # the tip that must match
```

Equal → the commits are preserved on the remote and the branch ref is redundant; delete it.
Neither lookup returns anything, or the values differ → **no proof; do not delete.**

`$branch_ref` is whichever form resolves locally for the branch in hand: the plain name for a
local branch (`backup/main-before-...`), or `origin/<name>` for a remote-only one. Preservation
branches are frequently local-only — a cron or a rescue script made them and never pushed — so
do not assume the `origin/`-prefixed form exists here.

To find whether *any* tag already covers a branch, compare its tip against the full
`git ls-remote --tags origin` listing rather than guessing at a tag name — the tag protecting
a branch is often named nothing like it.

Steps 1-3 are autonomous. This does not widen the destructive-action rule in
`safety-boundaries.md`: that rule stops deletion of commits **not contained anywhere else**,
and each of these paths establishes containment or a backup ref *before* the delete.

### Report-once items

A few refs genuinely cannot be disposed of autonomously — unique content that cannot be
tagged, or a decision that is the user's to make. "Report once" is only a terminal state if
something remembers the report; otherwise it is the same recurring line the sweep exists to
eliminate. Make it durable:

- Append one dated line to the repo's hygiene ledger (whatever file the repo profile names
  for autonomous-action history) recording the ref, its age, the specific decision needed,
  and the recommendation.
- On later sweeps, check the ledger first. An item already recorded is **not** re-raised in
  the report body — cite it in one line as still-open with its original date, so its age is
  visible without the noise of a fresh finding.
- When the user decides, act on it and record the outcome on the same line.

If the repo has no ledger and none can be created, say so explicitly in the report — an
undecidable item with nowhere to be recorded is a gap worth naming, not something to bury.

Name tags to match whatever convention the repo already uses (check `git tag -l` first);
absent one, `archive/<original-branch-name>` reads clearly next to the branches it replaces.

## Agent Branches

For agent branches (`claude/*`, `codex/*`, etc.), inspect before merging:

1. Branch name and age.
2. Commit list.
3. Changed file list.
4. Whether files are useful content, stale tooling, generated junk, or unrelated work.

Then integrate (merge/cherry-pick), preserve selectively, or skip with a stated reason — and delete the remote branch once integrated. Preserve useful content selectively; avoid whole-branch merges for stale archive/rescue branches.

## Summary

Report branches fetched, integrated, skipped, deleted (with containment evidence), worktrees pruned, and anything flagged for user disposal.

When the repo profile names a hygiene ledger, append one plain-English line per autonomous merge, branch deletion, or identity switch: `[YYYY-MM-DD] <repo>: <what and why>`. One file across all time — this is the "what did the robots do to my git" history.
