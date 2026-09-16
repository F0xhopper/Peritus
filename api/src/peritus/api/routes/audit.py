"""The audit surface: what this corpus is made of, and how it got that way.

Every route resolves the expert through the same read-scoped lookup the rest of
the API uses (``get_for_user``), so a private expert 404s for anyone but its
owner and a published one is auditable by anyone who can read it. That second
half is intentional: a public expert whose evidence trail were private would be
a claim without a receipt.

Read-only. Nothing here mutates a corpus.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from peritus.api.auth import AuthUser
from peritus.api.deps import Audits, CurrentUser, Pool, ReadableExpert
from peritus.api.schemas.audit import (
    AUDITS_PAGE_DEFAULT,
    AUDITS_PAGE_MAX,
    CONTRADICTIONS_PAGE_DEFAULT,
    CONTRADICTIONS_PAGE_MAX,
    EXPORT_MAX_ROWS,
    GRAPH_NODES_DEFAULT,
    GRAPH_NODES_MAX,
    SOURCES_PAGE_DEFAULT,
    SOURCES_PAGE_MAX,
    ExportFormat,
    SourceDecision,
    SourceSort,
)
from peritus.audit.export import (
    export_filename,
    sources_to_csv,
    sources_to_ris,
)
from peritus.audit.repository import AuditScope
from peritus.audit.service import (
    DEFAULT_EXCERPT_CHARS,
    DEFAULT_PASSAGES_PER_SIDE,
    MAX_EXCERPT_CHARS,
    MAX_PASSAGES_PER_SIDE,
)
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.search.readiness import get_readiness

logger = get_logger(__name__)

router = APIRouter(prefix="/experts", tags=["audit"])


def _audit_scope(expert: Expert, user: AuthUser) -> AuditScope:
    return AuditScope(
        caller_id=user.id,
        include_unowned=user.is_admin,
        owns_expert=expert.is_owned_by(user.id, include_unowned=user.is_admin),
    )


@router.get("/{slug}/corpus-report")
async def corpus_report(
    expert: ReadableExpert,
    audits: Audits,
    decision: SourceDecision = SourceDecision.ALL,
    sort: SourceSort = SourceSort.DECISION,
    limit: int = Query(SOURCES_PAGE_DEFAULT, ge=1, le=SOURCES_PAGE_MAX),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Every source this corpus was built from — and every source it rejected.

    Totals, score distributions and breakdowns are computed over the whole
    corpus, not over the returned page, so a paginated read still reports true
    numbers.
    """
    return await audits.corpus_report(
        expert, decision=decision.value, sort=sort.value, limit=limit, offset=offset
    )


@router.get("/{slug}/corpus-report/export")
async def corpus_report_export(
    expert: ReadableExpert,
    audits: Audits,
    format: ExportFormat = ExportFormat.CSV,
    decision: SourceDecision = SourceDecision.ALL,
) -> Response:
    """Download the screening ledger as CSV or RIS.

    RIS carries the sources into Covidence, Zotero and EndNote, which is what
    makes a grey-literature find usable in the review the reviewer is actually
    running. Both formats include rejected sources with their exclusion reason
    and the search that produced them.

    Exports are never partial: if a corpus somehow exceeds the runaway guard the
    request fails loudly rather than returning a file that looks complete.
    """
    rows, truncated = await audits.export_rows(expert, decision.value, EXPORT_MAX_ROWS)
    if truncated:
        raise HTTPException(
            status_code=507,
            detail=(
                f"This corpus has more than {EXPORT_MAX_ROWS} sources, above the "
                "export guard. A truncated ledger would misrepresent the search, "
                "so no file was produced — page through /corpus-report instead."
            ),
        )

    if format is ExportFormat.RIS:
        body = sources_to_ris(rows)
        media_type = "application/x-research-info-systems"
        extension = "ris"
    else:
        body = sources_to_csv(rows)
        media_type = "text/csv"
        extension = "csv"

    filename = export_filename(expert.name, decision.value, extension)
    return Response(
        content=body,
        media_type=f"{media_type}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Peritus-Export-Rows": str(len(rows)),
        },
    )


@router.get("/{slug}/screening-flow")
async def screening_flow(expert: ReadableExpert, audits: Audits) -> dict[str, Any]:
    """Counts through the funnel: identified → screened → retrieved → assessed → included.

    Pre-validation counts come from the build event log and are absent for
    experts that have none; validation onward comes from the corpus itself.
    Counts that nothing persists are returned as null with the reason, never as
    a zero or an estimate.
    """
    return await audits.screening_flow(expert)


@router.get("/{slug}/coverage")
async def coverage(expert: ReadableExpert, audits: Audits) -> dict[str, Any]:
    """Evidence strength per planned key concept — where the corpus is weak."""
    return await audits.coverage(expert)


@router.get("/{slug}/contradictions")
async def contradictions(
    expert: ReadableExpert,
    audits: Audits,
    pool: Pool,
    limit: int = Query(CONTRADICTIONS_PAGE_DEFAULT, ge=1, le=CONTRADICTIONS_PAGE_MAX),
    offset: int = Query(0, ge=0),
    passages_per_side: int = Query(DEFAULT_PASSAGES_PER_SIDE, ge=1, le=MAX_PASSAGES_PER_SIDE),
    excerpt_chars: int = Query(DEFAULT_EXCERPT_CHARS, ge=100, le=MAX_EXCERPT_CHARS),
) -> dict[str, Any]:
    """Where sources in this corpus were judged to disagree, resolved to passages.

    Each item carries both concept nodes and, for each side, the passages and
    source citations behind it — enough to render the disagreement without a
    second request.

    Check ``computed`` before reading ``contradictions``: it is ``false`` while
    the concept graph is still being extracted, and an empty list in that state
    means "not analysed yet", not "none found".
    """
    readiness = await get_readiness(pool, expert.id)
    return await audits.contradictions(
        expert,
        readiness,
        limit=limit,
        offset=offset,
        passages_per_side=passages_per_side,
        excerpt_chars=excerpt_chars,
    )


@router.get("/{slug}/graph")
async def graph(
    expert: ReadableExpert,
    audits: Audits,
    limit: int = Query(GRAPH_NODES_DEFAULT, ge=1, le=GRAPH_NODES_MAX),
) -> dict[str, Any]:
    """The concept graph as nodes and edges, for a force-directed rendering.

    Nodes are ranked by degree and capped at ``limit`` so a large corpus stays
    renderable; edges are returned only between the nodes in that cap.

    Check ``computed`` before reading ``nodes``/``edges``: it is ``false``
    while the concept graph is still being extracted.
    """
    return await audits.graph(expert, node_limit=limit)


@router.get("/{slug}/answer-audits")
async def list_answer_audits(
    expert: ReadableExpert,
    user: CurrentUser,
    audits: Audits,
    conversation_id: str | None = Query(None),
    limit: int = Query(AUDITS_PAGE_DEFAULT, ge=1, le=AUDITS_PAGE_MAX),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Retrieval trails for the caller's own answers from this expert.

    The durable half of the ``retrieval_audit`` event the chat stream emits, so
    an answer can still be accounted for long after its stream closed. Scoped
    to the caller's conversations (see ``AuditScope``): a trail carries the
    question, and a readable expert is not a licence to read other people's.
    """
    return await audits.list_answer_audits(
        expert,
        limit=limit,
        offset=offset,
        conversation_id=conversation_id,
        scope=_audit_scope(expert, user),
    )


@router.get("/{slug}/answer-audits/{audit_id}")
async def get_answer_audit(
    expert: ReadableExpert, audit_id: str, user: CurrentUser, audits: Audits
) -> dict[str, Any]:
    """One answer's full retrieval trail, with per-passage disposition."""
    try:
        audit = await audits.get_answer_audit(expert, audit_id, scope=_audit_scope(expert, user))
    except Exception as exc:  # malformed uuid reaches Postgres as a cast error
        logger.info("Answer audit lookup failed for %r/%r: %s", expert.name, audit_id, exc)
        raise HTTPException(status_code=404, detail="Answer audit not found") from exc
    if audit is None:
        raise HTTPException(status_code=404, detail="Answer audit not found")
    return audit
