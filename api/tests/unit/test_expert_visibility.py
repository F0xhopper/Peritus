"""Visibility and leak-prevention tests.

Two halves:

- Pure SQL-clause tests, which run everywhere. These pin the *shape* of the two
  scoping clauses, because the entire security story of the public catalog is
  "read is wide, mutate is narrow" and a one-word edit to either clause would
  silently break it.
- DB-backed tests against a real Postgres (skipped without
  ``PERITUS_TEST_DATABASE_URL``), which prove that publishing one expert does
  not expose another.
"""

import pytest

from peritus.experts.domain import (
    CatalogMeta,
    Expert,
    ExpertStatus,
    ExpertTier,
    ExpertVisibility,
)
from peritus.experts.repository import (
    ExpertRepository,
    _readable_clause,
    _visibility_clause,
)

OWNER = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


# ── clause shape (no DB) ────────────────────────────────────────────────────

def test_ownership_clause_never_matches_on_visibility():
    """The ownership clause is shared with conversations; widening it would leak
    every user's chat history on a public expert."""
    clause, params = _visibility_clause(OWNER, include_unowned=False, alias="e", idx=1)
    assert "visibility" not in clause
    assert "public" not in clause
    assert params == [OWNER]


def test_ownership_clause_admin_variant_still_ignores_visibility():
    clause, _ = _visibility_clause(OWNER, include_unowned=True, alias="e", idx=1)
    assert "owner_id IS NULL" in clause
    assert "visibility" not in clause


def test_readable_clause_adds_shared_visibilities_only():
    clause, params = _readable_clause(OWNER, include_unowned=False, alias="e", idx=1)
    assert "e.owner_id = $1::uuid" in clause
    assert "e.visibility IN ('public', 'unlisted')" in clause
    # 'private' must never appear as a matching value.
    assert "'private'" not in clause
    assert params == [OWNER]


def test_readable_clause_is_a_strict_superset_of_ownership():
    own, _ = _visibility_clause(OWNER, include_unowned=True, alias="e", idx=1)
    readable, _ = _readable_clause(OWNER, include_unowned=True, alias="e", idx=1)
    assert own in readable


# ── ownership predicate (no DB) ─────────────────────────────────────────────

def _expert(owner_id, visibility=ExpertVisibility.PRIVATE) -> Expert:
    return Expert(
        id=1,
        name="stoicism",
        topic="stoicism",
        status=ExpertStatus.READY,
        owner_id=owner_id,
        tier=ExpertTier.STANDARD,
        catalog=CatalogMeta(visibility=visibility),
        readiness="graph_ready",
    )


def test_public_expert_is_not_owned_by_a_reader():
    """The whole point: readable by everyone, mutable by its owner alone."""
    expert = _expert(OWNER, ExpertVisibility.PUBLIC)
    assert expert.is_owned_by(OWNER)
    assert not expert.is_owned_by(OTHER)
    assert not expert.is_owned_by(OTHER, include_unowned=True)


def test_legacy_unowned_expert_belongs_to_admins_only():
    expert = _expert(None)
    assert expert.is_owned_by(OTHER, include_unowned=True)
    assert not expert.is_owned_by(OTHER, include_unowned=False)


def test_readiness_gates_chattability_not_job_status():
    expert = _expert(OWNER, ExpertVisibility.PUBLIC)
    expert.readiness = "chat_ready"
    assert expert.is_chattable
    assert not expert.graph_expanded

    expert.readiness = "pending"
    assert not expert.is_chattable


def test_unrecognised_visibility_fails_closed():
    """A row carrying a value we don't understand must not be treated as public."""
    from peritus.experts.repository import _row_to_catalog

    row = {"visibility": "world-readable-lol", "tags": None}
    meta = _row_to_catalog(row, set(row))
    assert meta.visibility is ExpertVisibility.PRIVATE


# ── DB-backed leak checks ───────────────────────────────────────────────────

pytestmark_db = pytest.mark.asyncio


async def _seed(pool, name: str, owner: str | None, visibility: ExpertVisibility):
    repo = ExpertRepository(pool)
    expert = await repo.create(name=name, topic=name, tier=ExpertTier.LITE, owner_id=owner)
    # Catalog listing requires an answerable corpus, not a finished job.
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE experts SET readiness = 'graph_ready', status = 'ready' WHERE id = $1",
            expert.id,
        )
    if visibility is not ExpertVisibility.PRIVATE:
        await repo.update_catalog(expert.id, visibility=visibility, published_by=owner)
    return expert


@pytest.mark.asyncio
async def test_publishing_does_not_leak_other_private_experts(db_pool):
    repo = ExpertRepository(db_pool)
    await _seed(db_pool, "public-one", OWNER, ExpertVisibility.PUBLIC)
    await _seed(db_pool, "private-one", OWNER, ExpertVisibility.PRIVATE)
    await _seed(db_pool, "someone-elses-secret", OTHER, ExpertVisibility.PRIVATE)

    catalog = await repo.list_catalog()
    assert [e.name for e in catalog] == ["public-one"]

    # A stranger reads the public one and nothing else.
    assert await repo.get_for_user("public-one", OTHER, include_unowned=False) is not None
    assert await repo.get_for_user("private-one", OTHER, include_unowned=False) is None


@pytest.mark.asyncio
async def test_workspace_listing_excludes_the_catalog(db_pool):
    """`GET /experts` is "my experts" — it must not grow when someone publishes."""
    repo = ExpertRepository(db_pool)
    await _seed(db_pool, "someone-elses-public", OTHER, ExpertVisibility.PUBLIC)
    await _seed(db_pool, "mine", OWNER, ExpertVisibility.PRIVATE)

    mine = await repo.list_for_user(OWNER, include_unowned=False)
    assert [e.name for e in mine] == ["mine"]


@pytest.mark.asyncio
async def test_public_expert_is_readable_but_not_owned(db_pool):
    repo = ExpertRepository(db_pool)
    await _seed(db_pool, "shared", OWNER, ExpertVisibility.PUBLIC)

    # Readable by a stranger…
    assert await repo.get_for_user("shared", OTHER, include_unowned=False) is not None
    # …but not resolvable through the mutation gate, so rebuild/delete/curate 404.
    assert await repo.get_owned_for_user("shared", OTHER, include_unowned=False) is None
    assert await repo.get_owned_for_user("shared", OWNER, include_unowned=False) is not None
    # And the owner-scoped delete refuses too.
    assert await repo.delete_for_user("shared", OTHER, include_unowned=False) is False


@pytest.mark.asyncio
async def test_unlisted_is_reachable_by_slug_but_absent_from_the_shelf(db_pool):
    repo = ExpertRepository(db_pool)
    await _seed(db_pool, "quiet", OWNER, ExpertVisibility.UNLISTED)

    assert [e.name for e in await repo.list_catalog()] == []
    assert await repo.get_public("quiet") is not None
    assert await repo.get_for_user("quiet", OTHER, include_unowned=False) is not None


@pytest.mark.asyncio
async def test_private_expert_is_not_reachable_anonymously(db_pool):
    await _seed(db_pool, "secret", OWNER, ExpertVisibility.PRIVATE)
    assert await ExpertRepository(db_pool).get_public("secret") is None


@pytest.mark.asyncio
async def test_catalog_order_is_featured_then_rank_then_recency(db_pool):
    repo = ExpertRepository(db_pool)
    for name in ("alpha", "beta", "gamma"):
        await _seed(db_pool, name, OWNER, ExpertVisibility.PUBLIC)

    gamma = await repo.get_by_name("gamma")
    beta = await repo.get_by_name("beta")
    await repo.update_catalog(gamma.id, is_featured=True)
    await repo.update_catalog(beta.id, catalog_rank=1)

    assert [e.name for e in await repo.list_catalog()][:2] == ["gamma", "beta"]


@pytest.mark.asyncio
async def test_catalog_filters_by_category_and_tag(db_pool):
    repo = ExpertRepository(db_pool)
    a = await _seed(db_pool, "med", OWNER, ExpertVisibility.PUBLIC)
    b = await _seed(db_pool, "phil", OWNER, ExpertVisibility.PUBLIC)
    await repo.update_catalog(a.id, category="Medicine", tags=["oncology", "review"])
    await repo.update_catalog(b.id, category="Philosophy", tags=["ethics"])

    assert [e.name for e in await repo.list_catalog(category="medicine")] == ["med"]
    assert [e.name for e in await repo.list_catalog(tag="ethics")] == ["phil"]
    assert dict(await repo.list_catalog_categories()) == {"Medicine": 1, "Philosophy": 1}


@pytest.mark.asyncio
async def test_rebuild_drops_a_public_expert_off_the_shelf(db_pool):
    """A public expert being rebuilt must not be offered with no corpus behind it."""
    repo = ExpertRepository(db_pool)
    expert = await _seed(db_pool, "rebuilding", OWNER, ExpertVisibility.PUBLIC)
    assert len(await repo.list_catalog()) == 1

    await repo.reset_build_state(expert.id)

    assert await repo.list_catalog() == []
    # Still public — it comes back when the rebuild reaches chat_ready.
    reloaded = await repo.get_by_id(expert.id)
    assert reloaded.catalog.visibility is ExpertVisibility.PUBLIC
    assert reloaded.readiness == "pending"


@pytest.mark.asyncio
async def test_unpublish_keeps_curation_but_hides_the_expert(db_pool):
    repo = ExpertRepository(db_pool)
    expert = await _seed(db_pool, "onoff", OWNER, ExpertVisibility.PUBLIC)
    await repo.update_catalog(expert.id, blurb="A good one", category="Philosophy")

    await repo.update_catalog(expert.id, visibility=ExpertVisibility.PRIVATE)

    reloaded = await repo.get_by_id(expert.id)
    assert reloaded.catalog.visibility is ExpertVisibility.PRIVATE
    assert reloaded.catalog.blurb == "A good one"      # re-publishing is one command
    assert reloaded.catalog.published_at is None
    assert await repo.list_catalog() == []


@pytest.mark.asyncio
async def test_clear_nulls_a_field_that_omission_would_preserve(db_pool):
    repo = ExpertRepository(db_pool)
    expert = await _seed(db_pool, "clearable", OWNER, ExpertVisibility.PUBLIC)
    await repo.update_catalog(expert.id, blurb="temporary", catalog_rank=5)

    await repo.update_catalog(expert.id, clear=frozenset({"blurb", "catalog_rank"}))

    reloaded = await repo.get_by_id(expert.id)
    assert reloaded.catalog.blurb is None
    assert reloaded.catalog.catalog_rank is None
