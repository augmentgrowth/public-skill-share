# Repo Profiles

A repo profile is a per-repo (or per-client) override file that the SKILL.md router loads before doing anything network-facing in that repo. Profiles exist because a global autonomy contract cannot know:

- **Detection signals** — which paths, remote owners, or repo markers mean "this profile applies".
- **Credential expectations** — which GitHub account is allowed to write here (see `../credentials.md`).
- **Gates** — actions that are normally autonomous but user-gated in this repo (e.g. merge), or the reverse.
- **Automation coexistence** — if an automated sync process (cron/launchd/CI bot) owns default-branch content in this repo, the profile documents what the automation owns, what closeout owns, and how parked/queued branches get drained.

## How to add one

Create `references/profiles/<name>.md`, then add a routing row to `SKILL.md` (Routing Order + Route Table) keyed on the detection signals. Keep each profile short: signals, credentials, gates, and any repo-specific closeout steps.

## Example: `acme-client.md` (fictional)

```markdown
# Acme Client Repo Profile

Use this profile when the path, remote, or repo markers indicate Acme work.

## Detection Signals

- Path under `$HOME/code/acme/`.
- Remote owner `acme-corp`.
- Root `CLAUDE.md`/`AGENTS.md` names Acme-specific credentials or client boundaries.

If Acme and non-Acme signals conflict, stop before network writes.

## Credential Behavior

1. Read `../credentials.md`.
2. Use the Acme GitHub account only when `gh auth status` shows it is already
   authenticated. If it is missing, stop — do not push with the default
   account and do not log in.
3. After Acme writes, switch back to the default account.

## Gates

- Merge is user-gated on `acme-corp/billing-service` (regulated code path);
  everywhere else the standard Merge Policy applies.
- Never push Acme work to public or upstream remotes unless the remote is
  verified as the intended private/client destination.
- Do not commit client secrets, local OAuth tokens, downloaded exports, or
  generated private data.

## Automation Coexistence (if applicable)

An auto-sync job commits default-branch content in `acme-corp/docs` every
15 minutes. Implications:
- Never sweep its dirty files into a task commit; the sync owns them.
- Never leave the main checkout on a feature branch (the sync only runs on
  the default branch); do feature work in a worktree.
- Branches the sync parks for review are this profile's triage queue —
  drain it at every closeout, don't just flag it.

## Closeout Summary

Include: detection signal, account used, remote touched, PR/branch/CI
status, and whether the default identity was reinstated.
```
