# AGENTS.md — repo contract

How this repo is organized and the sync rules any agent editing it must follow.

## Layout

- `skills/<bucket>/<kebab-name>/SKILL.md` — one directory per skill. Current buckets: `engineering/` (promoted). Future non-promoted buckets (`in-progress/`, `deprecated/`) get no README/plugin entries.
- `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json` — the repo doubles as a single-plugin Claude Code marketplace.

## Sync rules (must hold after every change)

1. Every skill in a promoted bucket MUST appear in: the root `README.md` Reference section, and `plugin.json`'s `skills[]`. Non-promoted skills MUST NOT appear in either.
2. Keep `plugin.json` `version` bumped on any user-visible skill change — it is the plugin update signal. Record the change in the skill's own `CHANGELOG.md`.
3. Every skill declares its invocation mode: model-invoked (default) or user-invoked (`disable-model-invocation: true`). The README Reference section groups by that axis.
4. Run `claude plugin validate . --strict` (if available) after touching `.claude-plugin/`, and the skill's own `evals/run-checks.sh` after touching its routes.

## Sanitization contract (public repo)

Skills here are sanitized ports of private working skills. Before any commit: no personal absolute paths, no client or account names, no machine-specific labels, no secrets or token paths. Grep for leaks; do not rely on memory. Machine-specific behavior belongs behind env vars, `git config` flags (`githubAutopilot.*`), or repo-profile files the user writes themselves.
