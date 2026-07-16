# CI Repair

Use this when an open PR or branch has failing GitHub checks.

## Flow

1. Confirm PR and credentials:

```bash
gh pr view --json number,url,headRefName,state
gh pr checks --json name,state,conclusion,workflow,link
```

2. For each failing check, open the linked run and read failing logs:

```bash
gh run view <run-id> --log-failed
```

3. Classify the failure:
   - Product/code regression: fix code and add/update tests when practical.
   - Test expectation drift: update the test only when the new behavior is intended and supported by the plan.
   - Environment/auth/dependency outage: retry once only when the failure is clearly transient; otherwise record a blocker.
   - Flake: identify the flaky boundary and harden it if bounded; do not loop blindly.
4. Commit and push focused fixes.
5. Watch checks again.

## Bounds

- Do not weaken assertions just to make CI green.
- Do not skip tests or disable workflows unless the plan explicitly requires that migration and the reason is documented.
- Stop after three fix iterations and record unresolved checks in the PR or final report.

## Evidence

Report failing check names, root cause, files changed, validation command, and final CI state.
