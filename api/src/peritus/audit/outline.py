"""The expert's outline: what it holds, work by work and part by part.

The Map, the Flow and the Graph draw the expert's *ideas* — a syllabus, and the
concepts a model extracted from a capped share of each source. None of them can
say the plainest thing about a corpus: which works are in it, how far into each
one the expert reads, and which parts it read closely as against merely holds.
That was invisible when it mattered most — every long work cut at 200,000
characters, the Prima Pars ending at question 10 of 119, and no page of the
product that could have shown it (docs/plans/beating-closed-book.md §3.1).

The outline is the corpus in the shape its authors gave it:

- a **work** is a kept source;
- a **part** is a run of its passages under one heading — or, where the text
  carries no usable heading, under one locus ("I, q. 36") — all read the same
  way: **closely** (contextualised, sent to graph extraction) or **held**
  (``ingestion/structural.py``: embedded and findable, never read by a model);
- a **section** is a row of ``corpus_sections`` inside a part, with the ~120
  words on what it establishes that broad questions are routed by
  (``ingestion/summaries.py``). Experts built before that table have parts and
  no sections.

Each part says which key concepts its passages serve, counted off the concept
nodes anchored in it. A single node's key concept is an assignment that is right
about four times in five; a part's is a tally over all of them, which is why it
is only reported past a share of the part's evidence. Held parts have no nodes,
so they carry none — that is what "held" means.

Pure functions over rows the repository has already read. The outline itself
carries no summary text — a few hundred paragraphs is most of a megabyte on a
large expert — only how many sections each part has; a work's summaries are read
when that work is opened (:func:`build_outline_work`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from peritus.experts.domain import Expert
from peritus.ingestion.structural import INGEST_STRUCTURAL
from peritus.search.labels import citation_title, section_heading

#: A part with fewer passages than this joins its neighbour — the same rule, and
#: the same number, the section summariser uses (``summaries.MIN_RUN``). A stray
#: heading ("Truth", a printer's name, a line of a table of contents) is one or
#: two passages long, and sixty of them is not an outline.
MIN_PART = 3
#: The most key concepts a part reports.
MAX_PART_CONCEPTS = 2
#: A key concept is reported for a part when it has at least this many anchored
#: concept nodes there, and at least this share of the part's.
MIN_CONCEPT_HITS = 2
MIN_CONCEPT_SHARE = 0.25


@dataclass
class _Part:
    label: str | None
    held: bool
    seq_start: int
    seq_end: int
    passage_id: int
    passages: int = 0
    chars: int = 0
    locus_first: str | None = None
    locus_last: str | None = None
    group: str | None = None
    hits: dict[int, int] = field(default_factory=dict)
    sections: list[dict[str, Any]] = field(default_factory=list)


def _meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


# A full stop with more text after it: "A.D. 1115. This year was the King…",
# "CII. That God's happiness is perfect", "C. A. Mirick, Printer". A heading names
# a place in a work; these are a sentence, a contents line and a colophon.
_SENTENCE = re.compile(r"\.\s+\S")
_ABBREVIATION = re.compile(r"\b(?:St|Dr|Mr|Mrs|vs|cf)\.", re.IGNORECASE)


def _heading(meta: dict[str, Any], work: str) -> str | None:
    """The heading a passage sits under, fit to title a part.

    The citation label's rule (``search/labels.py``), and one more: a label
    beside a single passage may be a sentence, but a row of an outline may not.
    """
    heading = section_heading(meta.get("section"), work) or section_heading(
        meta.get("heading"), work, max_chars=100, max_words=14
    )
    if heading and _SENTENCE.search(_ABBREVIATION.sub("", heading)):
        return None
    return heading


def _locus(meta: dict[str, Any]) -> str | None:
    return " ".join(str(meta.get("locus") or "").split()) or None


def summary_text(raw: str | None) -> str:
    """A section summary as a paragraph of prose.

    Seven in ten stored summaries open with a title line the summariser was told
    not to write — "# Index Entry: Summa Theologica, Part I, Question 2", or the
    same in bold — and the part and its locus already say that beside it.
    """
    lines = [line.strip() for line in (raw or "").splitlines()]
    while lines and (
        not lines[0] or lines[0].startswith("#") or re.fullmatch(r"\*\*.+\*\*:?", lines[0])
    ):
        lines.pop(0)
    # Emphasis markers too (`*a priori*`): the view shows prose, not Markdown.
    text = re.sub(r"\*{1,2}([^*\n]+)\*{1,2}", r"\1", " ".join(lines))
    return " ".join(text.split())


def locus_group(locus: str | None) -> str | None:
    """What a locus belongs to: "I, q. 2, a. 3" → "I, q. 2".

    Only a locus with more than one component has a group. "A.D. 878" or
    "Question 2" on its own is a place, not a place *within* something, and
    splitting on it would make a part of every annal.
    """
    if not locus or "," not in locus:
        return None
    return locus.rsplit(",", 1)[0].strip() or None


def _breaks(part: _Part, held: bool, heading: str | None, group: str | None) -> bool:
    """Whether a passage begins a new part rather than continuing ``part``.

    A jump in the sequence is deliberately not a reason. The prose gate leaves
    holes — an edition of Bede that interleaves Old English lost two passages in
    three — and a part per island was 106 rows all reading "Book I". Where text
    is genuinely skipped, the heading or the locus changes across it.
    """
    if part.held != held:
        return True
    if heading is not None:
        return heading != part.label
    return group is not None and part.group is not None and group != part.group


def _parts(chunks: list[dict[str, Any]], work: str) -> list[_Part]:
    """One work's passages, in order, as parts.

    A part ends where the way of reading changes or a new heading begins. A
    passage with no usable heading — "Full Text",
    or a line of body text the chunker took for one — stays in the part it
    follows unless its locus says it has moved on to something else.
    """
    parts: list[_Part] = []
    for row in chunks:
        meta = _meta(row.get("chunk_meta"))
        heading = _heading(meta, work)
        locus = _locus(meta)
        group = locus_group(locus)
        held = meta.get("ingest") == INGEST_STRUCTURAL
        seq = int(row["sequence_n"])
        current = parts[-1] if parts else None
        if current is None or _breaks(current, held, heading, group):
            current = _Part(
                label=heading,
                held=held,
                seq_start=seq,
                seq_end=seq,
                passage_id=int(row["id"]),
            )
            parts.append(current)
        current.seq_end = seq
        current.passages += 1
        current.chars += int(row.get("chars") or 0)
        if locus:
            current.locus_first = current.locus_first or locus
            current.locus_last = locus
        if group:
            current.group = group
    return _merge_short(parts)


def _merge_short(parts: list[_Part]) -> list[_Part]:
    """Fold a part under ``MIN_PART`` passages into the one before it.

    Never across the read-closely/held line. The longer of the two keeps its
    name; the passage the part opens at stays the first.
    """
    merged: list[_Part] = []
    for part in parts:
        prev = merged[-1] if merged else None
        if (
            prev is None
            or prev.held != part.held
            or (part.passages >= MIN_PART and prev.passages >= MIN_PART)
        ):
            merged.append(part)
            continue
        if part.passages > prev.passages:
            prev.label = part.label or prev.label
        prev.seq_end = part.seq_end
        prev.passages += part.passages
        prev.chars += part.chars
        prev.locus_first = prev.locus_first or part.locus_first
        prev.locus_last = part.locus_last or prev.locus_last
        prev.group = part.group or prev.group
    return merged


def _part_concepts(hits: dict[int, int], known: int) -> list[int]:
    """The key concepts a part serves, busiest first, past the evidence floor."""
    total = sum(hits.values())
    if not total:
        return []
    ranked = sorted(hits.items(), key=lambda item: (-item[1], item[0]))
    return [
        idx
        for idx, n in ranked
        if 0 <= idx < known and n >= MIN_CONCEPT_HITS and n / total >= MIN_CONCEPT_SHARE
    ][:MAX_PART_CONCEPTS]


def _work(
    source: dict[str, Any],
    chunks: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    hits: dict[int, dict[int, int]],
    key_concepts: int,
    *,
    summaries: bool,
) -> dict[str, Any] | None:
    """One kept source as a work, or None when none of its passages are held."""
    if not chunks:
        return None
    parts = _parts(chunks, citation_title(source.get("title") or ""))
    by_seq = {int(row["sequence_n"]): row for row in chunks}
    for part in parts:
        for seq in range(part.seq_start, part.seq_end + 1):
            for idx, n in hits.get(seq, {}).items():
                part.hits[idx] = part.hits.get(idx, 0) + n

    for row in sorted(sections, key=lambda r: int(r["seq_start"])):
        start, end = int(row["seq_start"]), int(row["seq_end"])
        home = next((p for p in parts if p.seq_start <= start <= p.seq_end), None)
        if home is None:
            continue
        # A summary's run can outlast its part by a merged stray heading; what
        # is shown for it is the stretch that lies inside the part.
        end = min(end, home.seq_end)
        rows = [by_seq[seq] for seq in range(start, end + 1) if seq in by_seq]
        if not rows:
            continue
        loci = [locus for r in rows if (locus := _locus(_meta(r.get("chunk_meta"))))]
        home.sections.append(
            {
                "seq_start": start,
                "seq_end": end,
                "passages": len(rows),
                "passage_id": int(rows[0]["id"]),
                "locus_first": loci[0] if loci else None,
                "locus_last": loci[-1] if loci else None,
                "summary": summary_text(row.get("summary")),
            }
        )

    close = sum(p.passages for p in parts if not p.held)
    held = sum(p.passages for p in parts if p.held)
    return {
        "source_id": int(source["id"]),
        "title": source.get("title") or "",
        "author": source.get("author"),
        "kind": source["source_type"],
        "tier": source.get("source_tier"),
        "passages": close + held,
        "close": close,
        "held": held,
        "locus_first": next((p.locus_first for p in parts if p.locus_first), None),
        "locus_last": next((p.locus_last for p in reversed(parts) if p.locus_last), None),
        "parts": [
            {
                "label": p.label,
                "held": p.held,
                "seq_start": p.seq_start,
                "seq_end": p.seq_end,
                "passages": p.passages,
                "passage_id": p.passage_id,
                "locus_first": p.locus_first,
                "locus_last": p.locus_last,
                "key_concepts": _part_concepts(p.hits, key_concepts),
                "section_count": len(p.sections),
                # Null means "not sent": the outline counts a part's sections,
                # and one work's payload carries them.
                "sections": p.sections if summaries else None,
            }
            for p in parts
        ],
    }


def _by_source(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["source_id"]), []).append(row)
    return grouped


def _hits_by_source(rows: list[dict[str, Any]]) -> dict[int, dict[int, dict[int, int]]]:
    grouped: dict[int, dict[int, dict[int, int]]] = {}
    for row in rows:
        per_seq = grouped.setdefault(int(row["source_id"]), {})
        per_seq.setdefault(int(row["sequence_n"]), {})[int(row["idx"])] = int(row["n"])
    return grouped


def build_outline(
    expert: Expert,
    sources: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    concept_hits: list[dict[str, Any]],
) -> dict[str, Any]:
    """Every work and its parts, with a count of each part's sections.

    ``sources`` are the kept sources; ``chunks`` every passage of theirs as
    ``(id, source_id, sequence_n, chunk_meta, chars)`` ordered by source and
    sequence; ``sections`` the ``corpus_sections`` rows (their summaries are not
    needed here); ``concept_hits`` how many concept nodes placed in key concept
    ``idx`` are anchored in the passage at ``(source_id, sequence_n)``.

    ``computed`` is false while there are no passages at all — sources found but
    not yet read — so the view can say "not yet" rather than "nothing".
    """
    key_concepts = len(expert.key_concepts or [])
    chunks_of, sections_of, hits_of = (
        _by_source(chunks),
        _by_source(sections),
        _hits_by_source(concept_hits),
    )
    works = [
        work
        for source in sources
        if (
            work := _work(
                source,
                chunks_of.get(int(source["id"]), []),
                sections_of.get(int(source["id"]), []),
                hits_of.get(int(source["id"]), {}),
                key_concepts,
                summaries=False,
            )
        )
    ]
    # The works an expert leans on most come first; a tie keeps the source order.
    works.sort(key=lambda w: -w["passages"])
    return {
        "expert": {"slug": expert.name, "topic": expert.topic},
        "computed": bool(works),
        "key_concepts": list(expert.key_concepts or []),
        "totals": {
            "works": len(works),
            "passages": sum(w["passages"] for w in works),
            "close": sum(w["close"] for w in works),
            "held": sum(w["held"] for w in works),
            "parts": sum(len(w["parts"]) for w in works),
            "sections": sum(p["section_count"] for w in works for p in w["parts"]),
        },
        "works": works,
    }


def build_outline_work(
    expert: Expert,
    source: dict[str, Any],
    chunks: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    concept_hits: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """One work with each part's sections and what they establish.

    The same parts, in the same order, as the work has in :func:`build_outline`
    — the view matches them by ``seq_start`` — so both are cut by one function.
    """
    return _work(
        source,
        chunks,
        sections,
        _hits_by_source(concept_hits).get(int(source["id"]), {}),
        len(expert.key_concepts or []),
        summaries=True,
    )
