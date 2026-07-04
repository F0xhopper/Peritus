"""Shared executor for many independent Claude calls.

Build-pipeline stages (triage, validation, contextualisation, graph extraction)
each need N independent `messages.create` calls whose results are matched back
to inputs by position. This module runs such a set either:

- through the **Message Batches API** (50% of standard token prices — the right
  choice for latency-insensitive background builds), or
- as **live concurrent calls** when batching is disabled, the set is too small
  to be worth queueing, or a batch times out / individual items fail.

Failure semantics: the returned list is positionally aligned with the input;
an entry is the Anthropic ``Message`` on success or ``None`` when that request
failed after retries. Callers map ``None`` to their stage-specific fallback.
"""

import asyncio
import time
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client

logger = get_logger(__name__)

_LIVE_ATTEMPTS = 3
_TERMINAL_BATCH_ERRORS = ("invalid_request",)


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

    use_batch = (
        settings.ANTHROPIC_BATCH_ENABLED
        and len(params_list) >= settings.ANTHROPIC_BATCH_MIN_REQUESTS
    )
    if not use_batch:
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
