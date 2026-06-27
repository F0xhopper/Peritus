"""Golden-set evaluation runner.

Runs a JSON golden set of questions against a *live* expert and reports retrieval
recall@k, citation validity, citation→source recall, faithfulness, and refusal
correctness. Requires a database, API keys, and an already-built expert.

Usage:
    python -m peritus.eval.runner "stoic philosophy" path/to/golden.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from peritus.chat.agent import ChatAgent
from peritus.chat.faithfulness import assess_faithfulness
from peritus.chat.grounding import build_grounded_context
from peritus.core.exceptions import NotFoundError
from peritus.eval import metrics
from peritus.experts.service import ExpertService
from peritus.infrastructure.database import get_pool, init_pool


@dataclass
class GoldQuestion:
    question: str
    supporting_chunk_ids: list[int] = field(default_factory=list)
    supporting_source_ids: list[int] = field(default_factory=list)
    must_refuse: bool = False


@dataclass
class QuestionScore:
    question: str
    recall_at_k: float
    citation_validity: float
    citation_source_recall: float
    groundedness: float | None
    refusal_correct: bool | None


@dataclass
class EvalReport:
    expert: str
    n: int
    mean_recall_at_k: float
    mean_citation_validity: float
    mean_citation_source_recall: float
    mean_groundedness: float
    refusal_accuracy: float | None
    per_question: list[QuestionScore]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


async def evaluate(expert_name: str, gold: list[GoldQuestion], top_k: int = 10) -> EvalReport:
    await init_pool()
    pool = get_pool()
    svc = ExpertService(pool)
    expert = await svc.get(expert_name)  # raises NotFoundError if missing

    agent = ChatAgent(pool)
    cfg = expert.config
    scores: list[QuestionScore] = []

    for gq in gold:
        # Retrieval: mirror the agent's first hop to measure recall directly.
        subqueries = await agent._plan(gq.question, expert.topic, cfg.max_subqueries)
        search_resp = await agent._search.batch_search(
            expert_id=expert.id,
            question=gq.question,
            queries=subqueries,
            top_k=cfg.retrieval_top_k,
        )
        retrieved_ids = [r.chunk_id for r in search_resp.results]
        recall = metrics.recall_at_k(retrieved_ids, gq.supporting_chunk_ids, top_k)

        # Full grounded answer.
        answer = await agent.respond(expert, gq.question, history=[])
        enriched = await agent._graph.expand(search_resp.results, expert.id, hops=cfg.graph_hops)
        _, passages = build_grounded_context(enriched, cfg.max_context_passages)
        num_passages = len(passages)
        passage_source_ids = {p.index: p.source_id for p in passages}

        cit_validity = metrics.citation_validity(answer.text, num_passages)
        cit_source_recall = metrics.cited_supporting_sources(
            answer.text,
            passage_source_ids,
            gq.supporting_source_ids,
        )

        # Faithfulness is an offline eval metric only — it is no longer attached to
        # live answers, so the harness computes it directly here.
        faith = await assess_faithfulness(gq.question, answer.text, passages)
        groundedness = faith["groundedness"] if faith else None

        refusal_correct: bool | None = None
        if gq.must_refuse:
            refusal_correct = metrics.looks_like_refusal(answer.text)

        scores.append(QuestionScore(
            question=gq.question,
            recall_at_k=round(recall, 4),
            citation_validity=round(cit_validity, 4),
            citation_source_recall=round(cit_source_recall, 4),
            groundedness=groundedness,
            refusal_correct=refusal_correct,
        ))

    grounded = [s.groundedness for s in scores if s.groundedness is not None]
    refusals = [s.refusal_correct for s in scores if s.refusal_correct is not None]
    return EvalReport(
        expert=expert_name,
        n=len(scores),
        mean_recall_at_k=metrics.aggregate([s.recall_at_k for s in scores]),
        mean_citation_validity=metrics.aggregate([s.citation_validity for s in scores]),
        mean_citation_source_recall=metrics.aggregate([s.citation_source_recall for s in scores]),
        mean_groundedness=metrics.aggregate(grounded),
        refusal_accuracy=(
            metrics.aggregate([1.0 if r else 0.0 for r in refusals]) if refusals else None
        ),
        per_question=scores,
    )


def _load_gold(path: str) -> list[GoldQuestion]:
    data = json.loads(Path(path).read_text())
    return [GoldQuestion(**q) for q in data["questions"]]


async def _main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: python -m peritus.eval.runner <expert> <golden.json>")
    expert_name, gold_path = sys.argv[1], sys.argv[2]
    try:
        report = await evaluate(expert_name, _load_gold(gold_path))
    except NotFoundError:
        raise SystemExit(f"No expert found matching {expert_name!r} — build it first.") from None
    print(report.to_json())


if __name__ == "__main__":
    asyncio.run(_main())
