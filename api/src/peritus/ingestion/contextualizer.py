"""Contextual retrieval — situate each chunk within its source before indexing.

Chunks are contextualised in batches of 5 per Claude call. All calls — across
every source in a build — are executed through
:func:`peritus.infrastructure.anthropic_batch.gather_claude_calls`, so when the
Message Batches API is enabled the whole stage runs at half price in a single
submitted batch.
"""

from dataclasses import dataclass
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_batch import gather_claude_calls
from peritus.ingestion.chunker import TextChunk

logger = get_logger(__name__)

_CONTEXT_BATCH_SIZE = 5  # chunks per API call

_SYSTEM = (
    "You situate text excerpts within their source document so they can be accurately "
    "retrieved by a search engine. For each chunk, reply with one or two sentences only — "
    "no preamble, no quotation, no commentary."
)

_BATCH_TOOL: dict[str, Any] = {
    "name": "contextualize_chunks",
    "description": "Generate a short retrieval context for each chunk, in order.",
    "input_schema": {
        "type": "object",
        "properties": {
            "contexts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1–2 sentence retrieval context per chunk, same order as input.",
            }
        },
        "required": ["contexts"],
    },
}

_INSTRUCTION = (
    "For each numbered chunk above, write 1–2 sentences that situate it within the source "
    "so a search engine can retrieve it accurately. Name the source and specific topic "
    "where relevant. Return exactly one string per chunk in the contexts array."
)

# How much of the document to show as the local window around a batch, split
# between text before and after the batch's span.
_DOC_HEAD_CHARS = 800  # always-included framing so the model knows what the source is


@dataclass
class ContextJob:
    """One source's chunks awaiting contextualisation."""
    chunks: list[TextChunk]
    source_title: str
    source_text: str


def _locate_offsets(source_text: str, chunks: list[TextChunk]) -> list[int]:
    """Best-effort character offset of each chunk within the source, in order.

    Chunks are emitted in document order, so we scan forward from the previous
    match. Falls back to the running cursor when a chunk can't be located (e.g.
    whitespace normalisation), which keeps windows monotonic rather than correct
    to the character — good enough to situate a chunk in the right region.
    """
    offsets: list[int] = []
    cursor = 0
    for c in chunks:
        probe = c.text[:120]
        idx = source_text.find(probe, cursor) if probe else -1
        if idx == -1 and probe:
            idx = source_text.find(probe)
        if idx == -1:
            idx = cursor
        offsets.append(idx)
        cursor = max(cursor, idx + len(c.text))
    return offsets


def _job_params(job: ContextJob) -> list[tuple[dict[str, Any], int]]:
    """Build (request_params, batch_len) for every 5-chunk batch of one job."""
    offsets = _locate_offsets(job.source_text, job.chunks)
    doc_head = job.source_text[:_DOC_HEAD_CHARS]
    half_window = max(settings.CONTEXT_MAX_CHARS // 2, _DOC_HEAD_CHARS)

    def _window_for(start_idx: int, batch: list[TextChunk]) -> str:
        first_off = offsets[start_idx]
        last = start_idx + len(batch) - 1
        last_end = offsets[last] + len(batch[-1].text)
        win_start = max(0, first_off - half_window)
        win_end = min(len(job.source_text), last_end + half_window)
        window = job.source_text[win_start:win_end]
        # Prepend the document head when the window doesn't already include it, so
        # even late chunks are framed by what the source actually is.
        if win_start > _DOC_HEAD_CHARS:
            return f"{doc_head}\n…\n{window}"
        return window

    params: list[tuple[dict[str, Any], int]] = []
    for start in range(0, len(job.chunks), _CONTEXT_BATCH_SIZE):
        batch = job.chunks[start: start + _CONTEXT_BATCH_SIZE]
        surrounding = _window_for(start, batch)
        prompt = (
            f"<source_title>{job.source_title}</source_title>\n"
            f"<surrounding_text>\n{surrounding}\n</surrounding_text>\n\n"
            + "\n\n".join(f"<chunk_{i}>\n{c.text}\n</chunk_{i}>" for i, c in enumerate(batch))
            + f"\n\n{_INSTRUCTION}"
        )
        params.append((
            {
                "model": settings.FAST_MODEL,
                "max_tokens": 150 * len(batch),
                "system": _SYSTEM,
                "tools": [_BATCH_TOOL],
                "tool_choice": {"type": "tool", "name": "contextualize_chunks"},
                "messages": [{"role": "user", "content": prompt}],
            },
            len(batch),
        ))
    return params


def _parse_contexts(resp: Any, batch_len: int) -> list[str]:
    block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
    contexts = list(block.input.get("contexts", []))
    while len(contexts) < batch_len:
        contexts.append("")
    return contexts[:batch_len]


async def contextualize_sources(jobs: list[ContextJob]) -> list[list[str]]:
    """Contextualise every job's chunks. Returns one context list per job, in order.

    All batches across all jobs go through a single ``gather_claude_calls`` so
    the Message Batches API can price the entire stage at 50%.
    """
    if not jobs:
        return []
    if not settings.CONTEXT_ENABLED or not settings.ANTHROPIC_API_KEY:
        return [["" for _ in job.chunks] for job in jobs]

    # Flatten: remember how many batches each job contributed.
    all_params: list[dict[str, Any]] = []
    batch_lens: list[int] = []
    job_batch_counts: list[int] = []
    for job in jobs:
        job_params = _job_params(job)
        job_batch_counts.append(len(job_params))
        for params, batch_len in job_params:
            all_params.append(params)
            batch_lens.append(batch_len)

    responses = await gather_claude_calls(
        all_params,
        live_concurrency=settings.CONTEXT_CONCURRENCY,
        description="contextualize",
    )

    flat_contexts: list[list[str]] = []
    for resp, batch_len in zip(responses, batch_lens, strict=True):
        if resp is None:
            flat_contexts.append(["" for _ in range(batch_len)])
            continue
        try:
            flat_contexts.append(_parse_contexts(resp, batch_len))
        except Exception as exc:
            logger.warning("Contextualisation batch unparseable (%d chunks): %s", batch_len, exc)
            flat_contexts.append(["" for _ in range(batch_len)])

    # Regroup per job.
    results: list[list[str]] = []
    cursor = 0
    for job, n_batches in zip(jobs, job_batch_counts, strict=True):
        contexts = [
            ctx
            for batch_ctxs in flat_contexts[cursor: cursor + n_batches]
            for ctx in batch_ctxs
        ]
        cursor += n_batches
        filled = sum(1 for c in contexts if c)
        logger.info(
            "Contextualised %d/%d chunks for %r", filled, len(job.chunks), job.source_title,
        )
        results.append(contexts)
    return results


async def contextualize_chunks(
    chunks: list[TextChunk],
    source_title: str,
    source_text: str,
) -> list[str]:
    """Single-source convenience wrapper around :func:`contextualize_sources`."""
    if not chunks:
        return []
    [contexts] = await contextualize_sources(
        [ContextJob(chunks=chunks, source_title=source_title, source_text=source_text)]
    )
    return contexts
