"""Neighbour expansion — a retrieved passage arrives with the text either side of it.

A chunk is about a thousand characters and an argument is not. Aquinas's article
on whether God exists runs to seven chunks; asked for the most tangible proof of
God, retrieval found the chunk where the article *begins* — the second objection
and the first sentences of the First Way — and the answering model was handed
that fragment with the argument itself one row further down the table. An expert
that may only assert what its passages say cannot walk through a proof it was
shown the first paragraph of, so the answers came back short and general, and
said so.

So the best few retrieved passages each bring their neighbours: the chunk before
and the two after, from the same source. More after than before because prose
states its point and then develops it — the text following a hit is what the hit
was leading to, and the text before it is usually the end of something else.

Neighbours are passages in their own right, each numbered and each citable, and
not text folded into the passage they came with. Everything downstream of an
answer — the citation panel, the passage reader, the audit trail — resolves
``[n]`` to one chunk, and a citation is a promise that *that* chunk says the
thing. A widened passage would let the model cite a claim from the neighbour and
show the reader the anchor.

Pure functions; the fetch is ``SearchService.fetch_by_position``.
"""

from peritus.graph.retriever import EnrichedResult

#: Where a chunk sits: ``(source_id, sequence_n)``.
Position = tuple[int, int]


def position(e: EnrichedResult) -> Position:
    return (e.result.source_id, e.result.sequence_n)


def wanted_positions(
    anchors: list[EnrichedResult],
    held: set[Position],
    before: int,
    after: int,
) -> list[Position]:
    """The positions to fetch around ``anchors``, skipping whatever is ``held``.

    Best anchor first and, around each, nearest first with the text that follows
    ahead of the text that precedes — the order that matters if a caller ever
    truncates the list. Two anchors a chunk apart want the same neighbour; it is
    asked for once.
    """
    wanted: list[Position] = []
    seen = set(held)
    for anchor in anchors:
        source_id, seq = position(anchor)
        for distance in range(1, max(before, after) + 1):
            offsets = ([distance] if distance <= after else []) + (
                [-distance] if distance <= before else []
            )
            for offset in offsets:
                pos = (source_id, seq + offset)
                if pos[1] >= 0 and pos not in seen:
                    seen.add(pos)
                    wanted.append(pos)
    return wanted


def reading_order(
    retrieved: list[EnrichedResult],
    neighbours: list[EnrichedResult],
) -> list[EnrichedResult]:
    """``retrieved`` and ``neighbours`` as runs of consecutive text.

    A run is every held chunk that is contiguous in its source. Runs are ordered
    by the best retrieved passage in them and read in source order within, so the
    model meets an argument in the order it was written rather than in the order
    a reranker scored its paragraphs. Two retrieved passages that a neighbour
    joins become one run, placed where the better of them ranked.

    A neighbour that ends up touching nothing — its anchor's adjacent chunk was
    missing — is dropped: a paragraph from two rows away, with the row between
    them absent, is not context for anything.
    """
    by_position: dict[Position, EnrichedResult] = {}
    for e in [*retrieved, *neighbours]:
        by_position.setdefault(position(e), e)

    ordered: list[EnrichedResult] = []
    placed: set[int] = set()
    for e in retrieved:
        if e.result.chunk_id in placed:
            continue
        source_id, seq = position(e)
        if by_position[(source_id, seq)] is not e:
            # Two chunks claiming one position: a corpus from before chunks were
            # sequenced. There is no order to read them in, so it stands alone.
            placed.add(e.result.chunk_id)
            ordered.append(e)
            continue
        start = seq
        while (source_id, start - 1) in by_position:
            start -= 1
        run = []
        at = start
        while (member := by_position.get((source_id, at))) is not None:
            run.append(member)
            at += 1
        for member in run:
            if member.result.chunk_id not in placed:
                placed.add(member.result.chunk_id)
                ordered.append(member)
    return ordered


def continues_previous(previous: EnrichedResult | None, current: EnrichedResult) -> bool:
    """Whether ``current`` is the very next chunk of the source ``previous`` is from."""
    if previous is None:
        return False
    source_id, seq = position(previous)
    return position(current) == (source_id, seq + 1)
