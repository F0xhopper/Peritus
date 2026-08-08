"""Persistence for experts.

**Two scoping clauses, and the difference is the security boundary.**

``_visibility_clause`` is the *ownership* clause: own rows, plus legacy
owner-less rows for admins. It answers "may this user MUTATE / does this row
belong to them". ``chat.conversation_repository`` imports it to scope
conversations, so it must never be widened — a conversation belongs to the user
who had it, not to everyone who can read the expert.

``_readable_clause`` is the *read* clause: ownership OR a shared visibility
(public/unlisted). It answers "may this user READ / CHAT WITH this expert".

Every query below is explicit about which one it uses. Listing the caller's
workspace uses ownership; the catalog is a separate query; ``get_for_user`` is
the read clause (so chat over public experts works), and mutating routes call
``get_owned_for_user`` instead.
"""

import dataclasses
import json

import asyncpg

from peritus.experts.domain import (
    SHARED_VISIBILITIES,
    CatalogMeta,
    Expert,
    ExpertConfig,
    ExpertStatus,
    ExpertTier,
    ExpertVisibility,
)

# Columns computed on list queries; kept here so catalog and workspace listings
# stay identical in shape.
_SOURCE_TYPE_COUNTS_SQL = """
    COALESCE(
        (SELECT jsonb_object_agg(source_type, cnt)
         FROM (
             SELECT source_type, COUNT(*)::int AS cnt
             FROM sources
             WHERE expert_id = e.id AND passed = true
             GROUP BY source_type
         ) sc),
        '{}'::jsonb
    ) AS source_type_counts
"""

# Catalog shelf order: featured first, then the founder's manual rank
# (un-ranked sorts last), then newest.
_CATALOG_ORDER = "e.is_featured DESC, e.catalog_rank ASC NULLS LAST, e.created_at DESC"


class ExpertRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(
        self,
        name: str,
        topic: str,
        tier: ExpertTier = ExpertTier.STANDARD,
        owner_id: str | None = None,
    ) -> Expert:
        config = ExpertConfig.from_tier(tier)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO experts (name, topic, status, tier, config, owner_id)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::uuid)
                RETURNING *
                """,
                name, topic, ExpertStatus.QUEUED.value,
                tier.value, json.dumps(dataclasses.asdict(config)), owner_id,
            )
        return _row_to_expert(row)

    async def get_by_id(self, expert_id: int) -> Expert | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM experts WHERE id = $1", expert_id)
        return _row_to_expert(row) if row else None

    async def get_by_name(self, name: str) -> Expert | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM experts WHERE lower(name) = lower($1)", name
            )
        return _row_to_expert(row) if row else None

    async def list_all(self) -> list[Expert]:
        """Every expert, unscoped. Local CLI / admin path only — never a request handler."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.*, {_SOURCE_TYPE_COUNTS_SQL}
                FROM experts e
                ORDER BY e.created_at DESC
                """
            )
        return [_row_to_expert(r) for r in rows]

    async def list_for_user(self, owner_id: str, include_unowned: bool) -> list[Expert]:
        """The caller's own workspace: their experts, plus legacy NULL-owned for admins.

        Deliberately OWNERSHIP-scoped, not read-scoped: ``GET /experts`` is "my
        experts", and quietly folding the whole public catalog into it would
        make every user's workspace grow whenever the founder publishes.
        The catalog is a separate endpoint (``list_catalog``).
        """
        clause, params = _visibility_clause(owner_id, include_unowned, alias="e", idx=1)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.*, {_SOURCE_TYPE_COUNTS_SQL}
                FROM experts e
                WHERE {clause}
                ORDER BY e.created_at DESC
                """,
                *params,
            )
        return [_row_to_expert(r) for r in rows]

    async def get_for_user(
        self, name: str, owner_id: str, include_unowned: bool
    ) -> Expert | None:
        """Get an expert by slug if the user may READ it.

        Read visibility = owned, or admin-visible legacy row, or shared
        (public/unlisted). This is what makes a catalog expert chattable by any
        signed-in user without touching the chat routes.

        **Do not use this to authorise a mutation** — use
        :meth:`get_owned_for_user`.
        """
        clause, params = _readable_clause(owner_id, include_unowned, alias="experts", idx=2)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM experts WHERE lower(name) = lower($1) AND {clause}",
                name, *params,
            )
        return _row_to_expert(row) if row else None

    async def get_owned_for_user(
        self, name: str, owner_id: str, include_unowned: bool
    ) -> Expert | None:
        """Get an expert by slug only if the user OWNS it.

        The authorisation gate for every mutating path: rebuild, cancel, delete,
        curate. A public expert is readable by everyone and mutable by nobody
        but its owner.
        """
        clause, params = _visibility_clause(owner_id, include_unowned, alias="experts", idx=2)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM experts WHERE lower(name) = lower($1) AND {clause}",
                name, *params,
            )
        return _row_to_expert(row) if row else None

    async def delete_for_user(
        self, name: str, owner_id: str, include_unowned: bool
    ) -> bool:
        """Delete an expert by slug if the user owns it. Returns True if a row went."""
        clause, params = _visibility_clause(owner_id, include_unowned, alias="experts", idx=2)
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM experts WHERE lower(name) = lower($1) AND {clause}",
                name, *params,
            )
        # asyncpg returns e.g. "DELETE 1"
        return result.rsplit(" ", 1)[-1] != "0"

    # ── public catalog ──────────────────────────────────────────────────────

    async def list_catalog(
        self,
        category: str | None = None,
        tag: str | None = None,
        featured_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Expert]:
        """The curated public shelf.

        Listed rows are ``visibility = 'public'`` AND answerable *right now* —
        i.e. readiness is chat_ready or graph_ready (migration 018), not job
        status. An expert is answerable a full stage before its build job ends,
        and the catalog's whole job is to have something warm to talk to; gating
        on job status would hide a usable expert for the length of graph
        extraction. Conversely a public expert being rebuilt drops out until its
        chunks are back, because ``reset_build_state`` returns it to 'pending'.
        """
        params: list = [limit, offset]
        filters = ["e.visibility = 'public'", "e.readiness <> 'pending'"]
        if category:
            params.append(category)
            filters.append(f"lower(e.category) = lower(${len(params)})")
        if tag:
            params.append(tag)
            filters.append(f"${len(params)} = ANY(e.tags)")
        if featured_only:
            filters.append("e.is_featured = true")

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.*, {_SOURCE_TYPE_COUNTS_SQL}
                FROM experts e
                WHERE {' AND '.join(filters)}
                ORDER BY {_CATALOG_ORDER}
                LIMIT $1 OFFSET $2
                """,
                *params,
            )
        return [_row_to_expert(r) for r in rows]

    async def get_public(self, name: str) -> Expert | None:
        """Fetch a shared (public or unlisted) expert by slug, with no user context.

        Backs the anonymous catalog detail endpoint. Unlisted rows resolve here
        too — that is the point of "unlisted": unguessable but shareable.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM experts
                WHERE lower(name) = lower($1) AND visibility = ANY($2::text[])
                """,
                name, sorted(SHARED_VISIBILITIES),
            )
        return _row_to_expert(row) if row else None

    async def list_catalog_categories(self) -> list[tuple[str, int]]:
        """Categories present in the public catalog, with counts, for facet chips."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT category, COUNT(*)::int AS n
                FROM experts
                WHERE visibility = 'public' AND readiness <> 'pending' AND category IS NOT NULL
                GROUP BY category
                ORDER BY n DESC, category ASC
                """
            )
        return [(r["category"], r["n"]) for r in rows]

    async def update_catalog(
        self,
        expert_id: int,
        *,
        visibility: ExpertVisibility | None = None,
        is_featured: bool | None = None,
        catalog_rank: int | None = None,
        blurb: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        published_by: str | None = None,
        clear: frozenset[str] = frozenset(),
    ) -> Expert | None:
        """Patch curation fields. ``None`` means "leave alone".

        To null a field out, name it in ``clear`` — otherwise there would be no
        way to remove a blurb or un-rank an expert.
        """
        sets: list[str] = []
        params: list = []

        def add(column: str, value) -> None:
            params.append(value)
            sets.append(f"{column} = ${len(params)}")

        if visibility is not None:
            add("visibility", visibility.value)
            if visibility is ExpertVisibility.PUBLIC:
                # First publish stamps provenance; re-publishing refreshes it.
                sets.append("published_at = NOW()")
                add("published_by", published_by)
            else:
                sets.append("published_at = NULL")
        if is_featured is not None:
            add("is_featured", is_featured)
        if catalog_rank is not None:
            add("catalog_rank", catalog_rank)
        elif "catalog_rank" in clear:
            sets.append("catalog_rank = NULL")
        if blurb is not None:
            add("blurb", blurb)
        elif "blurb" in clear:
            sets.append("blurb = NULL")
        if category is not None:
            add("category", category)
        elif "category" in clear:
            sets.append("category = NULL")
        if tags is not None:
            add("tags", tags)

        if not sets:
            return await self.get_by_id(expert_id)

        params.append(expert_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE experts SET {', '.join(sets)}, updated_at = NOW()
                WHERE id = ${len(params)}
                RETURNING *
                """,
                *params,
            )
        return _row_to_expert(row) if row else None

    async def update_status(
        self,
        expert_id: int,
        status: ExpertStatus,
        error: str | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experts
                SET status = $1, error = $2, updated_at = NOW()
                WHERE id = $3
                """,
                status.value, error, expert_id,
            )

    async def update_key_concepts(self, expert_id: int, key_concepts: list[str]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE experts SET key_concepts = $1::jsonb, updated_at = NOW() WHERE id = $2",
                json.dumps(key_concepts), expert_id,
            )

    async def update_counts(
        self,
        expert_id: int,
        source_count: int,
        chunk_count: int,
        node_count: int,
        edge_count: int,
        avg_quality: float | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experts
                SET source_count = $1, chunk_count = $2,
                    node_count = $3, edge_count = $4,
                    avg_quality = $5, updated_at = NOW()
                WHERE id = $6
                """,
                source_count, chunk_count, node_count, edge_count, avg_quality, expert_id,
            )

    async def update_persona(
        self,
        expert_id: int,
        persona_name: str,
        persona_bio: str,
        persona_style: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experts
                SET persona_name = $1, persona_bio = $2, persona_style = $3,
                    updated_at = NOW()
                WHERE id = $4
                """,
                persona_name, persona_bio, persona_style, expert_id,
            )

    async def update_config(self, expert_id: int, config: ExpertConfig) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE experts SET config = $1::jsonb, updated_at = NOW() WHERE id = $2",
                json.dumps(dataclasses.asdict(config)), expert_id,
            )

    async def update_tier(self, expert_id: int, tier: ExpertTier) -> None:
        """Move an expert to a new tier, with the config that tier implies.

        Tier and config travel together: the builder reads depth off
        ``expert.config``, so changing one without the other builds at a depth
        the row no longer claims.
        """
        config = ExpertConfig.from_tier(tier)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experts
                SET tier = $1, config = $2::jsonb, updated_at = NOW()
                WHERE id = $3
                """,
                tier.value, json.dumps(dataclasses.asdict(config)), expert_id,
            )

    async def reset_build_state(self, expert_id: int) -> None:
        """Clear derived corpus state so a (re)build starts from a clean slate.

        Builds are not checkpointed, so a retry re-runs the whole pipeline. Deleting
        the previous attempt's sources/chunks/graph first keeps a retry from creating
        duplicate rows. Child tables cascade from `sources`, but we delete each
        explicitly so this is correct regardless of FK cascade direction.

        **User-supplied sources survive.** Anything with
        ``discovered_via = 'upload'`` was handed over by the owner, not found by
        discovery, and in most cases cannot be found again — that is usually the
        reason it was uploaded. Wiping it on a rebuild would destroy the one part
        of the corpus the pipeline cannot reconstruct, so uploads and their
        chunks are kept and the rebuild adds discovery's findings around them.

        The concept graph is still wiped whole, because it is rebuilt whole and a
        node can be anchored in both uploaded and discovered chunks. The build's
        graph stage re-reads the surviving upload chunks, so they are back in the
        graph by the time it finishes.

        Readiness is reset here, inside the same transaction that wipes the
        corpus, rather than by the builder a moment later. Otherwise there is a
        window in which the expert advertises ``graph_ready`` while its chunks
        are already gone — and a public catalog expert being rebuilt would be
        offered to visitors with nothing behind it.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM expert_edges WHERE expert_id = $1", expert_id)
            await conn.execute("DELETE FROM expert_nodes WHERE expert_id = $1", expert_id)
            await conn.execute(
                """
                DELETE FROM source_chunks
                WHERE expert_id = $1 AND source_id IN (
                    SELECT id FROM sources
                    WHERE expert_id = $1
                      AND (discovered_via IS DISTINCT FROM 'upload')
                )
                """,
                expert_id,
            )
            await conn.execute(
                """
                DELETE FROM sources
                WHERE expert_id = $1 AND (discovered_via IS DISTINCT FROM 'upload')
                """,
                expert_id,
            )
            await conn.execute(
                """
                    UPDATE experts
                    SET source_count = (SELECT COUNT(*) FROM sources
                                        WHERE expert_id = $1 AND passed = true),
                        chunk_count = (SELECT COUNT(*) FROM source_chunks
                                       WHERE expert_id = $1),
                        node_count = 0, edge_count = 0,
                        avg_quality = NULL, error = NULL,
                        readiness = 'pending', chat_ready_at = NULL, graph_ready_at = NULL,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                expert_id,
            )

    async def delete(self, expert_id: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM experts WHERE id = $1", expert_id)

    async def fuzzy_find(self, query: str) -> Expert | None:
        """Find the closest expert by name using trigram similarity."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT *, similarity(lower(name), lower($1)) AS sim
                FROM experts
                ORDER BY sim DESC
                LIMIT 1
                """,
                query,
            )
        if row and row["sim"] > 0.1:
            return _row_to_expert(row)
        return None


def _visibility_clause(
    owner_id: str, include_unowned: bool, alias: str, idx: int
) -> tuple[str, list]:
    """OWNERSHIP clause: rows this user owns (plus legacy owner-less rows for admins).

    Regular users match only their own experts. Admins additionally match legacy
    experts with no owner (owner_id IS NULL) so nothing predating auth is orphaned.
    ``idx`` is the 1-based position of the owner_id parameter in the final query.

    **Do not widen this to include public experts.** It is shared with
    ``chat.conversation_repository`` to scope *conversations*, which are private
    to the user who had them even when the expert is public. Read access lives
    in :func:`_readable_clause` instead.
    """
    own = f"{alias}.owner_id = ${idx}::uuid"
    if include_unowned:
        return (f"({own} OR {alias}.owner_id IS NULL)", [owner_id])
    return (own, [owner_id])


def _readable_clause(
    owner_id: str, include_unowned: bool, alias: str, idx: int
) -> tuple[str, list]:
    """READ clause: ownership OR a shared visibility (public / unlisted).

    Used only for expert rows. A row matching this is readable and chattable;
    it is *not* necessarily mutable — see :func:`_visibility_clause`.
    """
    own, params = _visibility_clause(owner_id, include_unowned, alias, idx)
    shared = f"{alias}.visibility IN ('public', 'unlisted')"
    return (f"({own} OR {shared})", params)


def _row_to_expert(row: asyncpg.Record) -> Expert:
    # A set, not `row.keys()` directly: asyncpg returns a one-shot iterator
    # there, so the first `in` check that misses walks it to exhaustion and
    # every check after it reads False. That silently defaulted readiness,
    # tier, config, owner_id and visibility on every row — an expert with a
    # fully extracted concept graph came back as readiness='pending', which is
    # what made the graph view claim "not analysed yet" for every expert.
    keys = set(row.keys())

    # key_concepts stored as JSONB — decode from string if asyncpg doesn't auto-decode.
    _raw_concepts = row["key_concepts"] if "key_concepts" in keys else None
    if isinstance(_raw_concepts, str):
        _raw_concepts = json.loads(_raw_concepts)
    key_concepts: list[str] = list(_raw_concepts) if _raw_concepts else []

    # source_type_counts is a computed column present only in list_all queries.
    source_type_counts: dict[str, int] = {}
    if "source_type_counts" in keys and row["source_type_counts"]:
        raw = row["source_type_counts"]
        source_type_counts = dict(raw) if isinstance(raw, dict) else json.loads(raw)

    # Tier and config — fall back to STANDARD defaults for rows predating the migration.
    tier = ExpertTier(row["tier"]) if "tier" in keys and row["tier"] else ExpertTier.STANDARD

    raw_config = row["config"] if "config" in keys else None
    if isinstance(raw_config, str):
        raw_config = json.loads(raw_config)
    config = ExpertConfig(**raw_config) if raw_config else ExpertConfig.from_tier(tier)

    owner_id = row["owner_id"] if "owner_id" in keys and row["owner_id"] else None

    catalog = _row_to_catalog(row, keys)

    # Readiness comes from the row (migration 018); rows read before that
    # migration, or partial projections, fall back to 'pending'.
    readiness = row["readiness"] if "readiness" in keys and row["readiness"] else "pending"

    return Expert(
        id=row["id"],
        name=row["name"],
        topic=row["topic"],
        status=ExpertStatus(row["status"]),
        owner_id=str(owner_id) if owner_id else None,
        tier=tier,
        config=config,
        persona_name=row["persona_name"],
        persona_bio=row["persona_bio"],
        persona_style=row["persona_style"],
        source_count=row["source_count"],
        chunk_count=row["chunk_count"],
        node_count=row["node_count"],
        edge_count=row["edge_count"],
        avg_quality=row["avg_quality"],
        key_concepts=key_concepts,
        source_type_counts=source_type_counts,
        catalog=catalog,
        readiness=readiness,
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_catalog(row: asyncpg.Record, keys) -> CatalogMeta:
    """Build CatalogMeta, tolerating rows read before migration 015 was applied."""
    raw_visibility = row["visibility"] if "visibility" in keys else None
    try:
        visibility = ExpertVisibility(raw_visibility) if raw_visibility else ExpertVisibility.PRIVATE
    except ValueError:
        # An unrecognised value must never open a row up — fail closed.
        visibility = ExpertVisibility.PRIVATE

    raw_tags = row["tags"] if "tags" in keys else None
    published_by = row["published_by"] if "published_by" in keys else None

    return CatalogMeta(
        visibility=visibility,
        is_featured=bool(row["is_featured"]) if "is_featured" in keys else False,
        catalog_rank=row["catalog_rank"] if "catalog_rank" in keys else None,
        blurb=row["blurb"] if "blurb" in keys else None,
        category=row["category"] if "category" in keys else None,
        tags=list(raw_tags) if raw_tags else [],
        published_at=row["published_at"] if "published_at" in keys else None,
        published_by=str(published_by) if published_by else None,
    )
