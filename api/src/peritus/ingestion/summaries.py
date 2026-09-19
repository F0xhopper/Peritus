"""Section summaries — a routing index over the corpus, for broad questions.

"Who was the most impactful king?" has no passage that answers it; every
passage scores low, and the top ten chunks by rerank are whichever annals
happened to say "king" most. What the question needs is the corpus seen from
above: which parts of which works are about kings, and their best passages
(docs/plans/beating-closed-book.md §3.4, phase 4).

So a build writes one short summary per *section* — a run of consecutive chunks
of one source sharing a heading, at most ``MAX_RUN`` chunks — saying what the
section establishes: the names, dates, positions and arguments in it. Each is
embedded. A broad question searches the summaries, takes the best sections
across distinct sources, and seats each section's best chunks
(``chat/agent.py``). **Summaries find, passages prove**: a summary is never
shown to the answering model and never cited; it routes to the real text.

Structural tails (``structural.py``) get summaries too — this is how a question
finds its way into a part of a work nobody contextualised.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import asyncpg

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_batch import gather_claude_calls
from peritus.infrastructure.embeddings import embed_in_batches
from peritus.search.labels import citation_title, section_heading

logger = get_logger(__name__)

#: The most chunks one section spans. A "section" the chunker could not name
#: ("Full Text") is a whole source; cut into windows of this size, each is a
#: few pages — enough to say what it is about in 120 words.
MAX_RUN = 12
#: A run shorter than this joins the run before it in the same source.
MIN_RUN = 3
#: How much of a section the summariser reads.
_SUMMARY_INPUT_CHARS = 12_000

_SYSTEM = (
    "You index a section of a source for a search engine that routes broad "
    "questions to it. In about 120 words, say what this section establishes: the "
    "people, places, dates, positions, arguments and findings in it, by name. "
    "Plain declarative sentences about the subject, no preamble, never 'this "
    "section' or 'the author discusses' — write what it says."
)


@dataclass
class Run:
    source_id: int
    title: str
    section: str
    seq_start: int
    seq_end: int
    texts: list[str]


def section_key(meta: dict) -> str:
    """The heading a chunk belongs under, for grouping into sections."""
    return str(meta.get("heading") or meta.get("section") or "").strip()


def section_runs(rows: list[dict]) -> list[Run]:
    """Group chunk rows (one expert, ordered by source and sequence) into runs.

    A run breaks at a change of source or heading, at a gap in the sequence,
    and every ``MAX_RUN`` chunks. Then a run under ``MIN_RUN`` joins its
    neighbour in the same source — the one before it when that is contiguous,
    else the one after — so a stray heading does not become a section.
    """
    runs: list[Run] = []
    for row in rows:
        meta = row.get("chunk_meta") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        key = section_key(meta)
        last = runs[-1] if runs else None
        if (
            last is not None
            and last.source_id == row["source_id"]
            and last.section == key
            and row["sequence_n"] == last.seq_end + 1
            and len(last.texts) < MAX_RUN
        ):
            last.seq_end = row["sequence_n"]
            last.texts.append(row["text"])
            continue
        runs.append(
            Run(
                source_id=row["source_id"],
                title=row["title"],
                section=key,
                seq_start=row["sequence_n"],
                seq_end=row["sequence_n"],
                texts=[row["text"]],
            )
        )

    def joinable(a: Run, b: Run) -> bool:
        return a.source_id == b.source_id and b.seq_start - a.seq_end <= 2

    merged: list[Run] = []
    for run in runs:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and joinable(prev, run)
            and (len(run.texts) < MIN_RUN or len(prev.texts) < MIN_RUN)
        ):
            prev.seq_end = run.seq_end
            prev.texts += run.texts
            if len(prev.texts) - len(run.texts) < len(run.texts):
                prev.section = run.section or prev.section
            continue
        merged.append(run)
    return merged


def _label(run: Run) -> str:
    work = citation_title(run.title)
    heading = section_heading(run.section, work, max_chars=100, max_words=14)
    return f"{work} — {heading}" if heading else work


def _params(run: Run) -> dict[str, Any]:
    body = "\n\n".join(run.texts)[:_SUMMARY_INPUT_CHARS]
    return {
        "model": settings.FAST_MODEL,
        "max_tokens": 400,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": f"Source: {_label(run)}\n\n{body}"}],
    }


async def build_section_index(pool: asyncpg.Pool, expert_id: int) -> int:
    """Summarise and embed every section of an expert's corpus not yet indexed.

    Idempotent: sources that already have sections are skipped, so a resumed
    build or a backfill adds only what is missing. Returns sections written.
    """
    rows = await pool.fetch(
        """
        SELECT sc.source_id, sc.sequence_n, sc.text, sc.chunk_meta, s.title
        FROM source_chunks sc JOIN sources s ON s.id = sc.source_id
        WHERE sc.expert_id = $1
          AND NOT EXISTS (SELECT 1 FROM corpus_sections cs WHERE cs.source_id = sc.source_id)
        ORDER BY sc.source_id, sc.sequence_n
        """,
        expert_id,
    )
    runs = section_runs([dict(r) for r in rows])
    if not runs:
        return 0
    responses = await gather_claude_calls(
        [_params(r) for r in runs], live_concurrency=8, description="section-summaries"
    )
    summaries: list[tuple[Run, str]] = []
    for run, resp in zip(runs, responses, strict=True):
        text = "".join(getattr(b, "text", "") for b in (resp.content if resp else [])).strip()
        if text:
            summaries.append((run, text))
    if not summaries:
        return 0
    embeddings = await embed_in_batches([f"{_label(r)}\n{s}" for r, s in summaries])
    from pgvector.asyncpg import register_vector  # type: ignore

    async with pool.acquire() as conn:
        await register_vector(conn)
        await conn.executemany(
            """
            INSERT INTO corpus_sections
                (expert_id, source_id, section, seq_start, seq_end, summary, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            [
                (expert_id, r.source_id, r.section, r.seq_start, r.seq_end, s, emb)
                for (r, s), emb in zip(summaries, embeddings, strict=True)
            ],
        )
    logger.info("Indexed %d section(s) for expert %d", len(summaries), expert_id)
    return len(summaries)


@dataclass
class SectionHit:
    source_id: int
    seq_start: int
    seq_end: int
    score: float


async def search_sections(
    pool: asyncpg.Pool,
    expert_id: int,
    query_embeddings: list[list[float]],
    k: int,
) -> list[SectionHit]:
    """The ``k`` best sections for any of the queries, at most one per source.

    Distinct sources is the point: a broad question answered from one
    chronicle is the failure this exists to fix.
    """
    if not query_embeddings:
        return []
    # As text, cast in SQL: the pgvector codec encodes one vector per
    # parameter, not an array of them.
    vectors = ["[" + ",".join(repr(float(x)) for x in v) + "]" for v in query_embeddings]
    async with pool.acquire(timeout=settings.DB_ACQUIRE_TIMEOUT) as conn:
        rows = await conn.fetch(
            """
            SELECT cs.source_id, cs.seq_start, cs.seq_end,
                   max(1 - (cs.embedding <=> q.v::vector)) AS score
            FROM corpus_sections cs, unnest($2::text[]) AS q(v)
            WHERE cs.expert_id = $1 AND cs.embedding IS NOT NULL
            GROUP BY cs.id
            ORDER BY score DESC
            LIMIT $3
            """,
            expert_id,
            vectors,
            k * 6,
        )
    hits: list[SectionHit] = []
    seen: set[int] = set()
    for r in rows:
        if r["source_id"] in seen:
            continue
        seen.add(r["source_id"])
        hits.append(SectionHit(r["source_id"], r["seq_start"], r["seq_end"], float(r["score"])))
        if len(hits) >= k:
            break
    return hits
