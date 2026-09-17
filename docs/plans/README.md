# Implementation plans

Most of these are the design briefs for features that have since **shipped**. They are
kept for the reasoning — why a thing was built the way it was, and what the
alternatives were — not as a description of the current system.

**Do not read these as documentation.** Where a plan and the code disagree, the
code is right. Several describe a starting state that no longer exists.

| Plan | Shipped as |
|------|-----------|
| [chat.md](chat.md) | Persisted conversations, stream claim/interrupt — `api/src/peritus/chat/` |
| [answer-quality.md](answer-quality.md) | Query planning, asker-level shaping, grounded composition — `api/src/peritus/chat/agent.py`, `grounding.py` |
| [user-supplied-sources.md](user-supplied-sources.md) | PDF / text / URL upload into a live expert — `api/src/peritus/uploads/` |
| [source-selection.md](source-selection.md) | **Phases 0–6 and 7.A–7.B.** Screening ledger, fail-closed triage and a fetch floor, channel outcomes and retries, the Gutenberg catalogue, a canonical-work resolver, substance and composition caps, depth targets with a guaranteed round — `sources/triage.py`, `sources/canonical.py`, `experts/composition.py`, migration 029. Not built: 7.C (sections of long works); triage golden labels (human) |
| [syllabus.md](syllabus.md) | **Phases 0–4.** Resolver volumes kept through triage, no must-have boost for a work in hand, the text ceiling at the fetch boundary; an orientation pack read before planning; facets sized by tier and searched a facet at a time; figures with obtainable works, `not_obtainable` and substitutes, a thought-leader channel that looks for writing *by* people; graded concept tags and a named-text gate on "has primary" — `sources/orientation.py`, `sources/hosts.py`, `experts/coverage.py`, `sources/canonical.py`, migration 030. Not run: phase 5 (the measured rebuilds) |
| [expert-picture.md](expert-picture.md) | **Phase 1 only.** A found, licensed picture of the subject as each expert's default identity — `api/src/peritus/experts/picture.py`, `infrastructure/wikimedia.py`, migration 027, `web/components/identity/`. Phase 2 (model ranking, the candidate strip) and phase 3 (Commons/Openverse, the TUI credit, a public catalog endpoint) are not built |

## Proposed, not shipped

| Plan | What it covers |
|------|----------------|
| [web-production.md](web-production.md) | The production web app: every page, its purpose, data, states, the four rules, stack, backend gaps |
| [web-implementation.md](web-implementation.md) | How to build it: setup, auth/proxy layer, route handlers, types, streaming, data wiring, responsive and motion mechanics, tests, deployment, and the end-to-end flow in ten phases with a done-when check per phase (§13) |
| [web-design.md](web-design.md) | Look and feel: Obsidian-style shell, tokens, type, per-expert identity, the responsive tiers page by page (§8), and the motion catalogue (§9) |
| [corpus-quality.md](corpus-quality.md) | A larger, better-screened corpus: screening measurement, source identity and dedup, full-text resolution, second-opinion validation, an iterating discovery loop with coverage targets, snowballing, and a cost-based budget |
| [retrieval-quality.md](retrieval-quality.md) | Measured evaluation (2026-09-15) of how experts are built and used in chat: the 800-char passage cap, the dead keyword arm, junk chunks, a reconciler that has produced no edges, the corpus-wiping persona gate; thirteen ranked changes with per-turn token deltas |
| [overview-sidebar-review.md](overview-sidebar-review.md) | Design review (2026-09-16) of the expert Overview and the shell navigation — rail, expert sidebar, drawer, top bar — from code, real data and phone/tablet renders: eighteen findings, prioritised, with what not to change |
| [sources-chat-review.md](sources-chat-review.md) | Design review (2026-09-16) of the Sources page and the chat page — table, row detail, add/export, transcript, citations, passage panel, composer — from code, real data and phone/tablet renders: prioritised findings, with what not to change |
