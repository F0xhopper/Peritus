"""Retrieval golden set: generate it from an expert's own chunks, then measure recall.

No retrieval change could be shown to move recall, because no golden set had
real chunk ids — the example sets carry placeholders. This builds one per expert
the standard synthetic way: sample prose chunks, ask the fast model for a
question each chunk answers on its own, and record the chunk as the answer.

Matched by content, not by id. The changes this exists to measure (chunk size,
chunk hygiene) only take effect on a rebuild, and a rebuild deletes every chunk
and source id. So each gold item carries its passage text and source URL, and a
retrieved chunk counts as a hit when the two overlap — word-shingle
containment in either direction, so a 1,500-char gold passage re-chunked into
two 1,000-char halves still matches either half.

Retrieval only: plan → hybrid search → rerank, no graph expansion and no
composition, so a run costs the planner call, embeddings and one rerank per
question.

Usage:
    python -m peritus.eval.retrieval generate thomism --n 80
    python -m peritus.eval.retrieval run thomism [path] [--k 10]
    python -m peritus.eval.retrieval audits thomism        # weak labels, free
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import asyncpg

from peritus.chat.agent import ChatAgent
from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.domain import Expert
from peritus.infrastructure.anthropic_batch import gather_claude_calls
from peritus.infrastructure.anthropic_client import tool_input

logger = get_logger(__name__)

GOLDEN_DIR = Path(__file__).parent / "golden" / "retrieval"

#: A retrieved chunk "is" the gold passage when this share of one's word
#: 5-shingles appear in the other.
MATCH_CONTAINMENT = 0.5
_SHINGLE = 5
_CHUNKS_PER_CALL = 8
_MIN_PROSE_CHARS = 400


@dataclass
class GoldItem:
    question: str
    chunk_id: int
    source_id: int
    source_url: str | None
    source_title: str
    text: str


@dataclass
class ItemResult:
    question: str
    hit_rank: int | None  # 1-based rank of the first matching chunk
    source_hit: bool  # any chunk from the gold source in the top k


@dataclass
class RetrievalReport:
    expert: str
    n: int
    k: int
    recall_at_k: float
    mrr: float
    source_recall_at_k: float
    per_question: list[ItemResult] = field(default_factory=list)


# ── matching ────────────────────────────────────────────────────────────────


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.casefold())
    if len(words) < _SHINGLE:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + _SHINGLE]) for i in range(len(words) - _SHINGLE + 1)}


def same_passage(gold_text: str, retrieved_text: str) -> bool:
    """Whether a retrieved chunk carries the gold passage, across re-chunking."""
    gold, got = _shingles(gold_text), _shingles(retrieved_text)
    if not gold or not got:
        return False
    shared = len(gold & got)
    return max(shared / len(gold), shared / len(got)) >= MATCH_CONTAINMENT


def score(
    items: list[GoldItem], retrieved: list[list[tuple[str, str | None]]], k: int
) -> RetrievalReport:
    """Recall@k, MRR and source recall@k. ``retrieved[i]`` is ``(text, source_url)``
    per ranked chunk for ``items[i]``. Pure, so the metric is testable."""
    results: list[ItemResult] = []
    for item, ranked in zip(items, retrieved, strict=True):
        top = ranked[:k]
        hit_rank = next(
            (i + 1 for i, (text, _) in enumerate(top) if same_passage(item.text, text)), None
        )
        source_hit = item.source_url is not None and any(url == item.source_url for _, url in top)
        results.append(ItemResult(item.question, hit_rank, source_hit or hit_rank is not None))
    n = len(results) or 1
    return RetrievalReport(
        expert="",
        n=len(results),
        k=k,
        recall_at_k=round(sum(r.hit_rank is not None for r in results) / n, 4),
        mrr=round(sum(1 / r.hit_rank for r in results if r.hit_rank) / n, 4),
        source_recall_at_k=round(sum(r.source_hit for r in results) / n, 4),
        per_question=results,
    )


# ── generation ──────────────────────────────────────────────────────────────

_TOOL: dict[str, Any] = {
    "name": "write_questions",
    "description": "One question per passage that the passage alone answers.",
    "input_schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "question": {
                            "type": ["string", "null"],
                            "description": "Null when the passage answers nothing on its own.",
                        },
                    },
                    "required": ["index", "question"],
                },
            },
        },
        "required": ["questions"],
    },
}

_SYSTEM = (
    "You write evaluation questions for a search engine over a corpus about {topic}. "
    "For each numbered passage, write one question that a curious person might ask and "
    "that this passage answers on its own. Ask about the subject, in the asker's words, "
    "never about 'the passage' or 'the author', and do not copy distinctive phrases from "
    "it — a question that repeats the passage's wording tests string matching, not "
    "retrieval. Return null for a passage that is not self-contained prose (a list of "
    "references, a caption, a fragment)."
)


async def sample_chunks(pool: asyncpg.Pool, expert_id: int, n: int, seed: int) -> list[dict]:
    """Prose chunks spread across sources: at most ceil(n / sources) from each."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT sc.id, sc.source_id, sc.text, s.url, s.title
            FROM source_chunks sc JOIN sources s ON s.id = sc.source_id
            WHERE sc.expert_id = $1 AND length(sc.text) >= $2
            """,
            expert_id,
            _MIN_PROSE_CHARS,
        )
    rng = random.Random(seed)
    by_source: dict[int, list[dict]] = {}
    for r in rows:
        by_source.setdefault(r["source_id"], []).append(dict(r))
    for chunks in by_source.values():
        rng.shuffle(chunks)
    picked: list[dict] = []
    while len(picked) < n and any(by_source.values()):
        for chunks in list(by_source.values()):
            if chunks and len(picked) < n:
                picked.append(chunks.pop())
    return picked


async def generate(
    pool: asyncpg.Pool, expert: Expert, n: int = 80, seed: int = 7
) -> list[GoldItem]:
    chunks = await sample_chunks(pool, expert.id, n, seed)
    batches = [chunks[i : i + _CHUNKS_PER_CALL] for i in range(0, len(chunks), _CHUNKS_PER_CALL)]
    params = [
        {
            "model": settings.FAST_MODEL,
            "max_tokens": 1024,
            "system": _SYSTEM.format(topic=expert.topic),
            "tools": [_TOOL],
            "tool_choice": {"type": "tool", "name": "write_questions"},
            "messages": [
                {
                    "role": "user",
                    "content": "\n\n".join(f"[{i}] {c['text']}" for i, c in enumerate(batch)),
                }
            ],
        }
        for batch in batches
    ]
    responses = await gather_claude_calls(params, description="retrieval-golden")
    items: list[GoldItem] = []
    for batch, resp in zip(batches, responses, strict=True):
        payload = tool_input(resp) if resp else None
        for q in (payload or {}).get("questions", []):
            idx, question = q.get("index"), q.get("question")
            if not isinstance(idx, int) or not 0 <= idx < len(batch):
                continue
            if not isinstance(question, str) or not question.strip():
                continue
            c = batch[idx]
            items.append(
                GoldItem(
                    question=question.strip(),
                    chunk_id=c["id"],
                    source_id=c["source_id"],
                    source_url=c["url"],
                    source_title=c["title"],
                    text=c["text"],
                )
            )
    return items


async def from_audits(pool: asyncpg.Pool, expert_id: int, limit: int = 200) -> list[GoldItem]:
    """Weak labels that grow for free: each audited question and a passage it cited.

    Weak because "the answer cited it" is not "it was the passage to find" —
    use it to watch for regressions, not to report recall as a number.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.question, p.chunk_id, p.source_id, s.url, p.source_title, sc.text
            FROM answer_audits a
            JOIN answer_audit_passages p ON p.audit_id = a.id AND p.disposition = 'cited'
            JOIN source_chunks sc ON sc.id = p.chunk_id
            JOIN sources s ON s.id = p.source_id
            WHERE a.expert_id = $1
            ORDER BY a.created_at DESC, p.retrieval_rank
            LIMIT $2
            """,
            expert_id,
            limit,
        )
    return [
        GoldItem(
            r["question"], r["chunk_id"], r["source_id"], r["url"], r["source_title"], r["text"]
        )
        for r in rows
    ]


# ── running ─────────────────────────────────────────────────────────────────


async def run(
    pool: asyncpg.Pool,
    expert: Expert,
    items: list[GoldItem],
    k: int = 10,
    pace: float = 0.0,
) -> RetrievalReport:
    """``pace`` spaces questions that many seconds apart, one at a time.

    A Cohere trial key allows 10 rerank calls a minute; past that, `rerank`
    falls back to Haiku windows, which score differently — a run that trips the
    limit measures two rerankers at once and is not comparable to another run.
    """
    agent = ChatAgent(pool)
    cfg = expert.config
    sem = asyncio.Semaphore(1 if pace else 4)

    async def one(item: GoldItem) -> list[tuple[str, int]]:
        async with sem:
            if pace:
                await asyncio.sleep(pace)
            # As `ChatAgent.retrieve` calls it, so the eval measures the planner
            # that answers are actually planned with.
            plan = await agent._plan(
                item.question, expert.topic, cfg.max_subqueries, None, expert.key_concepts
            )
            resp = await agent._search.batch_search(
                expert_id=expert.id,
                question=plan.standalone_question or item.question,
                queries=plan.subqueries,
                top_k=max(k, cfg.retrieval_top_k),
                topic=expert.topic,
            )
        return [(r.text, r.source_id) for r in resp.results]

    ranked = await asyncio.gather(*(one(item) for item in items))
    urls = await _source_urls(pool, {sid for hits in ranked for _, sid in hits})
    retrieved = [[(text, urls.get(sid)) for text, sid in hits] for hits in ranked]
    report = score(items, retrieved, k)
    report.expert = expert.name
    return report


async def _source_urls(pool: asyncpg.Pool, source_ids: set[int]) -> dict[int, str | None]:
    if not source_ids:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, url FROM sources WHERE id = ANY($1)", list(source_ids))
    return {r["id"]: r["url"] for r in rows}


def save(items: list[GoldItem], path: Path, expert: Expert) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"expert": expert.name, "topic": expert.topic, "items": [asdict(i) for i in items]},
            indent=2,
            ensure_ascii=False,
        )
    )


def load(path: Path) -> list[GoldItem]:
    return [GoldItem(**i) for i in json.loads(path.read_text())["items"]]


async def _main(argv: list[str] | None = None) -> None:
    from peritus.experts.service import ExpertService
    from peritus.infrastructure.database import get_pool, init_pool

    parser = argparse.ArgumentParser(prog="python -m peritus.eval.retrieval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate", help="Write a golden set from the expert's chunks")
    gen.add_argument("expert")
    gen.add_argument("--n", type=int, default=80)
    gen.add_argument("--seed", type=int, default=7)
    gen.add_argument("--out", type=Path)
    run_p = sub.add_parser("run", help="Measure recall@k and MRR against a golden set")
    run_p.add_argument("expert")
    run_p.add_argument("path", type=Path, nargs="?")
    run_p.add_argument("--k", type=int, default=10)
    run_p.add_argument(
        "--pace",
        type=float,
        default=0.0,
        help="Seconds between questions (6.5 keeps a Cohere trial key under 10/min)",
    )
    aud = sub.add_parser("audits", help="Measure against cited passages from the audit trail")
    aud.add_argument("expert")
    aud.add_argument("--k", type=int, default=10)
    aud.add_argument("--pace", type=float, default=0.0)
    args = parser.parse_args(argv)

    await init_pool()
    pool = get_pool()
    expert = await ExpertService(pool).get(args.expert)
    default_path = GOLDEN_DIR / f"{expert.name}.json"

    if args.cmd == "generate":
        items = await generate(pool, expert, args.n, args.seed)
        out = args.out or default_path
        save(items, out, expert)
        print(f"Wrote {len(items)} questions to {out}")
        return

    items = (
        load(args.path or default_path) if args.cmd == "run" else await from_audits(pool, expert.id)
    )
    report = await run(pool, expert, items, args.k, args.pace)
    summary = {k: v for k, v in asdict(report).items() if k != "per_question"}
    print(json.dumps(summary, indent=2))
    misses = [r.question for r in report.per_question if r.hit_rank is None]
    if misses:
        print(f"\n{len(misses)} question(s) with no matching passage in the top {args.k}:")
        for q in misses[:20]:
            print(f"  - {q}")


if __name__ == "__main__":
    asyncio.run(_main())
