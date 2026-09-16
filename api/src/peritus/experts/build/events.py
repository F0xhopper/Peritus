"""What a build says about itself, and how much of it reaches the log.

Every stage reports through one callback, and the same events are both streamed
to whoever is watching and appended to `build_events` so a build can be replayed
long after its stream closed. This module is the vocabulary: which events are
worth a log line, and how much of a payload is worth keeping when they are.

The filtering matters more than it looks. A build emits thousands of events —
one per candidate triaged, per source fetched, per chunk embedded — and logging
all of them at INFO buries the six that say what the build actually decided.
"""

import time
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from typing import Any

from peritus.core.logging import get_logger

logger = get_logger(__name__)

EventCallback = Callable[[dict], Coroutine[Any, Any, None]]


async def _emit_event(cb: EventCallback | None, event: dict) -> None:
    _log_event(event)
    if cb:
        await cb(event)


# Wall-clock of the stage currently running, so each stage boundary can report
# how long the previous one took. A module-level single slot is enough: a build
# runs its stages in sequence, and concurrent builds each get their own copy
# through the same contextvar machinery the execution policy uses.
_stage_started: ContextVar[tuple[str, float] | None] = ContextVar(
    "peritus_stage_started", default=None
)


# Events worth a log line of their own. The rest (per-source validation, per-batch
# graph progress) are high-volume and already visible in the durable event log —
# logging those too would bury the ones that matter.
_LOGGED_EVENTS = frozenset(
    {
        "stage",
        "plan_ready",
        "picture_ready",
        "picture_skipped",
        "discovery_started",
        "round_started",
        "canonical_resolved",
        "fetcher_retried",
        "floor_relaxed",
        "composition_capped",
        "feedback_queries",
        "dedup_done",
        "triage_done",
        "fetch_done",
        "validate_done",
        "coverage_report",
        "discovery_done",
        "snowball_done",
        "corpus_warning",
        "chat_ready",
        "graph_ready",
        "entities_resolved",
        "claims_reconciled",
        "build_resumed",
        "persona_ready",
        "stage_degraded",
        "error",
        "cancelled",
        "done",
    }
)


def _clip(value: Any, limit: int = 160) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}…(+{len(text) - limit} chars)"


def _log_event(event: dict) -> None:
    """Mirror significant build events into the process log.

    The durable event log is per-job and only readable through the API, which is
    exactly the wrong place to look when the question is "what was this worker
    doing when it died". These lines put the build's shape into the same stream
    as the errors, so a worker log alone tells the story.
    """
    kind = event.get("type")
    if kind not in _LOGGED_EVENTS:
        return

    if kind == "stage":
        now = time.monotonic()
        previous = _stage_started.get()
        if previous:
            logger.info("Stage %r finished in %.1fs", previous[0], now - previous[1])
        name = str(event.get("name", "?"))
        _stage_started.set((name, now))
        logger.info("── Stage %d: %s ──", event.get("stage", -1), name)
        return

    # Values are model output (concept lists, warning prose) and can run to
    # hundreds of characters. Truncated per field so one verbose event cannot
    # push a whole build's worth of real log lines off the screen.
    detail = ", ".join(f"{k}={_clip(v)}" for k, v in event.items() if k != "type")
    if kind in ("error", "cancelled"):
        logger.error("Build event %s: %s", kind, detail)
    elif kind in ("stage_degraded", "corpus_warning"):
        logger.warning("Build event %s: %s", kind, detail)
    else:
        logger.info("Build event %s: %s", kind, detail)
