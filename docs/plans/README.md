# Implementation plans

Most of these are the design briefs for features that have since **shipped**. They are
kept for the reasoning — why a thing was built the way it was, and what the
alternatives were — not as a description of the current system.

**Do not read these as documentation.** Where a plan and the code disagree, the
code is right. Several describe a starting state that no longer exists (the
dashboard plan opens by calling `web/` a stock `create-next-app` scaffold).

| Plan | Shipped as |
|------|-----------|
| [chat.md](chat.md) | Persisted conversations, stream claim/interrupt, chat UI — `api/src/peritus/chat/`, `web/components/chat/` |
| [answer-quality.md](answer-quality.md) | Query planning, asker-level shaping, grounded composition — `api/src/peritus/chat/agent.py`, `grounding.py` |
| [user-supplied-sources.md](user-supplied-sources.md) | PDF / text / URL upload into a live expert — `api/src/peritus/uploads/` |
| [dashboard.md](dashboard.md) | The Next.js dashboard and landing page — `web/` |

## Proposed, not shipped

| Plan | What it covers |
|------|----------------|
| [web-production.md](web-production.md) | The replacement production web app: every page, its purpose, data, states, recommended stack, backend gaps, and build order |
| [web-implementation.md](web-implementation.md) | How to build the web app: setup, auth/proxy layer, route handlers, types, streaming, data wiring, tests, deployment |
| [corpus-quality.md](corpus-quality.md) | A larger, better-screened corpus: screening measurement, source identity and dedup, full-text resolution, second-opinion validation, an iterating discovery loop with coverage targets, snowballing, and a cost-based budget |
