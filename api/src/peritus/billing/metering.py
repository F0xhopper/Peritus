"""Per-build cost metering.

**What this measures, and how it avoids lying.**

Every dollar a build spends leaves the process through one of three calls:
``messages.create`` (live Claude calls), ``messages.batches.results`` (the
Message Batches API), and ``embeddings.create`` (OpenAI). This module wraps
those three, and only those three, and records what the *response* reported:
the model string comes off the response, and the mode (``live``/``batch``) comes
from which wrapper saw it. Nothing here reads ``ANTHROPIC_BATCH_ENABLED`` or any
other configuration to infer what a call cost — batching is decided per build
elsewhere and can fall back to live calls mid-stage, so configuration is not
evidence of what happened.

**How it attaches to a build.** The worker puts a :class:`BuildMeter` in a
context variable before starting the build task. ``asyncio`` copies the context
into every child task, so all of the pipeline's concurrent fan-out records into
the same meter, and two builds running in one worker cannot cross-contaminate.
The meter is a *mutable object* held in the contextvar rather than a value:
stage transitions mutate it in place, so tasks created before a transition still
see the current stage.

**How it attaches to a stage.** The builder already emits
``{"type": "stage", "name": ...}`` events for the UI. The worker forwards those
into :meth:`BuildMeter.set_stage`, so stage attribution costs no builder
changes and stays correct if stages are reordered.

Instrumentation is installed by replacing the cached client singletons with
transparent proxies (``__getattr__`` delegates everything not overridden). It is
idempotent, process-wide, and a no-op when no meter is in context — so chat
traffic through the same clients is unaffected.
"""

import asyncio
import contextlib
import threading
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from peritus.billing.pricing import embedding_cost_usd, message_cost_usd
from peritus.billing.settings import settings
from peritus.core.logging import get_logger

logger = get_logger(__name__)


class Stage:
    """Canonical stage names recorded against spend."""

    PLAN = "plan"
    TRIAGE = "triage"
    VALIDATION = "validation"
    CONTEXTUALIZATION = "contextualization"
    GRAPH_EXTRACTION = "graph_extraction"
    PERSONA = "persona"
    OTHER = "other"


# Maps the builder's own progress-event stage names onto billing stages. Keys
# are the `name` field of a `{"type": "stage"}` event. Unknown names fall back
# to OTHER rather than being dropped, so spend is never silently unattributed.
_EVENT_STAGE_MAP: dict[str, str] = {
    "plan": Stage.PLAN,
    # Discovery's LLM cost is the triage pass that ranks candidates.
    "discover": Stage.TRIAGE,
    "triage": Stage.TRIAGE,
    "validate": Stage.VALIDATION,
    # Chunk/embed: contextual prefixes (Claude) + embeddings (OpenAI). Provider
    # separates them in the recorded rows.
    "chunk": Stage.CONTEXTUALIZATION,
    "ingest": Stage.CONTEXTUALIZATION,
    "graph": Stage.GRAPH_EXTRACTION,
    "resolve": Stage.GRAPH_EXTRACTION,
    "persona": Stage.PERSONA,
}


def stage_for_event(name: str | None) -> str:
    if not name:
        return Stage.OTHER
    return _EVENT_STAGE_MAP.get(name.strip().lower(), Stage.OTHER)


@dataclass
class UsageBucket:
    """Aggregated usage for one (stage, provider, model, mode) key."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: Decimal = Decimal(0)

    def add(self, other: "UsageBucket") -> None:
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens
        self.cost_usd += other.cost_usd


UsageKey = tuple[str, str, str, str]  # (stage, provider, model, mode)


class BuildMeter:
    """Accumulates one build's spend and enforces its ceiling.

    Recording is synchronous and lock-guarded but never awaits: it runs on the
    hot path of every provider call, and a slow meter would show up as latency
    on every chunk. Persistence happens out of band via :meth:`drain`.
    """

    def __init__(
        self,
        job_id: int,
        expert_id: int | None = None,
        owner_id: str | None = None,
        cap_usd: float | None = None,
    ) -> None:
        self.job_id = job_id
        self.expert_id = expert_id
        self.owner_id = owner_id
        self.cap_usd = Decimal(str(cap_usd)) if cap_usd and cap_usd > 0 else None
        self.stage: str = Stage.OTHER
        self.total_cost_usd: Decimal = Decimal(0)
        self.embed_tokens: int = 0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.over_cap: bool = False
        self._buckets: dict[UsageKey, UsageBucket] = {}
        # Provider calls can land from many concurrent tasks; the lock keeps the
        # dict and the running totals consistent without an event-loop hop.
        self._lock = threading.Lock()

    # ── stage tracking ──────────────────────────────────────────────────────

    def set_stage(self, stage: str) -> None:
        self.stage = stage

    def observe_event(self, event: dict[str, Any]) -> None:
        """Update the current stage from a builder progress event."""
        if event.get("type") == "stage":
            self.set_stage(stage_for_event(event.get("name")))

    # ── recording ───────────────────────────────────────────────────────────

    def record_message(self, model: str, usage: Any, batch: bool) -> None:
        """Record one Claude message from its reported ``usage`` block."""
        if usage is None:
            return
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cache_creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cost = message_cost_usd(
            model,
            input_tokens,
            output_tokens,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
            batch=batch,
        )
        bucket = UsageBucket(
            calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
            cost_usd=cost,
        )
        self._accumulate(
            (self.stage, "anthropic", model or "unknown", "batch" if batch else "live"), bucket
        )

    def record_embedding(self, model: str, tokens: int) -> None:
        cost = embedding_cost_usd(model, tokens)
        bucket = UsageBucket(calls=1, input_tokens=tokens, cost_usd=cost)
        self._accumulate((self.stage, "openai", model or "unknown", "live"), bucket)
        with self._lock:
            self.embed_tokens += tokens

    def _accumulate(self, key: UsageKey, bucket: UsageBucket) -> None:
        with self._lock:
            self._buckets.setdefault(key, UsageBucket()).add(bucket)
            self.total_cost_usd += bucket.cost_usd
            self.total_input_tokens += bucket.input_tokens
            self.total_output_tokens += bucket.output_tokens
            if self.cap_usd is not None and self.total_cost_usd >= self.cap_usd and not self.over_cap:
                self.over_cap = True
                logger.warning(
                    "Build job %s hit its spend cap: $%.4f of $%.2f",
                    self.job_id, self.total_cost_usd, self.cap_usd,
                )

    # ── draining ────────────────────────────────────────────────────────────

    def drain(self) -> list[tuple[UsageKey, UsageBucket]]:
        """Take everything accumulated so far, leaving the meter's totals intact.

        Totals (``total_cost_usd`` and friends) are the build's running spend and
        are never reset — only the not-yet-persisted per-key deltas are handed
        out, so a flush can't double-count and a failed flush can be retried by
        the next one only if the caller hands the rows back.
        """
        with self._lock:
            drained = list(self._buckets.items())
            self._buckets = {}
        return drained

    def restore(self, rows: list[tuple[UsageKey, UsageBucket]]) -> None:
        """Put drained rows back after a failed flush, so nothing is lost."""
        with self._lock:
            for key, bucket in rows:
                self._buckets.setdefault(key, UsageBucket()).add(bucket)

    @property
    def spent_usd(self) -> float:
        return float(self.total_cost_usd)


# The active meter for the current task tree. Holding a mutable object (rather
# than a value) is deliberate: child tasks copy the context at creation, so a
# later stage transition must be visible through the same object reference.
_current_meter: ContextVar[BuildMeter | None] = ContextVar("peritus_build_meter", default=None)


def current_meter() -> BuildMeter | None:
    return _current_meter.get()


def set_meter(meter: BuildMeter | None):
    """Bind a meter to the current task's context. Returns the reset token."""
    return _current_meter.set(meter)


def reset_meter(token) -> None:
    with contextlib.suppress(ValueError):
        _current_meter.reset(token)


# ── instrumentation ─────────────────────────────────────────────────────────


class _MeteredBatches:
    """Wraps ``messages.batches``; records usage as batch results stream past."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def results(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        decoder = await self._inner.results(*args, **kwargs)
        return _metered_batch_results(decoder, current_meter())


async def _metered_batch_results(decoder: Any, meter: BuildMeter | None) -> AsyncIterator[Any]:
    """Pass batch entries through untouched, recording each succeeded message.

    The meter is captured when ``results()`` is called rather than read per
    entry: iteration may be driven from a different task, and this keeps every
    entry of one batch attributed to the build that submitted it.
    """
    async for entry in decoder:
        if meter is not None:
            with contextlib.suppress(Exception):
                result = getattr(entry, "result", None)
                if getattr(result, "type", None) == "succeeded":
                    message = getattr(result, "message", None)
                    meter.record_message(
                        getattr(message, "model", "") or "",
                        getattr(message, "usage", None),
                        batch=True,
                    )
        yield entry


class _MeteredMessages:
    """Wraps ``client.messages``; records live ``create`` calls."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._batches = _MeteredBatches(inner.batches)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def batches(self) -> _MeteredBatches:
        return self._batches

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        message = await self._inner.create(*args, **kwargs)
        meter = current_meter()
        if meter is not None:
            with contextlib.suppress(Exception):
                meter.record_message(
                    getattr(message, "model", "") or kwargs.get("model", ""),
                    getattr(message, "usage", None),
                    batch=False,
                )
        return message

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        # Chat only — never runs inside a build's meter context. Passed through
        # untouched so the streaming context-manager protocol is preserved.
        return self._inner.stream(*args, **kwargs)


class _MeteredAnthropicClient:
    """Transparent proxy over ``AsyncAnthropic``; only ``messages`` is wrapped."""

    _peritus_metered = True

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._messages = _MeteredMessages(inner.messages)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def messages(self) -> _MeteredMessages:
        return self._messages


class _MeteredEmbeddings:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        response = await self._inner.create(*args, **kwargs)
        meter = current_meter()
        if meter is not None:
            with contextlib.suppress(Exception):
                usage = getattr(response, "usage", None)
                tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                if tokens:
                    meter.record_embedding(
                        getattr(response, "model", "") or kwargs.get("model", ""), tokens
                    )
        return response


class _MeteredOpenAIClient:
    _peritus_metered = True

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._embeddings = _MeteredEmbeddings(inner.embeddings)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def embeddings(self) -> _MeteredEmbeddings:
        return self._embeddings


_install_lock = threading.Lock()
_installed = False


def install_instrumentation() -> bool:
    """Wrap the cached provider clients so build spend is observable.

    Idempotent and best-effort: if a client cannot be constructed (no API key in
    a test environment, say) metering degrades to nothing and the build still
    runs. Called by the worker rather than at import so nothing is constructed
    in processes that never build.
    """
    global _installed
    with _install_lock:
        if _installed:
            return True
        ok = False
        try:
            from peritus.infrastructure import anthropic_client

            client = anthropic_client.get_anthropic_client()
            if not getattr(client, "_peritus_metered", False):
                anthropic_client._client = _MeteredAnthropicClient(client)  # type: ignore[assignment]
            ok = True
        except Exception as exc:
            logger.warning("Could not instrument the Anthropic client: %s", exc)

        try:
            from peritus.infrastructure import embeddings

            emb_client = embeddings.get_embeddings_client()
            if not getattr(emb_client, "_peritus_metered", False):
                embeddings._client = _MeteredOpenAIClient(emb_client)  # type: ignore[assignment]
            ok = True
        except Exception as exc:
            logger.warning("Could not instrument the embeddings client: %s", exc)

        _installed = ok
        return ok


async def flush_periodically(meter: BuildMeter, persist, interval: float | None = None) -> None:
    """Background task: persist the meter's accumulated usage on a cadence.

    ``persist`` is an async callable taking the drained rows. On failure the
    rows go back into the meter so the next flush retries them.
    """
    delay = interval or settings.METER_FLUSH_INTERVAL
    while True:
        await asyncio.sleep(delay)
        await flush_once(meter, persist)


async def flush_once(meter: BuildMeter, persist) -> None:
    rows = meter.drain()
    if not rows:
        return
    try:
        await persist(rows)
    except Exception as exc:
        meter.restore(rows)
        logger.warning("Failed to persist build usage for job %s: %s", meter.job_id, exc)
