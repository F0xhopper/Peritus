"""Bring an existing expert's corpus up to what a new build ingests.

    python scripts/backfill_corpus.py 63 --backup-dir DIR            # dry run
    python scripts/backfill_corpus.py 63 --backup-dir DIR --apply    # write

Three steps, each what the build now does at ingest time
(docs/plans/beating-closed-book.md, phase 3):

1. **Prose gate** (``ingestion/quality.py``) over the stored chunks: chunks that
   are not prose — Latin and Old English editions, reference lists, page
   chrome — are deleted. Every deleted row (text, note, metadata; not the
   vector) is written to ``--backup-dir`` first.
2. **Loci** (``ingestion/structural.annotate_loci``) read from the stored chunks
   in order and written to ``chunk_meta.locus``, so citation labels carry "I,
   q. 2, a. 3" without a rebuild.
3. **Tails** (``ingestion/structural.ingest_tails``): every long work that was
   cut at its ceiling is fetched again, whole, through the same fetcher that
   found it, and the best of what the cut left — by nearness to the expert's
   key concepts, within the tier's budget — is held embed-only.
4. **Section summaries** (``ingestion/summaries.build_section_index``, phase
   4): the routing index broad questions search. Last, so the tails get
   summaries too. Idempotent — sources already indexed are skipped.

Run with CHUNK_SIZE_CHARS=1000 (production's value) if the local .env says
otherwise; the script refuses to hold a tail at any other chunk size.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from peritus.core.config import settings
from peritus.experts.build.constants import _STRUCTURAL_TAIL_CHARS
from peritus.experts.service import ExpertService
from peritus.infrastructure.database import get_pool, init_pool
from peritus.ingestion.chunker import TextChunk
from peritus.ingestion.quality import chunk_rejection
from peritus.ingestion.structural import TailWork, annotate_loci, ingest_tails
from peritus.ingestion.summaries import build_section_index
from peritus.sources.canonical import ArchiveTextFetcher
from peritus.sources.domain import RawSource, SourceCandidate, SourceType
from peritus.sources.fetchers.gutenberg import GutenbergFetcher

# A stored text at this length was cut at the 200,000-character ceiling.
_CUT_AT = 199_000
_PRODUCTION_CHUNK_CHARS = 1000


async def prose_gate(pool, expert_id: int, backup: Path, apply: bool) -> int:
    rows = await pool.fetch(
        "SELECT id, source_id, sequence_n, text, context_text, chunk_meta "
        "FROM source_chunks WHERE expert_id = $1",
        expert_id,
    )
    junk = [(r, why) for r in rows if (why := chunk_rejection(r["text"]))]
    by_reason: dict[str, int] = {}
    for _, why in junk:
        by_reason[why] = by_reason.get(why, 0) + 1
    print(f"prose gate: {len(junk)} of {len(rows)} chunks are not prose {by_reason}")
    await asyncio.to_thread(
        backup.write_text,
        json.dumps(
            [
                {
                    "id": r["id"],
                    "source_id": r["source_id"],
                    "sequence_n": r["sequence_n"],
                    "reason": why,
                    "text": r["text"],
                    "context_text": r["context_text"],
                    "chunk_meta": r["chunk_meta"],
                }
                for r, why in junk
            ],
            indent=1,
        ),
    )
    if apply and junk:
        await pool.execute(
            "DELETE FROM source_chunks WHERE id = ANY($1::int[])", [r["id"] for r, _ in junk]
        )
    return len(junk)


async def loci(pool, expert_id: int, apply: bool) -> int:
    rows = await pool.fetch(
        "SELECT id, source_id, sequence_n, text, chunk_meta FROM source_chunks "
        "WHERE expert_id = $1 ORDER BY source_id, sequence_n",
        expert_id,
    )
    by_source: dict[int, list] = {}
    for r in rows:
        by_source.setdefault(r["source_id"], []).append(r)
    updates = []
    for chunks in by_source.values():
        texts = [
            TextChunk(text=r["text"], sequence_n=r["sequence_n"], chunk_meta={}) for r in chunks
        ]
        annotate_loci(texts)
        for r, t in zip(chunks, texts, strict=True):
            extra = {k: t.chunk_meta[k] for k in ("locus", "article") if k in t.chunk_meta}
            if extra:
                updates.append((r["id"], json.dumps(extra)))
    print(f"loci: {len(updates)} of {len(rows)} chunks get a locus")
    if apply and updates:
        await pool.executemany(
            "UPDATE source_chunks SET chunk_meta = coalesce(chunk_meta, '{}'::jsonb) || $2::jsonb "
            "WHERE id = $1",
            updates,
        )
    return len(updates)


async def refetch(row) -> RawSource | None:
    method, url = row["full_text_method"], row["url"]
    if method == "gutenberg_text":
        book_id = int(url.rstrip("/").rsplit("/", 1)[-1])
        candidate = SourceCandidate(
            SourceType.GUTENBERG, url, row["title"], None, "", {"gutenberg_id": book_id}
        )
        return await GutenbergFetcher().fetch(candidate)
    if method == "archive_djvu_text":
        candidate = SourceCandidate(SourceType.WEB, url, row["title"], None, "", {})
        return await ArchiveTextFetcher().fetch(candidate)
    return None


async def tails(pool, expert, apply: bool) -> None:
    if settings.CHUNK_SIZE_CHARS != _PRODUCTION_CHUNK_CHARS:
        raise SystemExit(
            f"CHUNK_SIZE_CHARS is {settings.CHUNK_SIZE_CHARS}; run with "
            f"CHUNK_SIZE_CHARS={_PRODUCTION_CHUNK_CHARS} to match production."
        )
    rows = await pool.fetch(
        "SELECT s.id, s.title, s.url, s.full_text_method, s.text_chars, "
        "(SELECT max(sequence_n) FROM source_chunks c WHERE c.source_id = s.id) AS last_seq, "
        "(SELECT count(*) FROM source_chunks c WHERE c.source_id = s.id "
        " AND c.chunk_meta->>'ingest' = 'structural') AS held "
        "FROM sources s WHERE s.expert_id = $1 AND s.passed AND s.text_chars >= $2",
        expert.id,
        _CUT_AT,
    )
    works: list[TailWork] = []
    for row in rows:
        if row["held"]:
            print(f"  [{row['id']}] {row['title'][:60]}: tail already held, skipping")
            continue
        raw = await refetch(row)
        if raw is None or not raw.full_text:
            print(f"  [{row['id']}] {row['title'][:60]}: no longer text to hold")
            continue
        # Where the close-read text ended: the stored text was a prefix of this
        # fetch, cut at the ceiling.
        close_end = min(len(raw.full_text), int(row["text_chars"]))
        print(
            f"  [{row['id']}] {row['title'][:60]}: {len(raw.full_text):,} chars whole, "
            f"{close_end:,} read closely"
        )
        works.append(
            TailWork(
                source_id=row["id"],
                title=row["title"],
                full_text=raw.full_text,
                close_spans=[(0, close_end)],
                next_seq=(row["last_seq"] or 0) + 1,
            )
        )
    budget = _STRUCTURAL_TAIL_CHARS[expert.tier]
    print(f"tails: {len(works)} work(s), budget {budget:,} chars")
    if not works or not apply:
        return
    report = await ingest_tails(
        pool, expert.id, works, [expert.topic, *expert.key_concepts], budget
    )
    print(f"tails: held {report.summary()}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("expert", type=int)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--skip", action="append", default=[], choices=["gate", "loci", "tails", "summaries"]
    )
    args = parser.parse_args()
    args.backup_dir.mkdir(parents=True, exist_ok=True)

    await init_pool()
    pool = get_pool()
    expert = await ExpertService(pool).get(args.expert)
    print(f"Expert {expert.id} {expert.topic!r} ({expert.tier})")
    if "gate" not in args.skip:
        await prose_gate(pool, expert.id, args.backup_dir / f"dropped-{expert.id}.json", args.apply)
    if "tails" not in args.skip:
        await tails(pool, expert, args.apply)
    if "loci" not in args.skip:
        await loci(pool, expert.id, args.apply)
    if "summaries" not in args.skip:
        if args.apply:
            written = await build_section_index(pool, expert.id)
            print(f"summaries: {written} section(s) indexed")
        else:
            print("summaries: would index every source not yet indexed")
    if args.apply:
        await pool.execute(
            "UPDATE experts SET chunk_count = (SELECT count(*) FROM source_chunks "
            "WHERE expert_id = $1) WHERE id = $1",
            expert.id,
        )
    else:
        print("Dry run: nothing written. Pass --apply to write.")


if __name__ == "__main__":
    asyncio.run(main())
