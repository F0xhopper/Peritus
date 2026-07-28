"""Shared executor for many independent Claude calls.

Build-pipeline stages (triage, validation, contextualisation, graph extraction)
each need N independent `messages.create` calls whose results are matched back
to inputs by position. This module runs such a set either:

- through the **Message Batches API** (50% of standard token prices — the right
  choice for latency-insensitive background builds), or
- as **live concurrent calls** when batching is disabled, the set is too small
  to be worth queueing, or a batch times out / individual items fail.

Which of the two a stage uses is **per build**, not process-wide. A build
declares its policy once, up front, via :func:`build_execution`; every stage it
runs inherits it through a :class:`~contextvars.ContextVar`, so the four call
sites and the four functions between them keep their existing signatures and
two builds running concurrently in the same worker cannot affect each other
(``asyncio`` tasks each get their own copy of the context).

    with build_execution(BuildExecution.INTERACTIVE):
        await builder.build(expert)      # every stage now makes live calls

Failure semantics: the returned list is positionally aligned with the input;
an entry is the Anthropic ``Message`` on success or ``None`` when that request
failed after retries. Callers map ``None`` to their stage-specific fallback.
"""

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client

logger = get_logger(__name__)

_LIVE_ATTEMPTS = 3
_TERMINAL_BATCH_ERRORS = ("invalid_request",)


class BuildExecution(StrEnum):
    """The cost/latency trade-off a single build has chosen.

    ``INTERACTIVE`` — live concurrent calls. Stages finish in seconds to a few
    minutes and the user gets an expert while they are still watching, at full
    token price. This is what a first build wants.

    ``BACKGROUND`` — Message Batches API. Half the token price, but each of the
    four batched stages can sit in the Anthropic queue for up to an hour, so a
    build can take hours end to end. This is what a rebuild or a scheduled
    refresh wants: nobody is blocked on it.
    """

    INTERACTIVE = "interactive"
    BACKGROUND = "background"


# Default for callers that never declared a policy (e.g. a one-off script
# calling ``contextualize_chunks``): the historical, env-driven behaviour.
_execution: ContextVar[BuildExecution] = ContextVar(
    "peritus_build_execution", default=BuildExecution.BACKGROUND
)


def current_execution() -> BuildExecution:
    """The execution policy in force for the current build/task."""
    return _execution.get()


@contextmanager
def build_execution(mode: BuildExecution) -> Iterator[None]:
    """Declare the execution policy for everything run inside the block."""
    token = _execution.set(mode)
    try:
        yield
    finally:
        _execution.reset(token)


def should_batch(request_count: int) -> bool:
    """Whether a stage of ``request_count`` calls should go through Message Batches.

    Three gates, in order of authority:

    1. ``ANTHROPIC_BATCH_ENABLED`` — deployment-level kill switch. False means
       this deployment never touches the Batch API, whatever a build asks for.
    2. The build's own policy (see :class:`BuildExecution`).
    3. ``ANTHROPIC_BATCH_MIN_REQUESTS`` — batch overhead isn't worth it for a
       handful of requests.
    """
    return (
        settings.ANTHROPIC_BATCH_ENABLED
        and current_execution() is BuildExecution.BACKGROUND
        and request_count >= settings.ANTHROPIC_BATCH_MIN_REQUESTS
    )


async def gather_claude_calls(
    params_list: list[dict[str, Any]],
    *,
    live_concurrency: int = 4,
    description: str = "claude-calls",
) -> list[Any | None]:
    """Run every ``messages.create(**params)`` in ``params_list``.

    Returns one entry per input, in order: the ``Message`` or ``None``.
    """
    if not params_list:
        return []

    if not should_batch(len(params_list)):
        return await _run_live(params_list, live_concurrency)

    try:
        results = await _run_batch(params_list, description)
    except Exception as exc:
        logger.warning(
            "Message batch %r failed outright (%s) — falling back to live calls",
            description, exc,
        )
        return await _run_live(params_list, live_concurrency)

    # Live-retry only the items the batch could not complete.
    missing = [i for i, r in enumerate(results) if r is None]
    if missing:
        logger.warning(
            "Message batch %r: %d/%d items unfinished — retrying them live",
            description, len(missing), len(params_list),
        )
        retried = await _run_live([params_list[i] for i in missing], live_concurrency)
        for idx, msg in zip(missing, retried, strict=True):
            results[idx] = msg
    return results


async def _run_live(
    params_list: list[dict[str, Any]],
    concurrency: int,
) -> list[Any | None]:
    client = get_anthropic_client()
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(params: dict[str, Any]) -> Any | None:
        async with sem:
            for attempt in range(_LIVE_ATTEMPTS):
                try:
                    return await client.messages.create(**params)
                except Exception as exc:
                    if attempt == _LIVE_ATTEMPTS - 1:
                        logger.warning("Live Claude call failed after retries: %s", exc)
                        return None
                    await asyncio.sleep(2 ** attempt)
        return None

    return list(await asyncio.gather(*(one(p) for p in params_list)))


async def _run_batch(
    params_list: list[dict[str, Any]],
    description: str,
) -> list[Any | None]:
    """Submit one Messages Batch and wait for it; harvest whatever finished.

    Raises on submission failure so the caller can fall back to live calls.
    """
    client = get_anthropic_client()
    batch = await client.messages.batches.create(
        requests=[
            {"custom_id": f"req-{i}", "params": params}
            for i, params in enumerate(params_list)
        ]
    )
    logger.info(
        "Submitted message batch %s (%r, %d requests)",
        batch.id, description, len(params_list),
    )

    deadline = time.monotonic() + settings.ANTHROPIC_BATCH_TIMEOUT
    while True:
        await asyncio.sleep(settings.ANTHROPIC_BATCH_POLL_INTERVAL)
        batch = await client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        if time.monotonic() > deadline:
            logger.warning(
                "Message batch %s (%r) exceeded ANTHROPIC_BATCH_TIMEOUT — cancelling",
                batch.id, description,
            )
            await client.messages.batches.cancel(batch.id)
            batch = await _await_ended(client, batch.id)
            break

    results: list[Any | None] = [None] * len(params_list)
    async for entry in await client.messages.batches.results(batch.id):
        try:
            idx = int(entry.custom_id.removeprefix("req-"))
        except ValueError:
            logger.warning("Batch result with unexpected custom_id %r", entry.custom_id)
            continue
        if not 0 <= idx < len(params_list):
            continue
        if entry.result.type == "succeeded":
            results[idx] = entry.result.message
        else:
            logger.warning(
                "Batch item %s in %s: %s", entry.custom_id, batch.id, entry.result.type,
            )

    done = sum(1 for r in results if r is not None)
    logger.info(
        "Message batch %s (%r) finished: %d/%d succeeded",
        batch.id, description, done, len(params_list),
    )
    return results


async def _await_ended(client: Any, batch_id: str) -> Any:
    """After a cancel, wait briefly until the batch reaches 'ended' so results are readable."""
    for _ in range(20):
        batch = await client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return batch
        await asyncio.sleep(3)
    return batch
