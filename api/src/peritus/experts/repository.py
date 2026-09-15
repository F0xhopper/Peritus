"""Persistence for experts.

**Two scoping clauses, and the difference is the security boundary.**

``_visibility_clause`` is the *ownership* clause: own rows, plus legacy
owner-less rows for admins. It answers "may this user MUTATE / does this row
belong to them". ``chat.conversation_repository`` imports it to scope
conversations, so it must never be widened — a conversation belongs to the user
who had it, not to everyone who can read the expert.

``_readable_clause`` is the *read* clause: ownership OR public OR a grant on a
live share link (migration 031). It answers "may this user READ / CHAT WITH
this expert".

Every query below is explicit about which one it uses. Listing the caller's
workspace uses ownership plus grants; the catalog is a separate query;
``get_for_user`` is the read clause (so chat over public and shared experts
works), and mutating routes call ``get_owned_for_user`` instead.
"""

import dataclasses
import json

import asyncpg

from peritus.experts.domain import (
    CatalogMeta,
    Expert,
    ExpertConfig,
    ExpertStatus,
    ExpertTier,
    ExpertVisibility,
)
from peritus.experts.picture_repository import (
    PICTURE_JOIN_COLUMNS,
    picture_join,
    row_to_picture,
)

# Computed on every query a client renders an expert from — the listings *and*
# the single-expert reads (Overview's "Source types" section reads it). Kept here
# so catalog and workspace shapes stay identical.
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

# Whether a build job for this expert is actually queued or running. The
# expert's own `status` column can say 'queued' long after its job is gone (a
# job deleted, or a row written outside the queue), and a client that trusts it
# shows a live "building" counter over a working expert indefinitely.
_BUILD_ACTIVE_SQL = """
    EXISTS (
        SELECT 1 FROM build_jobs j
        WHERE j.expert_id = e.id AND j.status IN ('queued', 'running')
    ) AS build_active
"""

# The found picture (migration 027), joined onto every query whose result a
# client renders an avatar from. Metadata only — `image` is never selected here;
# the blob has its own repository and exactly one endpoint that reads it.
_PICTURE_SQL = PICTURE_JOIN_COLUMNS
_PICTURE_JOIN = picture_join("e")


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
            row = await conn.fetchrow(
                f"""
                SELECT e.*, {_PICTURE_SQL}
                FROM experts e {_PICTURE_JOIN}
                WHERE e.id = $1
                """,
                expert_id,
            )
        return _row_to_expert(row) if row else None

    async def get_by_name(self, name: str) -> Expert | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT e.*, {_PICTURE_SQL}
                FROM experts e {_PICTURE_JOIN}
                WHERE lower(e.name) = lower($1)
                """,
                name,
            )
        return _row_to_expert(row) if row else None

    async def list_all(self) -> list[Expert]:
        """Every expert, unscoped. Local CLI / admin path only — never a request handler."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.*, {_SOURCE_TYPE_COUNTS_SQL}, {_BUILD_ACTIVE_SQL}, {_PICTURE_SQL}
                FROM experts e {_PICTURE_JOIN}
                ORDER BY e.created_at DESC
                """
            )
        return [_row_to_expert(r) for r in rows]

    async def list_for_user(self, owner_id: str, include_unowned: bool) -> list[Expert]:
        """The caller's workspace: their experts (plus legacy NULL-owned for
        admins) and the experts shared with them through a live link.

        Ownership plus grants, never the whole read clause: ``GET /experts`` is
        "my experts", and quietly folding the public catalog into it would make
        every user's workspace grow whenever the founder publishes. A grant is
        different — the caller opened that link on purpose. The catalog is a
        separate endpoint (``list_catalog``).
        """
        clause, params = _visibility_clause(owner_id, include_unowned, alias="e", idx=1)
        granted = _granted_clause(alias="e", idx=1)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.*, {_SOURCE_TYPE_COUNTS_SQL}, {_BUILD_ACTIVE_SQL}, {_PICTURE_SQL}
                FROM experts e {_PICTURE_JOIN}
                WHERE {clause} OR {granted}
                ORDER BY e.created_at DESC
                """,
                *params,
            )
        return [_row_to_expert(r) for r in rows]

    async def get_for_user(
        self, name: str, owner_id: str, include_unowned: bool
    ) -> Expert | None:
        """Get an expert by slug if the user may READ it.

        Read visibility = owned, or admin-visible legacy row, or public, or
        shared with this user through a live link. This is what makes a catalog
        or shared expert chattable without touching the chat routes.

        **Do not use this to authorise a mutation** — use
        :meth:`get_owned_for_user`.
        """
        clause, params = _readable_clause(owner_id, include_unowned, alias="e", idx=2)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT e.*, {_SOURCE_TYPE_COUNTS_SQL}, {_BUILD_ACTIVE_SQL}, {_PICTURE_SQL}
                FROM experts e {_PICTURE_JOIN}
                WHERE lower(e.name) = lower($1) AND {clause}
                """,
                name, *params,
            )
        return _row_to_expert(row) if row else None

    async def is_readable_by(
        self, expert_id: int, owner_id: str, include_unowned: bool
    ) -> bool:
        """Whether the user may still READ this expert, by id.

        For paths that reach an expert through something the user owns — a
        conversation — and must notice that the share behind it was revoked.
        """
        clause, params = _readable_clause(owner_id, include_unowned, alias="e", idx=2)
        async with self._pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    f"SELECT EXISTS (SELECT 1 FROM experts e WHERE e.id = $1 AND {clause})",
                    expert_id, *params,
                )
            )

    async def get_by_share_token(self, token: str) -> Expert | None:
        """The expert behind a *live* share link, with no user context.

        Backs the anonymous share page. A revoked or unknown token is None, so a
        link that was turned off or reset stops rendering immediately.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT e.*, {_SOURCE_TYPE_COUNTS_SQL}, {_BUILD_ACTIVE_SQL}, {_PICTURE_SQL}
                FROM expert_share_links l
                JOIN experts e ON e.id = l.expert_id
                {_PICTURE_JOIN}
                WHERE l.token = $1 AND l.revoked_at IS NULL
                """,
                token,
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
        clause, params = _visibility_clause(owner_id, include_unowned, alias="e", idx=2)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT e.*, {_PICTURE_SQL}
                FROM experts e {_PICTURE_JOIN}
                WHERE lower(e.name) = lower($1) AND {clause}
                """,
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
                SELECT e.*, {_SOURCE_TYPE_COUNTS_SQL}, {_BUILD_ACTIVE_SQL}, {_PICTURE_SQL}
                FROM experts e {_PICTURE_JOIN}
                WHERE {' AND '.join(filters)}
                ORDER BY {_CATALOG_ORDER}
                LIMIT $1 OFFSET $2
                """,
                *params,
            )
        return [_row_to_expert(r) for r in rows]

    async def get_public(self, name: str) -> Expert | None:
        """Fetch a public expert by slug, with no user context.

        Backs the anonymous catalog detail endpoint. Public only: a private
        expert — shared by link or not — never resolves by slug, because a slug
        is derived from the topic and is therefore guessable.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT e.*, {_SOURCE_TYPE_COUNTS_SQL}, {_BUILD_ACTIVE_SQL}, {_PICTURE_SQL}
                FROM experts e {_PICTURE_JOIN}
                WHERE lower(e.name) = lower($1) AND e.visibility = 'public'
                """,
                name,
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
                RETURNING id
                """,
                *params,
            )
        # Re-read rather than RETURNING *: the response carries the joined
        # picture, and an UPDATE cannot return a column it did not touch.
        return await self.get_by_id(row["id"]) if row else None

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

    async def update_build_summary(self, expert_id: int, summary: dict) -> None:
        """Record what the discovery loop did and why it stopped.

        Written as soon as discovery finishes rather than at the end of the
        build, so a build that later fails in graph extraction still leaves
        behind the account of how its corpus was assembled.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE experts SET build_summary = $1::jsonb, updated_at = NOW() WHERE id = $2",
                json.dumps(summary), expert_id,
            )

    async def update_research_plan(self, expert_id: int, plan: dict) -> None:
        """Store the normalised research plan. A rebuild overwrites it."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE experts SET research_plan = $1::jsonb, updated_at = NOW() WHERE id = $2",
                json.dumps(plan), expert_id,
            )

    async def clear_candidate_screenings(self, expert_id: int, job_id: int | None) -> None:
        """Forget a previous attempt's ledger for this job before a new one writes.

        A retried job re-runs discovery from nothing, and two attempts' rows under
        one job would double every count the ledger exists to answer.
        """
        async with self._pool.acquire() as conn:
            if job_id is None:
                await conn.execute(
                    "DELETE FROM candidate_screenings WHERE expert_id = $1 AND job_id IS NULL",
                    expert_id,
                )
            else:
                await conn.execute(
                    "DELETE FROM candidate_screenings WHERE job_id = $1", job_id,
                )

    async def insert_candidate_screenings(
        self, expert_id: int, job_id: int | None, rows: list[dict]
    ) -> None:
        """One round's screening ledger, in one transaction."""
        if not rows:
            return
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                """
                INSERT INTO candidate_screenings
                    (job_id, expert_id, round, source_type, url, title, author, snippet,
                     discovered_via, model_score, domain_adjustment, triage_score,
                     triage_status, fetch_rank, fetch_outcome)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                """,
                [
                    (
                        job_id, expert_id, r["round"], r["source_type"], r["url"],
                        r["title"][:1000], r.get("author"), r.get("snippet") or "",
                        r["discovered_via"], r["model_score"], r["domain_adjustment"],
                        r["triage_score"], r["triage_status"], r["fetch_rank"],
                        r["fetch_outcome"],
                    )
                    for r in rows
                ],
            )

    async def candidate_screenings(self, job_id: int) -> list[dict]:
        """Every candidate one job's triage saw, in round and fetch order."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT cs.*, s.passed, s.relevance_score, s.source_tier, s.drop_reason
                FROM candidate_screenings cs
                LEFT JOIN sources s ON s.id = cs.source_id
                WHERE cs.job_id = $1
                ORDER BY cs.round, cs.fetch_rank NULLS LAST, cs.triage_score DESC
                """,
                job_id,
            )
        return [dict(r) for r in rows]

    async def latest_candidate_screenings(self, expert_id: int) -> list[dict]:
        """The most recent build's ledger for an expert, job or no job.

        A build run outside the job queue (the CLI, a script) writes its ledger
        with ``job_id`` NULL, and a job id cannot find it.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH latest AS (
                    SELECT job_id FROM candidate_screenings
                    WHERE expert_id = $1
                    ORDER BY created_at DESC LIMIT 1
                )
                SELECT cs.*, s.passed, s.relevance_score, s.source_tier, s.drop_reason
                FROM candidate_screenings cs
                LEFT JOIN sources s ON s.id = cs.source_id
                WHERE cs.expert_id = $1
                  AND cs.job_id IS NOT DISTINCT FROM (SELECT job_id FROM latest)
                ORDER BY cs.round, cs.fetch_rank NULLS LAST, cs.triage_score DESC
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    async def link_candidate_screenings(self, expert_id: int, job_id: int | None) -> None:
        """Point the ledger at the sources rows it produced, once they exist.

        The ledger is written per round, before anything is persisted, so a
        build that fails before persisting still leaves it behind; the link is
        made afterwards by URL.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE candidate_screenings cs
                SET source_id = s.id
                FROM sources s
                WHERE cs.expert_id = $1
                  AND cs.job_id IS NOT DISTINCT FROM $2
                  AND cs.source_id IS NULL
                  AND cs.fetch_outcome IN ('fetched', 'content_duplicate')
                  AND s.expert_id = cs.expert_id
                  AND s.url = cs.url
                  AND (s.discovered_via IS DISTINCT FROM 'upload')
                """,
                expert_id, job_id,
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

    async def passed_source_digest(
        self, expert_id: int
    ) -> list[tuple[str, str, float | None, list[str]]]:
        """The corpus as the persona prompt wants it: best sources first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT title, content_type, quality_score, key_claims
                FROM sources
                WHERE expert_id = $1 AND passed = true
                ORDER BY quality_score DESC NULLS LAST
                LIMIT 15
                """,
                expert_id,
            )
        return [
            (
                r["title"],
                r["content_type"] or "other",
                r["quality_score"],
                _as_claims(r["key_claims"]),
            )
            for r in rows
        ]

    async def update_avatar(self, expert_id: int, avatar: dict | None) -> Expert | None:
        """Pin (or clear) an expert's picture avatar.

        ``None`` writes SQL NULL, which is the "derive it from the persona name"
        default — so the same method both sets and resets, and there is no
        second endpoint for the reset.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE experts
                SET avatar = $1::jsonb, updated_at = NOW()
                WHERE id = $2
                RETURNING id
                """,
                json.dumps(avatar) if avatar is not None else None,
                expert_id,
            )
        # Re-read for the joined picture — see `update_catalog`.
        return await self.get_by_id(row["id"]) if row else None

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

        Runs at the start of a job's first attempt, and of a retry whose earlier
        attempt never reached ``chat_ready``. A retry that did reach it resumes
        from that readiness instead (see ``jobs/worker._resume_point``): the
        corpus is the expensive part, and wiping it to retry a persona call is
        how a finished PRO build was lost. Deleting the previous attempt's
        sources/chunks/graph first keeps a from-scratch run from creating
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
                f"""
                SELECT e.*, {_PICTURE_SQL}, similarity(lower(e.name), lower($1)) AS sim
                FROM experts e {_PICTURE_JOIN}
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


def _granted_clause(alias: str, idx: int) -> str:
    """The user at ``$idx`` holds a grant on this expert's *live* share link.

    Joining through the link, not only the grant, is what makes revocation
    total: resetting or disabling a link sets ``revoked_at`` and every grant
    made on it stops matching here, without a single grant row being touched.
    """
    return (
        "EXISTS (SELECT 1 FROM expert_share_grants g"
        " JOIN expert_share_links l ON l.id = g.link_id"
        f" WHERE l.expert_id = {alias}.id AND l.revoked_at IS NULL"
        f" AND g.user_id = ${idx}::uuid)"
    )


def _readable_clause(
    owner_id: str, include_unowned: bool, alias: str, idx: int
) -> tuple[str, list]:
    """READ clause: ownership OR public OR a grant on a live share link.

    Used only for expert rows. A row matching this is readable and chattable;
    it is *not* necessarily mutable — see :func:`_visibility_clause`.
    """
    own, params = _visibility_clause(owner_id, include_unowned, alias, idx)
    public = f"{alias}.visibility = 'public'"
    return (f"({own} OR {public} OR {_granted_clause(alias, idx)})", params)


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

    # source_type_counts is a computed column, present only on queries a client
    # renders from (the listings and the single-expert reads).
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

    # Absent from partial projections and from rows written before migration 025.
    raw_summary = row["build_summary"] if "build_summary" in keys else None
    if isinstance(raw_summary, str):
        raw_summary = json.loads(raw_summary)
    build_summary = raw_summary if isinstance(raw_summary, dict) else None

    # Absent from rows written before migration 026, and NULL for every expert
    # whose owner has not chosen a picture — both mean "derive it".
    raw_avatar = row["avatar"] if "avatar" in keys else None
    if isinstance(raw_avatar, str):
        raw_avatar = json.loads(raw_avatar)
    avatar = raw_avatar if isinstance(raw_avatar, dict) else None

    picture = row_to_picture(row, keys)

    catalog = _row_to_catalog(row, keys)

    # Computed on the same queries as source_type_counts; None where not selected.
    build_active = bool(row["build_active"]) if "build_active" in keys else None

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
        build_summary=build_summary,
        avatar=avatar,
        picture=picture,
        source_type_counts=source_type_counts,
        build_active=build_active,
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


def _as_claims(raw) -> list[str]:
    """``sources.key_claims`` is JSONB, which asyncpg hands back as a string."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return [c for c in (raw or []) if isinstance(c, str)]
