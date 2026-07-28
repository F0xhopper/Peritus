"""API contract tests for the audit surface.

DB and service are mocked so no infrastructure is required (style of
test_build_endpoint.py). What is being pinned here is the route contract the
frontend is built against: owner scoping, pagination bounds, the parameters
that are allowed to reach SQL, and the two states the contradictions endpoint
must never conflate.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier
from peritus.search.readiness import Readiness

ADMIN_ID = "00000000-0000-0000-0000-000000000000"


def _make_expert() -> Expert:
    return Expert(
        id=1,
        name="stoicism",
        topic="stoicism",
        status=ExpertStatus.READY,
        tier=ExpertTier.STANDARD,
        config=ExpertConfig.from_tier(ExpertTier.STANDARD),
        owner_id=ADMIN_ID,
        key_concepts=["virtue", "fate"],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def app():
    from peritus.api.app import create_app
    from peritus.api.auth import AuthUser, require_user

    app = create_app()
    app.dependency_overrides[require_user] = lambda: AuthUser(
        id=ADMIN_ID, email="admin@test", is_admin=True
    )
    return app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# Sentinel so `expert=None` can mean "the lookup finds nothing", distinct from
# "the caller did not specify an expert".
_UNSET = object()


def _patched(service=None, expert=_UNSET, readiness=Readiness.GRAPH_READY):
    """Patch the route module's pool, expert lookup, service and readiness."""
    mock_experts = AsyncMock()
    mock_experts.get_for_user = AsyncMock(
        return_value=_make_expert() if expert is _UNSET else expert
    )

    async def _get_readiness(_pool, _expert_id):
        return readiness

    return (
        patch("peritus.api.routes.audit.get_pool", return_value=MagicMock()),
        patch("peritus.api.routes.audit.ExpertRepository", return_value=mock_experts),
        patch("peritus.api.routes.audit.AuditService", return_value=service or AsyncMock()),
        patch("peritus.api.routes.audit.get_readiness", new=_get_readiness),
    )


ENDPOINTS = [
    "/experts/stoicism/corpus-report",
    "/experts/stoicism/screening-flow",
    "/experts/stoicism/coverage",
    "/experts/stoicism/contradictions",
    "/experts/stoicism/answer-audits",
]


# ── owner scoping ──

@pytest.mark.parametrize("path", [*ENDPOINTS, "/experts/stoicism/corpus-report/export"])
@pytest.mark.asyncio
async def test_unreadable_expert_404s_everywhere(client, path):
    """Out-of-scope rows 404 rather than 403, matching the experts routes: an
    expert's existence is not disclosed to someone who cannot read it."""
    p1, p2, p3, p4 = _patched(expert=None)
    with p1, p2, p3, p4:
        resp = await client.get(path)
    assert resp.status_code == 404


# ── corpus report ──

@pytest.mark.asyncio
async def test_corpus_report_defaults_to_the_whole_ledger(client):
    service = AsyncMock()
    service.corpus_report = AsyncMock(return_value={"sources": []})
    p1, p2, p3, p4 = _patched(service)
    with p1, p2, p3, p4:
        resp = await client.get("/experts/stoicism/corpus-report")

    assert resp.status_code == 200
    kwargs = service.corpus_report.await_args.kwargs
    assert kwargs["decision"] == "all"       # rejected sources included by default
    assert kwargs["sort"] == "decision"
    assert kwargs["limit"] == 100
    assert kwargs["offset"] == 0


@pytest.mark.asyncio
async def test_corpus_report_can_be_filtered_to_rejected_sources(client):
    service = AsyncMock()
    service.corpus_report = AsyncMock(return_value={"sources": []})
    p1, p2, p3, p4 = _patched(service)
    with p1, p2, p3, p4:
        resp = await client.get(
            "/experts/stoicism/corpus-report?decision=rejected&sort=quality&limit=5&offset=10"
        )

    assert resp.status_code == 200
    kwargs = service.corpus_report.await_args.kwargs
    assert kwargs["decision"] == "rejected"
    assert kwargs["sort"] == "quality"
    assert kwargs["limit"] == 5
    assert kwargs["offset"] == 10


@pytest.mark.parametrize(
    "query",
    [
        "decision=maybe",
        "sort=quality; DROP TABLE sources",
        "sort=s.id",
        "limit=0",
        "limit=99999",
        "offset=-1",
    ],
)
@pytest.mark.asyncio
async def test_corpus_report_rejects_out_of_contract_parameters(client, query):
    """Sort keys reach an ORDER BY fragment, so only the declared enum may pass."""
    p1, p2, p3, p4 = _patched()
    with p1, p2, p3, p4:
        resp = await client.get(f"/experts/stoicism/corpus-report?{query}")
    assert resp.status_code == 422


def test_declared_sorts_match_the_implemented_sql():
    from peritus.api.schemas.audit import SourceSort
    from peritus.audit.repository import SOURCE_SORTS

    assert {s.value for s in SourceSort} == set(SOURCE_SORTS)


# ── export ──

def _export_row(passed: bool) -> dict:
    return {
        "id": 1 if passed else 2,
        "passed": passed,
        "title": "On the shortness of life",
        "author": "Seneca",
        "url": "https://example.org/a",
        "source_type": "gutenberg",
        "content_type": "textbook",
        "difficulty": 3,
        "quality_score": 9.0 if passed else 2.0,
        "relevance_score": 9.0 if passed else 3.0,
        "drop_reason": None if passed else "off topic",
        "validator_model": "claude-haiku-4-5-20251001",
        "rubric_version": "v3-concepts-q5r6",
        "discovered_via": "plan" if passed else "gapfill:fate",
        "covered_concepts": '["virtue"]',
        "key_claims": '["Time is the only real possession"]',
        "chunk_count": 4,
        "created_at": datetime(2026, 7, 1, tzinfo=UTC),
    }


@pytest.mark.asyncio
async def test_csv_export_includes_rejected_rows_and_downloads(client):
    service = AsyncMock()
    service.export_rows = AsyncMock(
        return_value=([_export_row(True), _export_row(False)], False)
    )
    p1, p2, p3, p4 = _patched(service)
    with p1, p2, p3, p4:
        resp = await client.get("/experts/stoicism/corpus-report/export?format=csv")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment;" in resp.headers["content-disposition"]
    assert ".csv" in resp.headers["content-disposition"]
    assert resp.headers["x-peritus-export-rows"] == "2"
    body = resp.text
    assert "accepted" in body and "rejected" in body
    assert "off topic" in body
    assert "gapfill:fate" in body


@pytest.mark.asyncio
async def test_ris_export_is_importable_shaped(client):
    service = AsyncMock()
    service.export_rows = AsyncMock(return_value=([_export_row(True)], False))
    p1, p2, p3, p4 = _patched(service)
    with p1, p2, p3, p4:
        resp = await client.get("/experts/stoicism/corpus-report/export?format=ris")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-research-info-systems")
    assert ".ris" in resp.headers["content-disposition"]
    assert resp.text.startswith("TY  - BOOK")
    assert "ER  -" in resp.text


@pytest.mark.asyncio
async def test_truncated_export_fails_rather_than_returning_a_partial_ledger(client):
    """A ledger that silently stopped short would be cited as complete."""
    service = AsyncMock()
    service.export_rows = AsyncMock(return_value=([_export_row(True)], True))
    p1, p2, p3, p4 = _patched(service)
    with p1, p2, p3, p4:
        resp = await client.get("/experts/stoicism/corpus-report/export")
    assert resp.status_code == 507


# ── contradictions: "not computed" is not "none found" ──

@pytest.mark.asyncio
async def test_contradictions_are_not_computed_before_the_graph_exists(client):
    """The service must be told the readiness, and the real service returns a
    `computed: false` envelope rather than an empty list of findings."""
    from peritus.audit.service import AuditService

    real = AuditService(MagicMock())
    p1, p2, p3, p4 = _patched(real, readiness=Readiness.CHAT_READY)
    with p1, p2, p3, p4:
        resp = await client.get("/experts/stoicism/contradictions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["computed"] is False
    assert body["readiness"] == "chat_ready"
    assert body["contradictions"] == []
    assert body["summary"]["contradictions"] is None      # not 0
    assert "not looked for" in body["unavailable_reason"]


@pytest.mark.asyncio
async def test_contradictions_pass_readiness_and_paging_to_the_service(client):
    service = AsyncMock()
    service.contradictions = AsyncMock(return_value={"contradictions": []})
    p1, p2, p3, p4 = _patched(service, readiness=Readiness.GRAPH_READY)
    with p1, p2, p3, p4:
        resp = await client.get(
            "/experts/stoicism/contradictions?limit=5&offset=2&passages_per_side=4"
        )

    assert resp.status_code == 200
    args, kwargs = service.contradictions.await_args
    assert args[1] is Readiness.GRAPH_READY
    assert kwargs["limit"] == 5
    assert kwargs["offset"] == 2
    assert kwargs["passages_per_side"] == 4


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=1000", "passages_per_side=0", "passages_per_side=50",
              "excerpt_chars=1", "excerpt_chars=100000"]
)
@pytest.mark.asyncio
async def test_contradictions_bound_their_payload_parameters(client, query):
    p1, p2, p3, p4 = _patched()
    with p1, p2, p3, p4:
        resp = await client.get(f"/experts/stoicism/contradictions?{query}")
    assert resp.status_code == 422


# ── screening flow and coverage ──

@pytest.mark.asyncio
async def test_screening_flow_is_served(client):
    service = AsyncMock()
    service.screening_flow = AsyncMock(return_value={"stages": {}})
    p1, p2, p3, p4 = _patched(service)
    with p1, p2, p3, p4:
        resp = await client.get("/experts/stoicism/screening-flow")
    assert resp.status_code == 200
    service.screening_flow.assert_awaited_once()


@pytest.mark.asyncio
async def test_coverage_is_served(client):
    service = AsyncMock()
    service.coverage = AsyncMock(return_value={"concepts": []})
    p1, p2, p3, p4 = _patched(service)
    with p1, p2, p3, p4:
        resp = await client.get("/experts/stoicism/coverage")
    assert resp.status_code == 200
    service.coverage.assert_awaited_once()


# ── answer audits ──

@pytest.mark.asyncio
async def test_answer_audits_list_accepts_a_conversation_filter(client):
    service = AsyncMock()
    service.list_answer_audits = AsyncMock(return_value={"audits": []})
    p1, p2, p3, p4 = _patched(service)
    with p1, p2, p3, p4:
        resp = await client.get("/experts/stoicism/answer-audits?conversation_id=abc&limit=3")

    assert resp.status_code == 200
    kwargs = service.list_answer_audits.await_args.kwargs
    assert kwargs["conversation_id"] == "abc"
    assert kwargs["limit"] == 3


@pytest.mark.asyncio
async def test_unknown_answer_audit_404s(client):
    service = AsyncMock()
    service.get_answer_audit = AsyncMock(return_value=None)
    p1, p2, p3, p4 = _patched(service)
    with p1, p2, p3, p4:
        resp = await client.get("/experts/stoicism/answer-audits/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_malformed_audit_id_404s_rather_than_500s(client):
    """A non-uuid reaches Postgres as a cast error; it is a bad id, not a fault."""
    service = AsyncMock()
    service.get_answer_audit = AsyncMock(side_effect=ValueError("invalid input for uuid"))
    p1, p2, p3, p4 = _patched(service)
    with p1, p2, p3, p4:
        resp = await client.get("/experts/stoicism/answer-audits/not-a-uuid")
    assert resp.status_code == 404
