"""Auditable evidence synthesis — the provenance surface over a built corpus.

Peritus records, for every source it considered, how it was found, who scored
it, against which rubric, what it scored, and why it was kept or dropped. This
package is the read side of that record: the queries and service layer behind

    GET /experts/{slug}/corpus-report     every accepted AND rejected source
    GET /experts/{slug}/screening-flow    counts through the discovery funnel
    GET /experts/{slug}/coverage          evidence strength per key concept
    GET /experts/{slug}/contradictions    disagreements, resolved to passages
    GET /experts/{slug}/answer-audits     retrieval trail per answered question

plus the writer for the per-answer retrieval trail the chat stream emits.

Two rules run through the whole package:

**Never invent a number.** Where a count is not persisted, the response carries
``null`` and an ``unavailable_reason`` string saying why. Estimates, back-
calculations from other stages, and plausible-looking defaults are all worse
than an honest gap, because the point of this surface is to be defensible.

**This is first-pass screening plus an audit trail, not systematic-review
compliance.** An LLM does the screening; a human checks it. Nothing here
substitutes for two independent human reviewers, and no response claims it does.
"""

from peritus.audit.domain import (
    CoverageStrength,
    classify_coverage,
    parse_discovery_method,
)
from peritus.audit.service import AuditService

__all__ = [
    "AuditService",
    "CoverageStrength",
    "classify_coverage",
    "parse_discovery_method",
]
