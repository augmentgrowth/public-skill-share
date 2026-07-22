#!/usr/bin/env python3
"""Stop-hook closeout guard for the github-autopilot skill.

Fires when Claude finishes a turn. If the session's repo has uncommitted or
unpushed work, it blocks the stop ONCE per session+repo and tells Claude to
run github-autopilot closeout. Fail-open by design: any error, timeout, or
ambiguity allows the stop.

Registration — add to ~/.claude/settings.json:

    {
      "hooks": {
        "Stop": [
          {"hooks": [{
            "type": "command",
            "command": "python3 ~/.claude/skills/github-autopilot/scripts/stop-closeout-guard.py"
          }]}
        ]
      }
    }

Per-repo tuning via git config (no code changes needed):

    git config --local githubAutopilot.localOnly true
        Repo has no intended push target (no remote, or a deliberately
        fetch-only upstream). Only uncommitted work is flagged — a commit is
        the only safety net such a repo has.

    git config --local githubAutopilot.autoSynced true
        An automated sync process (cron/CI bot) owns default-branch content
        in this repo. On the default branch, dirty/unpushed checks are
        exempt (the automation owns them); on any other branch the guard
        flags that the checkout should return to the default branch so the
        automation can run.

Optional environment overrides:

    GH_AUTOPILOT_MARKER_DIR   once-per-session marker directory
                              (default: <tmpdir>/gh-autopilot-stop-guard)
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

MARKER_DIR = os.environ.get(
    "GH_AUTOPILOT_MARKER_DIR",
    os.path.join(tempfile.gettempdir(), "gh-autopilot-stop-guard"),
)


def sh(args, cwd):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=5)
        return r.returncode, r.stdout.strip()
    except Exception:
        return 1, ""


def truthy(value):
    return value.strip().lower() in ("true", "1", "yes")


def default_branch(top):
    # Explicit override wins (repos with trunk/other defaults and no origin/HEAD):
    #   git config --local githubAutopilot.defaultBranch trunk
    rc, cfg = sh(["git", "config", "--get", "githubAutopilot.defaultBranch"], top)
    if rc == 0 and cfg.strip():
        return cfg.strip()
    rc, ref = sh(["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], top)
    if rc == 0 and ref.startswith("origin/"):
        return ref[len("origin/"):]
    # No origin/HEAD (local-only repo, or never fetched): first existing
    # conventional default. show-ref pins to branches (a same-named tag
    # would satisfy plain rev-parse).
    for cand in ("main", "master", "develop"):
        rc, _ = sh(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{cand}"], top)
        if rc == 0:
            return cand
    return "main"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    # Loop guard: if we already blocked once and Claude continued, always allow.
    if data.get("stop_hook_active"):
        return
    cwd = data.get("cwd") or os.getcwd()
    if not os.path.isdir(cwd):
        return
    rc, top = sh(["git", "rev-parse", "--show-toplevel"], cwd)
    if rc != 0 or not top:
        return

    session = data.get("session_id", "nosession")
    key = hashlib.md5(f"{session}:{top}".encode()).hexdigest()
    marker = os.path.join(MARKER_DIR, key)
    if os.path.exists(marker):
        return

    _, branch = sh(["git", "branch", "--show-current"], top)
    _, auto_synced = sh(["git", "config", "--get", "githubAutopilot.autoSynced"], top)
    _, local_only = sh(["git", "config", "--get", "githubAutopilot.localOnly"], top)
    default = default_branch(top)
    issues = []

    if truthy(auto_synced) and branch == default:
        # The automation owns content on the default branch; nothing to demand.
        pass
    else:
        if truthy(auto_synced) and branch != default:
            issues.append(
                f"auto-synced repo checkout is on '{branch or 'DETACHED'}' — the sync process "
                f"only runs on '{default}'; return the checkout to '{default}' "
                "(feature work belongs in a worktree)"
            )
        rc, dirty = sh(["git", "status", "--porcelain"], top)
        if rc == 0 and dirty:
            issues.append(f"{len(dirty.splitlines())} uncommitted change(s)")
        # localOnly repos have no intended push target; unpushed is their
        # steady state, so only uncommitted work is worth surfacing there.
        if not truthy(local_only):
            rc, ahead = sh(["git", "rev-list", "--count", "@{u}..HEAD"], top)
            if rc == 0 and ahead and ahead != "0":
                issues.append(f"{ahead} unpushed commit(s) on '{branch or 'DETACHED'}'")
            elif rc != 0 and branch and branch not in ("main", "master", default):
                # An empty branch (no commits beyond default) is not stranded
                # work — scratch/worktree branches trip this constantly.
                rc2, ahead_def = sh(
                    ["git", "rev-list", "--count", f"{default}..HEAD"], top
                )
                if rc2 != 0 or (ahead_def and ahead_def != "0"):
                    issues.append(
                        f"branch '{branch}' has no upstream (work not on any remote)"
                    )

    if not issues:
        return

    os.makedirs(MARKER_DIR, exist_ok=True)
    with open(marker, "w") as f:
        f.write("1")

    reason = (
        f"github-autopilot closeout guard ({top}): " + "; ".join(issues) + ". "
        "Run the github-autopilot skill closeout now (commit current-task paths, push, PR, merge per its Merge Policy, hygiene sweep) — "
        "stage only files belonging to this session's task and report unrelated dirty work as preserved. "
        "If closeout genuinely doesn't apply (read-only session, user's own in-progress work, mid-plan state), say so briefly and stop. "
        "This guard fires once per session per repo."
    )
    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
