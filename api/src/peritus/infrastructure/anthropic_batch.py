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
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from typing import Any, cast

from anthropic.types.message_create_params import MessageCreateParamsNonStreaming

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client

logger = get_logger(__name__)

_LIVE_ATTEMPTS = 3
_TERMINAL_BATCH_ERRORS = ("invalid_request",)


def is_terminal_provider_error(exc: BaseException) -> bool:
    """Whether retrying this exception is provably pointless.

    An exhausted credit balance and a rejected key both arrive as ordinary API
    errors and were retried three times each, per call, across every stage —
    then reported by each stage in its own vocabulary. A build once failed with
    "All sources failed validation. Try a different topic or sources." when the
    real message, which Anthropic supplied and the code discarded, was "Your
    credit balance is too low to access the Anthropic API."
    """
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return True
    if status == 400:
        body = getattr(exc, "body", None)
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict) and err.get("type") in ("invalid_request_error",):
            return True
    return False


def provider_error_message(exc: BaseException) -> str:
    """The provider's own wording, which is the only actionable part."""
    body = getattr(exc, "body", None)
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict) and isinstance(err.get("message"), str):
        return err["message"]
    return str(exc) or type(exc).__name__


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


class ProviderStatus:
    """Mutable per-build record of a terminal provider failure.

    A *mutable holder* in the ContextVar rather than the exception itself,
    because ``asyncio.gather`` runs each call in its own Task with a **copy** of
    the context: a ``ContextVar.set`` inside one of them is invisible to the
    caller. The copy shares this object by reference, so mutating it is seen.
    """

    __slots__ = ("terminal",)

    def __init__(self) -> None:
        self.terminal: BaseException | None = None


_provider_status: ContextVar[ProviderStatus | None] = ContextVar(
    "peritus_provider_status", default=None
)


def terminal_provider_error() -> BaseException | None:
    """The terminal provider error seen during this build, if any.

    Lets a stage distinguish "the model judged the inputs and rejected them"
    from "the model was never reachable" — the two are indistinguishable at the
    call site, since both surface as a ``None`` result.
    """
    status = _provider_status.get()
    return status.terminal if status else None


def current_execution() -> BuildExecution:
    """The execution policy in force for the current build/task."""
    return _execution.get()


@contextmanager
def build_execution(mode: BuildExecution) -> Iterator[None]:
    """Declare the execution policy for everything run inside the block.

    Also installs a fresh :class:`ProviderStatus`, so a terminal provider error
    is scoped to this build and never leaks into a concurrent one.
    """
    token = _execution.set(mode)
    status_token = _provider_status.set(ProviderStatus())
    try:
        yield
    finally:
        _provider_status.reset(status_token)
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


ResultCallback = Callable[[int, Any], Coroutine[Any, Any, None]]


async def gather_claude_calls(
    params_list: list[dict[str, Any]],
    *,
    live_concurrency: int = 4,
    description: str = "claude-calls",
    on_result: ResultCallback | None = None,
) -> list[Any | None]:
    """Run every ``messages.create(**params)`` in ``params_list``.

    Returns one entry per input, in order: the ``Message`` or ``None``.

    ``on_result(index, message_or_none)`` is awaited exactly once per input.
    On the live path it fires as each call completes, so callers can stream
    progress while the set is still running; on the batch path everything
    arrives when the batch ends, so the calls fire together after harvest.
    A callback failure is logged and swallowed — progress reporting must never
    fail the work it reports on.
    """
    if not params_list:
        return []

    if not should_batch(len(params_list)):
        return await _run_live(
            params_list, live_concurrency, on_result=on_result, description=description
        )

    try:
        results = await _run_batch(params_list, description)
    except Exception as exc:
        logger.warning(
            "Message batch %r failed outright (%s: %s) — falling back to live calls",
            description, type(exc).__name__, exc, exc_info=True,
        )
        return await _run_live(
            params_list, live_concurrency, on_result=on_result, description=description
        )

    # Live-retry only the items the batch could not complete. on_result is not
    # passed through: it is invoked once per input below, after the merge, so
    # retried items are not reported twice (and not under their retry index).
    missing = [i for i, r in enumerate(results) if r is None]
    if missing:
        logger.warning(
            "Message batch %r: %d/%d items unfinished — retrying them live",
            description, len(missing), len(params_list),
        )
        retried = await _run_live(
            [params_list[i] for i in missing],
            live_concurrency,
            description=f"{description}:batch-retry",
        )
        for idx, msg in zip(missing, retried, strict=True):
            results[idx] = msg
    if on_result:
        for i, msg in enumerate(results):
            await _report(on_result, i, msg)
    return results


async def _report(on_result: ResultCallback, index: int, msg: Any) -> None:
    try:
        await on_result(index, msg)
    except Exception:
        logger.warning("on_result callback failed for item %d", index, exc_info=True)


async def _run_live(
    params_list: list[dict[str, Any]],
    concurrency: int,
    on_result: ResultCallback | None = None,
    description: str = "claude-calls",
) -> list[Any | None]:
    """Run the set as live concurrent calls, retrying each up to _LIVE_ATTEMPTS.

    Logging here is deliberately loud, because this is where a provider outage
    becomes a silent `None` that every caller then reports in its own domain
    vocabulary. A whole build once failed with "All sources failed validation.
    Try a different topic" when the truth was that every call in this function
    had failed: the only trace was one `%s`-formatted line with no stage name,
    no exception type, and nothing at all from the two retries before it. So:
    every failed attempt logs, with the stage and the exception type, and the
    set logs an aggregate that makes a total outage impossible to misread.
    """
    client = get_anthropic_client()
    sem = asyncio.Semaphore(max(1, concurrency))
    model = str(params_list[0].get("model", "?")) if params_list else "?"
    logger.info(
        "Live Claude calls: %d request(s) for %r (model=%s, concurrency=%d)",
        len(params_list), description, model, max(1, concurrency),
    )
    started = time.monotonic()

    async def one(index: int, params: dict[str, Any]) -> Any | None:
        msg: Any | None = None
        async with sem:
            for attempt in range(_LIVE_ATTEMPTS):
                try:
                    msg = await client.messages.create(**params)
                    if attempt:
                        logger.info(
                            "Live Claude call %r[%d] succeeded on attempt %d/%d",
                            description, index, attempt + 1, _LIVE_ATTEMPTS,
                        )
                    break
                except Exception as exc:
                    if is_terminal_provider_error(exc):
                        # No amount of retrying fixes a rejected key or an empty
                        # balance. Record it so the build can report the
                        # provider's own message instead of guessing.
                        status = _provider_status.get()
                        if status is not None:
                            status.terminal = exc
                        logger.error(
                            "Live Claude call %r[%d]: terminal provider error, not "
                            "retrying — %s",
                            description, index, provider_error_message(exc),
                        )
                        break
                    # Every attempt, not just the last. A call that succeeds on
                    # its third try is a provider degrading, and that is exactly
                    # the signal worth having before it degrades all the way.
                    last = attempt == _LIVE_ATTEMPTS - 1
                    logger.warning(
                        "Live Claude call %r[%d] attempt %d/%d failed: %s: %s%s",
                        description, index, attempt + 1, _LIVE_ATTEMPTS,
                        type(exc).__name__, exc,
                        "" if last else f" — retrying in {2 ** attempt}s",
                        exc_info=last,  # full traceback once, on the giving-up attempt
                    )
                    if not last:
                        await asyncio.sleep(2 ** attempt)
        if on_result:
            await _report(on_result, index, msg)
        return msg

    results = list(await asyncio.gather(*(one(i, p) for i, p in enumerate(params_list))))

    failed = sum(1 for r in results if r is None)
    elapsed = time.monotonic() - started
    if failed == len(results):
        # The case that has to be unmissable: nothing got through, so whatever
        # the caller reports next is about the provider, not about its inputs.
        status = _provider_status.get()
        terminal = status.terminal if status else None
        logger.error(
            "Live Claude calls %r: ALL %d call(s) failed (%.1fs, model=%s) — %s. "
            "Downstream stage failures are provider errors, not bad input",
            description, len(results), elapsed, model,
            f"terminal provider error, not retried: {provider_error_message(terminal)}"
            if terminal is not None
            else f"each retried {_LIVE_ATTEMPTS}x",
        )
    elif failed:
        logger.warning(
            "Live Claude calls %r: %d/%d failed after retries (%.1fs)",
            description, failed, len(results), elapsed,
        )
    else:
        logger.info(
            "Live Claude calls %r: %d/%d succeeded (%.1fs)",
            description, len(results), len(results), elapsed,
        )
    return results


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
            # Callers assemble params as plain dicts (they are built per-stage and
            # passed through unchanged to either transport), so the SDK's
            # TypedDict shape is asserted here rather than threaded through.
            {"custom_id": f"req-{i}", "params": cast(MessageCreateParamsNonStreaming, params)}
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
            # The per-item error carries the actual cause (rate limit, invalid
            # request, overloaded). Logging only `result.type` reduced every one
            # of those to the word "errored".
            logger.warning(
                "Batch item %s in %s (%r): %s — %s",
                entry.custom_id, batch.id, description, entry.result.type,
                getattr(entry.result, "error", None) or "no error detail",
            )

    done = sum(1 for r in results if r is not None)
    if not done:
        logger.error(
            "Message batch %s (%r): ALL %d item(s) failed — downstream stage "
            "failures are provider errors, not bad input",
            batch.id, description, len(params_list),
        )
    else:
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
