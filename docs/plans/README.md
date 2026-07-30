# Archived implementation plans

These are the design briefs for features that have since **shipped**. They are
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

For where the product is going next, see [POSITIONING.md](../../POSITIONING.md).
