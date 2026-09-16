## What and why

<!-- What changed, and the problem it solves. If there is an issue, link it. -->

## How it was verified

<!-- Which of these actually ran, and what they said. Delete what does not apply. -->

- [ ] `just check` (ruff, mypy, pytest, eslint, tsc, vitest, next build)
- [ ] `just test-db` — if this touches the job queue, conversations, credits, uploads or visibility
- [ ] `just e2e-web` — if this touches the web UI
- [ ] Tried against a real build / real expert

## Anything a reviewer should know

<!-- Trade-offs taken, things deliberately left out, anything that needs a follow-up. -->

---

- [ ] Schema or response shape changed → clients and fixtures updated (`web/lib/api/types.ts`,
      `web/tests/fixtures/`, `cli/src/api/types.rs`)
- [ ] Migration added → numbered, forward-only, and backwards-compatible with the running code
- [ ] `api/pyproject.toml` changed → `uv lock` run and committed
- [ ] None of the seven invariants in [CONTRIBUTING.md](../CONTRIBUTING.md) is weakened
