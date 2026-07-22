# Credential Routing

Read this before any GitHub network write: `git fetch`, `git push`, `gh pr`, branch deletion, release edits, or issue/PR mutation. Do not log in, create accounts, or print tokens.

This is a multi-account routing pattern. Fill in the identity table below with your own accounts; the discipline around it is fixed.

## Resolution Order

Choose the expected GitHub account from the first confident signal:

1. Repo profile override (a profile under `profiles/` names the expected identity).
2. Remote owner from `git remote get-url origin`.
3. Repo-local markers such as root instructions, package/project names, or client-specific paths.
4. Current active account only if it matches the expected owner.

If signals conflict, stop before network writes.

## Identity Table (template — fill in yours)

| Repo Signal | Expected Identity |
|---|---|
| Remote owner `<your-org>` or paths under `$HOME/code/<your-org>/` | `<default-account>` |
| Remote owner `<client-org>` or paths under `$HOME/code/<client-org>/` | `<client-account>` (only if already authenticated) |
| Anything else | stop and resolve authority first |

The exact account name must come from `gh auth status`; never guess from memory.

## Check and Switch

```bash
REMOTE_OWNER=$(git remote get-url origin 2>/dev/null | sed -E 's#\.git$##; s#.*[:/]([^/]+)/[^/]+$#\1#')
gh auth status 2>&1
```

Use `gh auth switch --hostname github.com --user <account>` only when `<account>` is already listed by `gh auth status`.

If no authenticated account matches the expected identity, stop with a credential blocker. Do not retry pushes against the wrong account. Never run `gh auth login` yourself, and never print or copy token values.

## Switch Back to Default

After repo-specific writes, switch back to your default account when it is authenticated. Make this a habit — a session that ends on a client identity poisons the next session's pushes. Report both the account used for the write and whether the default was reinstated.

## Summary Format

```text
GitHub identity: <previous> -> <used-for-repo> -> <default-reinstated|left-switched>
Reason: <path/remote/profile signal>
Network writes: <fetch/push/pr/edit/delete>
```
