# Public Skill Share

**Claude Code skills from Augment Growth's working setup — shared as we harden them.**

[![skills.sh](https://skills.sh/b/augmentgrowth/public-skill-share)](https://skills.sh/augmentgrowth/public-skill-share)

These are sanitized, portable versions of skills we run in production on our own machines. Each one exists because a real failure mode kept recurring until we codified the fix.

## Install

**Option A — copy the skills in (editable):**

```bash
npx skills@latest add augmentgrowth/public-skill-share
```

Or manually: copy any `skills/<bucket>/<name>/` directory to `~/.claude/skills/<name>/`.

**Option B — Claude Code plugin (managed, auto-updating):**

```
/plugin marketplace add augmentgrowth/public-skill-share
/plugin install public-skill-share@augmentgrowth
```

Some skills have optional enforcement layers (hooks, scheduled scripts) that need one-time manual setup — each skill's README covers it.

## Why these skills exist

Agents are good at doing work and bad at *finishing* it. The recurring failure mode isn't wrong code — it's the trail of operational debt left behind: uncommitted changes, unpushed branches, green PRs nobody merged, orphaned branches and worktrees accumulating until a human notices. Every "commit", "push", "merge it", "clean that up" the user has to type is friction the agent created.

The fix is the same in every case: **codify the default, enforce it mechanically, and reserve the human for genuine decisions.**

## Reference

### Engineering

**Model-invoked** — Claude loads these itself when the state matches:

- [github-autopilot](skills/engineering/github-autopilot/SKILL.md) — owns GitHub closeout end-to-end, unprompted: commit → push → PR → CI green → review resolved → merged → branch deleted → hygiene sweep. Ships with a decision-policy table (act on codified defaults instead of asking option-menu questions), an optional Stop hook that blocks turn-end while work is unshipped, and an optional daily three-tier hygiene watchdog (deterministic bash → cheap model → strong model on escalation). [Full README](skills/engineering/github-autopilot/README.md).

## Layout

```
skills/
  engineering/   # promoted: daily engineering workflow skills
```

Promoted skills appear in this README and in the plugin manifest. Draft and personal skills stay out of both until they've survived real use.

## License

[MIT](LICENSE)
