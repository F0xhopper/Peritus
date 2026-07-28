"""Request-side schemas for the audit surface.

Responses are documented in ``docs/audit-api.md`` and assembled by
``peritus.audit.service``. They are deliberately returned as plain dicts rather
than Pydantic models: the payloads are deeply nested, several fields are
``value-or-null-plus-reason`` pairs, and a second declaration of that shape here
would be one more thing to drift out of step with the document the frontend is
built against. What IS declared here is everything a client sends — the values
that reach a query — because those must be validated before they reach SQL.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from peritus.audit.repository import SOURCE_SORTS


class SourceDecision(StrEnum):
    """Which half of the ledger to return.

    ``rejected`` is a first-class filter, not a debug view: the excluded
    sources are the evidence that the included ones were selected.
    """

    ALL = "all"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class SourceSort(StrEnum):
    """Ordering for the corpus report.

    Every member maps to a fixed ORDER BY fragment in
    ``audit.repository.SOURCE_SORTS``; nothing a client sends is ever
    interpolated into SQL. :func:`_assert_sorts_match` keeps the two in step.
    """

    DECISION = "decision"
    QUALITY = "quality"
    RELEVANCE = "relevance"
    TITLE = "title"
    TYPE = "type"
    DISCOVERED_VIA = "discovered_via"
    ADDED = "added"


def _assert_sorts_match() -> None:
    declared = {s.value for s in SourceSort}
    implemented = set(SOURCE_SORTS)
    if declared != implemented:
        raise RuntimeError(
            "SourceSort and audit.repository.SOURCE_SORTS have diverged: "
            f"{declared ^ implemented}"
        )


_assert_sorts_match()


class ExportFormat(StrEnum):
    """Ledger export formats.

    ``ris`` is the one that matters operationally: it is what Covidence, Zotero
    and EndNote import, so it is how a grey-literature source Peritus found
    reaches the review the user is actually running.
    """

    CSV = "csv"
    RIS = "ris"


# Paging limits. Corpus reports run to tens of sources today, but the endpoint
# must stay bounded for a large future build.
SOURCES_PAGE_DEFAULT = 100
SOURCES_PAGE_MAX = 500

CONTRADICTIONS_PAGE_DEFAULT = 25
CONTRADICTIONS_PAGE_MAX = 100

AUDITS_PAGE_DEFAULT = 25
AUDITS_PAGE_MAX = 100

# Runaway guard on exports. An export must be complete or refuse to be an
# export, so this sits far above any real corpus and the route reports a
# truncation rather than emitting a silently partial file.
EXPORT_MAX_ROWS = 20_000


class AuditPage(BaseModel):
    """Standard pagination echoed back on every paginated audit response."""

    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    returned: int
    total_matching: int | None
    has_more: bool
