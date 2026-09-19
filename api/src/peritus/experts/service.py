"""Expert operations that are more than one repository call.

The routes above this layer are meant to read "validate, call, map": parse the
request, call one method here, turn the result or the error into HTTP. Anything
that has to touch two repositories and the entitlement service to get one thing
done belongs on this side of that line — `request_build` below being the case
that dragged a hundred and thirty lines of choreography into a route handler.
"""

import re
from dataclasses import dataclass

import asyncpg

from peritus.billing.service import EntitlementService
from peritus.core.config import settings
from peritus.core.exceptions import ConflictError, NotFoundError, PeritusError
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert, ExpertStatus, ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.jobs.domain import BuildJob, JobType
from peritus.jobs.repository import JobRepository

logger = get_logger(__name__)

# A slug is derived from the topic, so two users can legitimately want the same
# one. `base`, `base-2`, `base-3`… and after this many attempts the topic is
# genuinely too popular to disambiguate automatically.
_MAX_SLUG_ATTEMPTS = 50


class InvalidBuildRequest(PeritusError):
    """The request cannot produce a build: a bad topic, or unknown source types."""


@dataclass(frozen=True)
class BuildRequested:
    """What `request_build` did, in terms the route can map to a response."""

    expert: Expert
    job: BuildJob
    #: True when an in-flight build was joined rather than a new one started.
    #: Nothing was charged and the expert's status was left alone — it may be
    #: mid-build, and its hold was taken when that job was enqueued.
    attached: bool


def slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:80]


class ExpertService:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        repo: ExpertRepository | None = None,
        jobs: JobRepository | None = None,
        entitlements: EntitlementService | None = None,
    ) -> None:
        """`ExpertService(pool)` is the ordinary construction.

        The three keyword arguments exist so a test can substitute a
        collaborator without a database — `request_build` coordinates all three,
        and mocking them through the module namespace is how that kind of test
        goes stale.
        """
        self._pool = pool
        self._repo = repo or ExpertRepository(pool)
        self._jobs = jobs or JobRepository(pool)
        self._entitlements = entitlements or EntitlementService(pool)

    async def create(self, topic: str, owner_id: str | None = None) -> Expert:
        name = topic.lower().strip()
        existing = await self._repo.get_by_name(name)
        if existing:
            raise ConflictError(f"Expert already exists: {name!r}")
        return await self._repo.create(name, topic, owner_id=owner_id)

    async def get(self, name_or_id: str | int) -> Expert:
        if isinstance(name_or_id, int):
            expert = await self._repo.get_by_id(name_or_id)
        else:
            expert = await self._repo.get_by_name(name_or_id)
            if not expert:
                expert = await self._repo.fuzzy_find(name_or_id)
        if not expert:
            raise NotFoundError("Expert", str(name_or_id))
        return expert

    async def list_all(self) -> list[Expert]:
        return await self._repo.list_all()

    async def request_build(
        self,
        *,
        topic: str,
        owner_id: str,
        owner_email: str | None,
        is_admin: bool,
        tier: ExpertTier | None = None,
        sources: list[str] | None = None,
        known_sources: tuple[str, ...] = (),
    ) -> BuildRequested:
        """Resolve the expert, charge for the build, and queue it.

        **This is the gate.** Builds are the paid action, so entitlements are
        checked and held here, at enqueue — never mid-build, when the money is
        already being spent. Attaching to a build that is already running is
        free: its hold was taken when it was enqueued.

        Raises :class:`InvalidBuildRequest` for a request that cannot produce a
        build, :class:`ConflictError` when the topic's slugs are exhausted, and
        lets ``EntitlementError`` through for the caller to render.
        """
        if sources is not None:
            unknown = [s for s in sources if s not in known_sources]
            if unknown:
                raise InvalidBuildRequest(
                    f"Unknown source type(s): {', '.join(unknown)}. "
                    f"Valid source types: {', '.join(known_sources)}"
                )
            if not sources:
                raise InvalidBuildRequest(
                    "sources, when given, must name at least one source type. "
                    f"Valid source types: {', '.join(known_sources)}"
                )

        base_slug = slugify(topic)
        if not base_slug:
            raise InvalidBuildRequest("Topic must contain at least one letter or number")

        expert, slug = await self._resolve_slug(base_slug, owner_id, is_admin)

        if expert is not None:
            active = await self._jobs.get_active_job(expert.id, job_type=JobType.BUILD)
            if active is not None:
                logger.info("Attaching to in-flight build job %d for %r", active.id, slug)
                return BuildRequested(expert=expert, job=active, attached=True)

        resolved = (
            tier
            if tier is not None
            else await self._entitlements.resolve_tier(owner_id, None, owner_email)
        )
        # Checked before anything is created, so a denial leaves no orphan rows.
        await self._entitlements.authorize_build(owner_id, resolved, owner_email)

        expert = await self._prepare_for_build(expert, slug, topic, resolved, owner_id)
        job = await self._jobs.enqueue(
            expert.id,
            tier=resolved.value,
            source_filter=sources or None,
            max_attempts=settings.WORKER_MAX_ATTEMPTS,
        )
        # First event in the durable log, so every client — including one that
        # reconnects later — learns which expert this stream belongs to without
        # re-deriving the slug client-side.
        await self._jobs.append_event(
            job.id,
            "created",
            {
                "type": "created",
                "slug": expert.name,
                "expert_id": expert.id,
                "job_id": job.id,
                "tier": resolved.value,
                "topic": expert.topic,
            },
        )
        # The authoritative charge. Re-checks the balance under a row lock and is
        # idempotent per job id, so a double-submit landing on the same job never
        # double-charges. A failure here cancels the job rather than leaving it
        # to run unpaid.
        try:
            await self._entitlements.hold_for_job(owner_id, job.id, resolved)
        except Exception:
            await self._jobs.request_cancel(expert.id, job_type=JobType.BUILD)
            await self._repo.update_status(expert.id, ExpertStatus.FAILED, "Not enough credits")
            raise

        logger.info("Enqueued build job %d for %r (expert=%d)", job.id, slug, expert.id)
        return BuildRequested(expert=expert, job=job, attached=False)

    async def _resolve_slug(
        self, base_slug: str, owner_id: str, is_admin: bool
    ) -> tuple[Expert | None, str]:
        """Walk `base`, `base-2`, `base-3`… to the caller's expert or a free slug.

        Another user's expert on the same topic is silently stepped over: its
        existence is never revealed, and the caller gets the next slug along.
        """
        for i in range(1, _MAX_SLUG_ATTEMPTS + 1):
            slug = base_slug if i == 1 else f"{base_slug}-{i}"
            candidate = await self._repo.get_by_name(slug)
            if candidate is None:
                return None, slug
            if candidate.is_owned_by(owner_id, include_unowned=is_admin):
                return candidate, slug
        raise ConflictError("Too many experts already exist for this topic — rename it slightly")

    async def _prepare_for_build(
        self,
        expert: Expert | None,
        slug: str,
        topic: str,
        tier: ExpertTier,
        owner_id: str,
    ) -> Expert:
        """Create the expert, or put an existing one back into the queue."""
        if expert is None:
            return await self._repo.create(name=slug, topic=topic, tier=tier, owner_id=owner_id)
        if expert.tier != tier:
            # Rebuild at a different depth: the worker builds from the expert
            # row, so tier and config must move with the request or the new
            # build silently runs at the old depth.
            await self._repo.update_tier(expert.id, tier)
        await self._repo.update_status(expert.id, ExpertStatus.QUEUED)
        return expert

    async def delete(self, name_or_id: str | int) -> None:
        expert = await self.get(name_or_id)
        await self._repo.delete(expert.id)

    async def mark_failed(self, expert_id: int, error: str) -> None:
        await self._repo.update_status(expert_id, ExpertStatus.FAILED, error)

    async def mark_ready(self, expert_id: int) -> None:
        await self._repo.update_status(expert_id, ExpertStatus.READY)

    async def regenerate_persona(self, name_or_id: str | int) -> Expert:
        """Re-voice an already-built expert without rebuilding its corpus.

        The persona is generated once, at the end of a build, and then persisted
        forever — so a change to the persona prompt only reaches experts built
        after it. That would be an acceptable lag if personas were cosmetic, but
        the persona is half of the answer's voice: an expert carrying a persona
        generated under the old "describe how they cite and qualify claims"
        prompt keeps hedging no matter what the current contract says. This
        replays only the persona stage, off the corpus already in the database —
        one model call instead of a full re-fetch, re-validate and re-embed.
        """
        # Imported lazily: the builder drags in every fetcher (and their optional
        # third-party dependencies), which no other caller of this service needs.
        from peritus.experts.build.persona import generate_persona
        from peritus.graph.repository import GraphRepository

        expert = await self.get(name_or_id)
        sources = await self._repo.passed_source_digest(expert.id)
        if not sources:
            raise NotFoundError("Corpus for expert", expert.name)

        top_nodes = await GraphRepository(self._pool).get_top_nodes(expert.id, 20)
        persona = await generate_persona(expert.topic, sources, top_nodes)
        await self._repo.update_persona(
            expert.id,
            persona_name=persona["name"],
            persona_bio=persona["bio"],
            persona_style=persona["style"],
        )
        logger.info(
            "Regenerated persona for expert %d (%r): %s",
            expert.id,
            expert.name,
            persona["name"],
        )
        return await self.get(expert.id)

    async def refresh_picture(
        self,
        name_or_id: str | int,
        *,
        hints_from_corpus: bool = True,
        deadline: float | None = None,
    ) -> Expert:
        """Find this expert's picture again, from scratch, and store the result.

        The build finds a picture once and then leaves it alone — a rebuild does
        not re-find, because the topic has not changed and the owner may have
        chosen the one that is there. This is the explicit "find another": the
        backfill for experts built before pictures existed, and the picker's
        Find-another button.

        ``hints_from_corpus`` adds the titles of the expert's own validated
        Wikipedia sources to the query list. Those have already been judged
        relevant to this corpus by the validator, so on an expert whose topic
        string is vague they are a much better search than the topic is.

        ``deadline`` overrides ``PICTURE_TIMEOUT``, which is sized for a build:
        20 seconds is right when nothing may wait on the search and the fallback
        is a monogram nobody will notice. An operator running the backfill is
        waiting at a terminal on purpose and has no such constraint — and when
        Wikimedia is pacing us, a single honoured ``Retry-After`` can be most of
        a build's whole budget.

        Raises :class:`PictureSkipped` when nothing acceptable was found, so the
        caller can say *why* rather than only that nothing changed.
        """
        # Imported lazily for the same reason `regenerate_persona` imports the
        # builder lazily: no other caller of this service wants httpx clients
        # and Wikimedia plumbing loaded at import time.
        from peritus.experts.picture import find_picture
        from peritus.experts.picture_repository import ExpertPictureRepository
        from peritus.infrastructure.wikimedia import WikimediaClient

        expert = await self.get(name_or_id)
        pictures = ExpertPictureRepository(self._pool)
        hints = await pictures.wikipedia_source_titles(expert.id) if hints_from_corpus else ()

        async with WikimediaClient() as client:
            found = await find_picture(
                client, expert.topic, expert.key_concepts, hints, deadline=deadline, widen=True
            )
        await pictures.upsert(expert.id, found, chosen_by="build")
        logger.info(
            "Refreshed picture for expert %d (%r): %s (%s)",
            expert.id,
            expert.name,
            found.page_title,
            found.license,
        )
        return await self.get(expert.id)
