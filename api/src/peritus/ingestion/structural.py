"""Structural ingestion — the rest of a long work, held and findable, not read closely.

Every long work used to be cut at 200,000 characters, from the front. Expert 63
held the Prima Pars to question 10 of 119, the I-II to question 12 of 114 (law,
virtue, sin and grace all absent), the *Nicomachean Ethics* to Book IV. A
frontier model has the whole canon in memory; an expert holding a tenth of one
book of it cannot out-answer that model on the other nine tenths, and no
retrieval change helps (docs/plans/beating-closed-book.md §3.1).

The ceiling was priced as if every character cost the same, and they do not:
embedding is about $0.003 of the $0.27 per 100,000 characters an ingest costs.
The rest is per-chunk model work — the contextual note and graph extraction. A
canonical work is exactly the text that least needs a model-written note,
because its structure *is* its context: "Summa Theologica, Part I › I, q. 75,
a. 1 › Whether the soul is a body?" says more than a generated sentence.

So the part of a work past the close-read ceiling is ingested **embed-only**:
chunked and cleaned as usual, gated for prose (``quality.py``), given a
deterministic note built from its heading path, embedded, keyword-indexed — and
never contextualised or sent to graph extraction. Its chunks carry
``chunk_meta.ingest = "structural"`` so the build summary and the Knowledge page
can say what was read closely and what is merely held.

What bounds it is not money but storage: a chunk is ~29 KB in Postgres with
its 3,072-dimension vector and indexes, and the database is on a 500 MB plan. So
a build holds at most a per-tier budget of tail characters, and the tail
sections spent on are chosen by how near they sit to the expert's key concepts —
round-robin across concepts, so one concept cannot take the whole budget.

Loci (``chunk_meta.locus``: "I, q. 2, a. 3", "Book II, Chapter 3", "A.D. 878")
are read from the text as it is chunked, for close-read and structural chunks
alike, and lead the citation label (``search/labels.py``).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field

import asyncpg

from peritus.core.logging import get_logger
from peritus.infrastructure.embeddings import embed_in_batches
from peritus.ingestion.chunker import TextChunk, chunk_text
from peritus.ingestion.quality import chunk_rejection, is_prose
from peritus.search.labels import citation_title, section_heading
from peritus.sources.sections import find_sections

logger = get_logger(__name__)

INGEST_STRUCTURAL = "structural"

# ── Loci ─────────────────────────────────────────────────────────────────────

# The Gutenberg Summa marks every article: "FIRST ARTICLE [I, Q. 2, Art. 1]".
_SUMMA_ARTICLE = re.compile(
    r"\[(?P<part>[IVX]+(?:-[IVX]+)?|Suppl\.?),\s*Q\.\s*(?P<q>\d{1,3}),\s*Art\.\s*(?P<a>\d{1,2})\]"
)
_WHETHER = re.compile(r"(Whether\s[^\n?]{3,160}\?)")
# An annal entry: "A.D. 878." at the start of a line.
_ANNAL = re.compile(r"^\s*A\.\s?D\.\s*(?P<year>\d{2,4})\b", re.MULTILINE)
# "QUESTION 75", "CHAPTER XIII", "BOOK II", "LECTURE 7" on a line of their own.
_HEADING = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?P<kind>part|book|treatise|question|chapter|lecture|letter|"
    r"epistle|canto|sermon|discourse|meditation|lesson|article|section)s?\.?[ \t]+"
    r"(?P<num>\d{1,4}|[IVXLCDM]{1,8})\b[ \t.:]*(?:$|[A-Z])",
    re.IGNORECASE | re.MULTILINE,
)
_RANK = {
    "part": 1,
    "book": 1,
    "treatise": 2,
    "question": 3,
    "chapter": 3,
    "lecture": 3,
    "letter": 3,
    "epistle": 3,
    "canto": 3,
    "sermon": 3,
    "discourse": 3,
    "meditation": 3,
    "lesson": 3,
    "article": 4,
    "section": 4,
}


@dataclass
class _LocusState:
    """Where a reader is in a work, advanced chunk by chunk."""

    summa: str | None = None
    article: str | None = None
    annal: str | None = None
    headings: dict[int, str] = field(default_factory=dict)

    def locus(self) -> str | None:
        if self.summa:
            return self.summa
        if self.annal:
            return self.annal
        if self.headings:
            return ", ".join(self.headings[r] for r in sorted(self.headings)[-2:])
        return None

    def advance(self, text: str) -> list[int]:
        """Apply every locus event in ``text``; returns their offsets."""
        events: list[tuple[int, str, re.Match]] = []
        events += [(m.start(), "summa", m) for m in _SUMMA_ARTICLE.finditer(text)]
        events += [(m.start(), "annal", m) for m in _ANNAL.finditer(text)]
        events += [(m.start(), "heading", m) for m in _HEADING.finditer(text)]
        events.sort(key=lambda e: e[0])
        for _, kind, m in events:
            if kind == "summa":
                part = m.group("part").rstrip(".")
                self.summa = f"{part}, q. {m.group('q')}, a. {m.group('a')}"
                title = _WHETHER.search(text, m.end(), m.end() + 400)
                self.article = " ".join(title.group(1).split()) if title else None
            elif kind == "annal":
                self.annal = f"A.D. {m.group('year')}"
            else:
                word = m.group("kind").lower()
                rank = _RANK[word]
                num = m.group("num")
                num = num.upper() if not num.isdigit() else num
                self.headings = {r: v for r, v in self.headings.items() if r < rank}
                self.headings[rank] = f"{word.capitalize()} {num}"
                if rank <= 3:
                    # A new question or chapter leaves the previous article.
                    self.summa = None
                    self.article = None
        return [e[0] for e in events]


def annotate_loci(chunks: list[TextChunk]) -> None:
    """Set ``chunk_meta.locus`` (and ``article``) on chunks of one work, in order.

    A chunk takes the locus in effect where it starts — unless a new one begins
    in its first half, in which case most of the chunk belongs to that one.
    Works with no numbering get no locus, which the label treats as absent.
    """
    state = _LocusState()
    for chunk in chunks:
        before = (state.locus(), state.article)
        offsets = state.advance(chunk.text)
        if offsets and offsets[0] < len(chunk.text) / 2:
            locus, article = state.locus(), state.article
        elif before[0] is not None:
            locus, article = before
        else:
            locus, article = state.locus(), state.article
        if locus:
            chunk.chunk_meta["locus"] = locus
        if article:
            chunk.chunk_meta["article"] = article


def structural_note(title: str, chunk_meta: dict) -> str:
    """The note a structural chunk carries in place of a model-written one."""
    work = citation_title(title)
    parts = [p for p in (chunk_meta.get("locus"),) if p]
    heading = section_heading(chunk_meta.get("section"), work) or section_heading(
        chunk_meta.get("heading"), work, max_chars=100, max_words=_TITLE_WORDS
    )
    if heading:
        parts.append(heading)
    if chunk_meta.get("article"):
        parts.append(str(chunk_meta["article"]))
    note = f"From {work}" + (f" › {' › '.join(parts)}" if parts else "")
    return note if note[-1] in ".?!" else f"{note}."


# ── Tail segments ────────────────────────────────────────────────────────────

# A segment is the unit a tail is chosen in: one question, chapter or lecture.
_SEGMENT_KINDS = ("question", "chapter", "lecture", "letter", "sermon", "book", "part", "section")
_WINDOW_CHARS = 25_000
_MAX_SEGMENT_CHARS = 60_000
_MIN_SEGMENT_CHARS = 1_500
# What a segment is judged by: its heading and the start of its text.
_SCORE_CHARS = 1_500
# How much of a segment's opening the language check reads.
_LANGUAGE_PROBE_CHARS = 4_000


@dataclass
class Segment:
    work: int  # index into the works list
    start: int
    end: int
    heading: str
    score: float = 0.0

    @property
    def length(self) -> int:
        return self.end - self.start


def uncovered_spans(length: int, close_spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The parts of a text of ``length`` not in ``close_spans``."""
    spans: list[tuple[int, int]] = []
    cursor = 0
    for start, end in sorted(close_spans):
        if start > cursor:
            spans.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < length:
        spans.append((cursor, length))
    return [(s, e) for s, e in spans if e - s >= _MIN_SEGMENT_CHARS]


def segments_of(text: str, span: tuple[int, int], work: int = 0) -> list[Segment]:
    """``text[span]`` cut into sections by its numbered headings, else windows."""
    lo, hi = span
    body = text[lo:hi]
    found = find_sections(body)
    kind = next(
        (
            k
            for k in _SEGMENT_KINDS
            if len([s for s in found.get(k, []) if s.length >= _MIN_SEGMENT_CHARS]) >= 3
        ),
        None,
    )
    cuts: list[tuple[int, int]] = []
    if kind:
        sections = sorted(found[kind], key=lambda s: s.start)
        if sections[0].start >= _MIN_SEGMENT_CHARS:
            cuts.append((0, sections[0].start))
        cuts += [(s.start, s.end) for s in sections]
    else:
        cuts = [(0, len(body))]
    out: list[Segment] = []
    for start, end in cuts:
        while end - start > _MAX_SEGMENT_CHARS:
            cut = body.rfind("\n\n", start, start + _WINDOW_CHARS) if kind is None else -1
            cut = cut if cut > start + _MIN_SEGMENT_CHARS else start + _WINDOW_CHARS
            out.append(Segment(work, lo + start, lo + cut, _heading_at(body, start)))
            start = cut
        if end - start >= _MIN_SEGMENT_CHARS or not out:
            out.append(Segment(work, lo + start, lo + end, _heading_at(body, start)))
        else:
            out[-1].end = lo + end
    return out


def _heading_at(body: str, start: int) -> str:
    """The heading line at ``start`` and, when it is only a number, the title under it."""
    lines = [ln.strip() for ln in body[start : start + 400].splitlines() if ln.strip()]
    if not lines:
        return ""
    head = lines[0][:120]
    if len(lines) > 1 and re.fullmatch(r"\w+\s+(?:\d{1,4}|[IVXLC]{1,8})\.?", head):
        # The title under a bare number can run over several capitalised lines.
        title = []
        for line in lines[1:5]:
            if line.upper() != line or line.startswith("("):
                break
            title.append(line)
        if title:
            head = f"{head}: {' '.join(title)[:200]}"
    return head


def segment_title(heading: str) -> str | None:
    """A segment heading as a title: "QUESTION 75: OF MAN…" → "Of Man…"."""
    title = re.sub(r"^\w+\s+(?:\d{1,4}|[IVXLC]{1,8})\.?:?\s*", "", heading).strip()
    # A long title is cut at its first clause: "Of man who is composed of a
    # spiritual and a corporeal substance: and in the first place…".
    title = re.split(r"[:;]|,\s(?:and|in|concerning)\b", title)[0].strip(" ,.")
    words = title.split()
    if not words or len(words) > _TITLE_WORDS:
        return None
    return section_heading(" ".join(words), max_chars=100, max_words=_TITLE_WORDS)


_TITLE_WORDS = 14


def choose_segments(
    segments: list[Segment],
    concept_scores: list[list[float]],
    budget_chars: int,
) -> list[Segment]:
    """Segments to hold, round-robin across concepts, within ``budget_chars``.

    ``concept_scores[i][j]`` is segment ``i``'s similarity to concept ``j``.
    Each concept in turn takes its best segment not yet taken, so the budget
    is spread across what the expert is about rather than spent on whichever
    concept the longest work happens to dwell on.
    """
    if not segments or budget_chars <= 0:
        return []
    n_concepts = len(concept_scores[0]) if concept_scores else 0
    for seg, scores in zip(segments, concept_scores, strict=True):
        seg.score = max(scores, default=0.0)

    def by_concept(j: int) -> list[int]:
        return sorted(range(len(segments)), key=lambda i: concept_scores[i][j], reverse=True)

    queues = [by_concept(j) for j in range(n_concepts)] or [
        sorted(range(len(segments)), key=lambda i: segments[i].score, reverse=True)
    ]
    taken: set[int] = set()
    chosen: list[Segment] = []
    spent = 0
    exhausted = [False] * len(queues)
    while not all(exhausted):
        for q, queue in enumerate(queues):
            if exhausted[q]:
                continue
            while queue and (queue[0] in taken or segments[queue[0]].length > budget_chars - spent):
                queue.pop(0)
            if not queue:
                exhausted[q] = True
                continue
            i = queue.pop(0)
            taken.add(i)
            chosen.append(segments[i])
            spent += segments[i].length
    return chosen


# ── Ingestion ────────────────────────────────────────────────────────────────


@dataclass
class TailWork:
    """A long work whose close-read part is already ingested."""

    source_id: int
    title: str
    full_text: str
    close_spans: list[tuple[int, int]]
    #: First free ``sequence_n`` after the close-read chunks.
    next_seq: int


@dataclass
class StructuralReport:
    works: int = 0
    segments: int = 0
    chars: int = 0
    chunks: int = 0
    dropped: Counter = field(default_factory=Counter)
    chunk_ids: list[int] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "works": self.works,
            "segments": self.segments,
            "chars": self.chars,
            "chunks": self.chunks,
            "dropped": dict(self.dropped),
        }


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def ingest_tails(
    pool: asyncpg.Pool,
    expert_id: int,
    works: list[TailWork],
    concepts: list[str],
    budget_chars: int,
) -> StructuralReport:
    """Hold the best of every work's un-ingested text, embed-only, within budget."""
    report = StructuralReport()
    segments = [
        seg
        for w, work in enumerate(works)
        for span in uncovered_spans(len(work.full_text), work.close_spans)
        for seg in segments_of(work.full_text, span, w)
        # A segment that is not prose in the corpus language — the Old English
        # half of a facing-page edition — would spend budget only to be dropped
        # chunk by chunk by the prose gate.
        if is_prose(work.full_text[seg.start : seg.start + _LANGUAGE_PROBE_CHARS])
    ]
    if not segments or budget_chars <= 0:
        return report

    probes = [
        f"{citation_title(works[s.work].title)}. {s.heading}\n"
        f"{works[s.work].full_text[s.start : s.start + _SCORE_CHARS]}"
        for s in segments
    ]
    targets = [c for c in concepts if c.strip()]
    vectors = await embed_in_batches(targets + probes)
    concept_vecs, segment_vecs = vectors[: len(targets)], vectors[len(targets) :]
    scores = [[_cosine(sv, cv) for cv in concept_vecs] for sv in segment_vecs]
    chosen = choose_segments(segments, scores, budget_chars)
    report.segments = len(chosen)
    report.chars = sum(s.length for s in chosen)

    for w, work in enumerate(works):
        mine = sorted((s for s in chosen if s.work == w), key=lambda s: s.start)
        if not mine:
            continue
        report.works += 1
        chunks: list[TextChunk] = []
        seq = work.next_seq
        previous_end = max((e for _, e in work.close_spans), default=0)
        for seg in mine:
            if seg.start != previous_end:
                seq += 1  # a gap in the text is a gap in the sequence
            title = segment_title(seg.heading)
            for c in chunk_text(work.full_text[seg.start : seg.end], work.title):
                c.sequence_n = seq
                if title:
                    c.chunk_meta["heading"] = title
                seq += 1
                chunks.append(c)
            previous_end = seg.end
        annotate_loci(chunks)
        kept: list[TextChunk] = []
        for c in chunks:
            reason = chunk_rejection(c.text)
            if reason:
                report.dropped[reason] += 1
            else:
                kept.append(c)
        if not kept:
            continue
        notes = [structural_note(work.title, c.chunk_meta) for c in kept]
        for c, note in zip(kept, notes, strict=True):
            c.chunk_meta["ingest"] = INGEST_STRUCTURAL
            c.chunk_meta["context"] = note
        embeddings = await embed_in_batches(
            [f"{note}\n\n{c.text}"[:30_000] for c, note in zip(kept, notes, strict=True)]
        )
        ids = await _insert(pool, expert_id, work.source_id, kept, notes, embeddings)
        report.chunk_ids += ids
        report.chunks += len(ids)
        logger.info(
            "Held %d structural chunk(s) of %r (%d segment(s), embed-only)",
            len(ids),
            work.title,
            len(mine),
        )
    return report


async def _insert(
    pool: asyncpg.Pool,
    expert_id: int,
    source_id: int,
    chunks: list[TextChunk],
    notes: list[str],
    embeddings: list[list[float]],
) -> list[int]:
    from pgvector.asyncpg import register_vector  # type: ignore

    rows = [
        (expert_id, source_id, c.sequence_n, c.text, note, emb, json.dumps(c.chunk_meta))
        for c, note, emb in zip(chunks, notes, embeddings, strict=True)
    ]
    async with pool.acquire() as conn:
        await register_vector(conn)
        ids: list[int] = []
        async with conn.transaction():
            for row in rows:
                ids.append(
                    await conn.fetchval(
                        """
                        INSERT INTO source_chunks
                            (expert_id, source_id, sequence_n, text, context_text,
                             embedding, chunk_meta)
                        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                        RETURNING id
                        """,
                        *row,
                    )
                )
    return ids
