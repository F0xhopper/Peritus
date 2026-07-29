"""The SQL hybrid search actually issues.

These assert on the *shape* of the generated statement rather than on results,
because the properties that matter here are planner properties and they are
invisible in the output: the ordering expression has to match the indexed
expression exactly, and the limit has to sit directly above the scan so an ANN
index can stop early. Both are silently lost by a plausible-looking edit, and
neither changes a single returned row when it is.

The plan itself is verified against Postgres 17 / pgvector 0.8 (index scan on
``idx_source_chunks_hnsw_halfvec`` with ``Limit`` as its direct parent); that
needs a database, so it is not repeated here.
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from peritus.search.service import SearchService, _distance_expr


class _FakeConn:
    """Records the statements and arguments the service issues."""

    def __init__(self) -> None:
        self.sql: str | None = None
        self.args: tuple = ()
        self.executed: list[str] = []
        self.in_transaction = False
        self.fetch_inside_transaction: bool | None = None

    async def fetch(self, sql, *args):
        self.sql = sql
        self.args = args
        self.fetch_inside_transaction = self.in_transaction
        return []

    async def execute(self, sql, *args):
        self.executed.append(sql)
        return "SET"

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                conn.in_transaction = True

            async def __aexit__(self, *exc):
                conn.in_transaction = False
                return False

        return _Tx()


def _pool_returning(conn: _FakeConn) -> MagicMock:
    pool = MagicMock()
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_cm)
    return pool


async def _capture_sql(*, halfvec: bool) -> _FakeConn:
    conn = _FakeConn()
    with patch("peritus.search.service.halfvec_supported", return_value=halfvec):
        await SearchService(_pool_returning(conn))._hybrid_search(
            expert_id=7,
            query_embedding=[0.1] * 8,
            query_text="stoic virtue",
            candidate_k=200,
            top_k=50,
        )
    assert conn.sql is not None
    return conn


# ── the distance expression ──


def test_distance_expr_uses_halfvec_when_available():
    with patch("peritus.search.service.halfvec_supported", return_value=True):
        column, param = _distance_expr()
    assert column == "sc.embedding::halfvec(3072)"
    # The parameter stays a `vector` — that is the codec registered on the
    # connection — and Postgres narrows it.
    assert param == "$1::vector(3072)::halfvec(3072)"


def test_distance_expr_falls_back_to_plain_vector():
    with patch("peritus.search.service.halfvec_supported", return_value=False):
        column, param = _distance_expr()
    assert (column, param) == ("sc.embedding", "$1")


def test_distance_expr_follows_configured_dimension():
    from peritus.core.config import settings

    with patch.object(settings, "EMBED_DIM", 1536), \
         patch("peritus.search.service.halfvec_supported", return_value=True):
        column, param = _distance_expr()
    assert "halfvec(1536)" in column
    assert "halfvec(1536)" in param


# ── the generated statement ──


@pytest.mark.parametrize("halfvec", [True, False])
async def test_order_by_matches_the_indexed_expression(halfvec):
    """ORDER BY must be byte-identical to the index's expression, or it is unused."""
    conn = await _capture_sql(halfvec=halfvec)
    with patch("peritus.search.service.halfvec_supported", return_value=halfvec):
        column, param = _distance_expr()

    assert f"ORDER BY {column} <=> {param}" in conn.sql


async def test_limit_is_the_direct_parent_of_the_vector_scan():
    """The candidate LIMIT must not sit above a window function.

    ``ROW_NUMBER() OVER (ORDER BY <distance>) … LIMIT k`` puts a WindowAgg
    between the limit and the scan, and a WindowAgg consumes its whole input —
    so the ANN index can no longer stop at k. Ranking has to happen in a wrapper
    over the already-limited subquery.
    """
    conn = await _capture_sql(halfvec=True)
    semantic = conn.sql[conn.sql.index("WITH semantic"):conn.sql.index("keyword AS")]

    # The distance ordering and the candidate LIMIT are in the inner subquery…
    inner = semantic[semantic.index("SELECT sc.id"):]
    assert "ORDER BY sc.embedding::halfvec" in inner
    assert "LIMIT $3" in inner
    # …and ROW_NUMBER is applied outside it, over `ranked`.
    row_number_pos = semantic.index("ROW_NUMBER()")
    assert row_number_pos < semantic.index("SELECT sc.id"), (
        "ROW_NUMBER must wrap the limited subquery, not sit inside it"
    )
    assert "FROM (" in semantic and "ranked" in semantic


async def test_keyword_arm_also_ranks_outside_its_limit():
    conn = await _capture_sql(halfvec=True)
    keyword = conn.sql[conn.sql.index("keyword AS"):conn.sql.index("fused AS")]

    assert "ROW_NUMBER() OVER (ORDER BY rank DESC)" in keyword
    assert "ORDER BY rank DESC" in keyword
    assert "LIMIT $3" in keyword
    assert "matched" in keyword


async def test_candidate_arms_project_ids_only():
    """Chunk text is fetched once, for the fused set — not hauled per candidate.

    The previous shape selected full text/context/meta for every semantic
    candidate and then discarded it to re-fetch the same columns in the outer
    query, at candidate_k rows per subquery and four to six subqueries a turn.

    The keyword arm still *references* ``sc.text`` inside ``to_tsvector`` — that
    is the index expression, and it produces a rank, not a returned column. What
    matters is that neither arm projects the wide columns, and neither joins
    ``sources``.
    """
    conn = await _capture_sql(halfvec=True)
    candidates = conn.sql[conn.sql.index("WITH semantic"):conn.sql.index("fused AS")]

    for column in ("sc.context_text", "sc.chunk_meta", "sc.sequence_n", "source_title"):
        assert column not in candidates, f"{column} is fetched per candidate"
    assert "JOIN sources" not in candidates, "candidate arms should not join sources"
    # sc.text appears only as the tsvector input, never as a projected column.
    assert "SELECT sc.id, sc.text" not in candidates
    assert candidates.count("sc.text") == 2  # to_tsvector in the SELECT and the WHERE

    # The wide columns are still selected once, at the end, for the fused ids.
    final = conn.sql[conn.sql.index("fused AS"):]
    assert "sc.context_text" in final
    assert "JOIN sources s ON s.id = sc.source_id" in final


async def test_null_embeddings_are_excluded_from_the_semantic_arm():
    """A chunk whose embedding failed has no place in a distance ranking, and
    HNSW does not index NULLs — so the filter keeps indexed and unindexed
    deployments returning the same rows."""
    conn = await _capture_sql(halfvec=True)
    assert "sc.embedding IS NOT NULL" in conn.sql


async def test_both_arms_are_scoped_to_the_expert():
    conn = await _capture_sql(halfvec=True)
    # $2 is expert_id; it must appear in the semantic and the keyword arm.
    candidates = conn.sql[conn.sql.index("WITH semantic"):conn.sql.index("fused AS")]
    assert len(re.findall(r"sc\.expert_id = \$2", candidates)) == 2


async def test_arguments_are_passed_positionally_in_order():
    conn = await _capture_sql(halfvec=True)
    embedding, expert_id, candidate_k, query_text, top_k = conn.args
    assert embedding == [0.1] * 8
    assert (expert_id, candidate_k, query_text, top_k) == (7, 200, "stoic virtue", 50)


# ── filtered-HNSW recall ──


async def test_iterative_scan_is_set_local_inside_the_query_transaction():
    """The correctness fix, and the reason it must be SET LOCAL.

    An HNSW index cannot carry the ``expert_id`` filter, so with the default
    ``hnsw.iterative_scan = off`` a filtered scan stops after one ef_search pass
    and silently returns however few rows survived — measured on this corpus at
    40 rows for an expert owning 184 chunks.

    Session-level ``SET`` cannot be relied on: DATABASE_URL points at a
    transaction pooler, which hands each transaction a different backend and
    resets session state between them. Only ``SET LOCAL``, in the same
    transaction as the query, is guaranteed to apply to it.
    """
    conn = await _capture_sql(halfvec=True)

    assert conn.executed == ["SET LOCAL hnsw.iterative_scan = relaxed_order"]
    assert conn.fetch_inside_transaction is True, (
        "SET LOCAL outside a transaction has no effect on the following query"
    )


async def test_iterative_scan_is_never_off():
    """`off` is the setting that truncates results; it must not be reachable."""
    from peritus.infrastructure.database import iterative_scan_sql

    assert "off" not in iterative_scan_sql(local=True)
    assert iterative_scan_sql(local=True).startswith("SET LOCAL ")
    assert iterative_scan_sql(local=False).startswith("SET hnsw")


async def test_invalid_iterative_scan_mode_falls_back_rather_than_injecting():
    """The GUC value is interpolated (a GUC name cannot be parameterised), so an
    environment-supplied value has to be allowlisted."""
    from peritus.core.config import settings
    from peritus.infrastructure.database import iterative_scan_sql

    with patch.object(settings, "HNSW_ITERATIVE_SCAN", "off; DROP TABLE source_chunks"):
        sql = iterative_scan_sql(local=True)

    assert sql == "SET LOCAL hnsw.iterative_scan = relaxed_order"
    assert "DROP" not in sql


async def test_no_transaction_overhead_without_an_index():
    """Deployments with no halfvec have no HNSW index, so there is nothing for
    iterative_scan to fix — they should not pay for a transaction."""
    conn = await _capture_sql(halfvec=False)

    assert conn.executed == []
    assert conn.fetch_inside_transaction is False


async def test_acquire_is_bounded():
    """An exhausted pool must fail the search, not queue behind it forever."""
    from peritus.core.config import settings

    conn = _FakeConn()
    pool = _pool_returning(conn)
    with patch("peritus.search.service.halfvec_supported", return_value=True):
        await SearchService(pool)._hybrid_search(
            expert_id=1, query_embedding=[0.1], query_text="q", candidate_k=10, top_k=5
        )

    pool.acquire.assert_called_once_with(timeout=settings.DB_ACQUIRE_TIMEOUT)
