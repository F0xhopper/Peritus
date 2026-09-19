"""Peritus vs the same model closed-book, judged blind in both orders.

Read-only against the DB: uses ChatAgent.gather_context + a direct compose call,
so no conversation or audit rows are written.
"""

import asyncio
import json
import random
import re
import sys
import time

from peritus.chat.agent import (
    ChatAgent,
    build_cached_system,
    build_composition_messages,
    composition_params,
)
from peritus.core.config import settings
from peritus.experts.service import ExpertService
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.infrastructure.database import get_pool, init_pool

OUT = sys.argv[1]
JUDGE_MODEL = "claude-opus-5"

QUESTIONS: list[tuple[int, str]] = [
    (63, "What is the most tangible proof for God for a modern atheist?"),
    (63, "What will happen at the moment of death?"),
    (63, "Will we have bodies in the beatific vision?"),
    (63, "What is natural law and how do we come to know it?"),
    (63, "Why does Aquinas say God is simple, and what is the strongest objection to that?"),
    (66, "Who was the most impactful king during this period and why?"),
    (66, "What does the genetic evidence say about how many Anglo-Saxons actually migrated to Britain?"),
    (66, "Was the Anglo-Saxon arrival an invasion or a gradual migration?"),
    (41, "Why do bees swarm, and how do I stop my hive from swarming?"),
    (41, "How do I get a colony through its first winter?"),
    (43, "What is a perfect syllogism and why did Aristotle care about the distinction?"),
    (43, "What is the square of opposition?"),
]

_CITE = re.compile(r"\s?\[\d{1,3}\]")

JUDGE_TOOL = {
    "name": "judge",
    "description": "Score two answers to the same question.",
    "input_schema": {
        "type": "object",
        "properties": {
            **{
                f"{arm}_{axis}": {"type": "integer", "minimum": 1, "maximum": 5}
                for arm in ("a", "b")
                for axis in ("directness", "completeness", "depth_specificity", "accuracy", "usefulness")
            },
            "a_has_that_b_lacks": {"type": "array", "items": {"type": "string"}},
            "b_has_that_a_lacks": {"type": "array", "items": {"type": "string"}},
            "a_errors_or_padding": {"type": "array", "items": {"type": "string"}},
            "b_errors_or_padding": {"type": "array", "items": {"type": "string"}},
            "preferred": {"type": "string", "enum": ["a", "b", "tie"]},
            "reason": {"type": "string"},
        },
        "required": [
            "a_directness", "a_completeness", "a_depth_specificity", "a_accuracy", "a_usefulness",
            "b_directness", "b_completeness", "b_depth_specificity", "b_accuracy", "b_usefulness",
            "a_has_that_b_lacks", "b_has_that_a_lacks", "a_errors_or_padding", "b_errors_or_padding",
            "preferred", "reason",
        ],
    },
}


async def closed_book(topic: str, question: str, max_tokens: int) -> str:
    client = get_anthropic_client()
    resp = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        system=f"You are a knowledgeable expert in {topic}. Answer the question clearly, in Markdown.",
        messages=[{"role": "user", "content": question}],
        **composition_params(settings.CLAUDE_MODEL, max_tokens),
    )
    return "".join(b.text for b in resp.content if hasattr(b, "text"))


async def judge(topic: str, question: str, a: str, b: str) -> dict:
    client = get_anthropic_client()
    resp = await client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=2000,
        system=(
            f"You are a demanding specialist in {topic} judging two answers to a question "
            "from a curious, intelligent non-specialist. Judge substance, not length or "
            "formatting. completeness = covers what a real expert would consider essential "
            "to this question. depth_specificity = gives the actual arguments, facts, names, "
            "figures, not descriptions of them. Penalise padding, repetition, narrowness, "
            "and answering a different question than the one asked. List concrete items in "
            "the has/lacks fields."
        ),
        tools=[JUDGE_TOOL],
        tool_choice={"type": "tool", "name": "judge"},
        messages=[
            {
                "role": "user",
                "content": f"Question: {question}\n\n=== ANSWER A ===\n{a}\n\n=== ANSWER B ===\n{b}",
            }
        ],
    )
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            return dict(block.input)
    return {}


async def main() -> None:
    await init_pool()
    pool = get_pool()
    agent = ChatAgent(pool)
    svc = ExpertService(pool)
    client = get_anthropic_client()
    rng = random.Random(7)
    results = []

    for expert_id, question in QUESTIONS:
        started = time.monotonic()
        expert = await svc.get(expert_id)
        ctx = await agent.gather_context(expert, question, [])
        t_retrieve = time.monotonic() - started

        resp = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            system=build_cached_system(expert.persona_style, expert.topic),
            messages=build_composition_messages(
                [], question, ctx.context_block, ctx.plan, ctx.has_contradiction, ctx.contradiction_points
            ),
            **composition_params(settings.CLAUDE_MODEL, expert.config.max_response_tokens),
        )
        peritus = "".join(b.text for b in resp.content if hasattr(b, "text"))
        baseline = await closed_book(expert.topic, question, expert.config.max_response_tokens)

        # Blind: citation markers stripped so the judge cannot tell the arms apart.
        p_blind = _CITE.sub("", peritus)
        verdicts = []
        for peritus_is_a in rng.sample([True, False], 2):
            a, b = (p_blind, baseline) if peritus_is_a else (baseline, p_blind)
            v = await judge(expert.topic, question, a, b)
            v["peritus_is"] = "a" if peritus_is_a else "b"
            verdicts.append(v)

        trail = ctx.trail
        steps = trail.steps if trail else []
        in_ctx = {p.chunk_id for p in ctx.passages}
        searched = [s for s in steps if s.via != "neighbour"]
        results.append(
            {
                "expert_id": expert_id,
                "topic": expert.topic,
                "question": question,
                "plan": {
                    "subqueries": ctx.plan.subqueries if ctx.plan else [],
                    "fallback_queries": ctx.plan.fallback_queries if ctx.plan else [],
                    "question_type": ctx.plan.question_type if ctx.plan else None,
                    "asker_level": ctx.plan.asker_level if ctx.plan else None,
                    "directive": ctx.plan.answer_directive if ctx.plan else None,
                },
                "retrieval": {
                    "coverage_satisfied": trail.coverage_satisfied if trail else None,
                    "second_pass": trail.second_pass if trail else None,
                    "retrieved": len(searched),
                    "scores": [round(s.score, 3) for s in searched],
                    "context_passages": len(ctx.passages),
                    "context_sources": len({p.source_id for p in ctx.passages}),
                    "neighbours_in_context": sum(1 for s in steps if s.via == "neighbour" and s.chunk_id in in_ctx),
                    "context_chars": len(ctx.context_block),
                    "source_titles": sorted({s.source_title for s in steps if s.chunk_id in in_ctx}),
                    "seconds": round(t_retrieve, 1),
                },
                "peritus_answer": peritus,
                "peritus_context": ctx.context_block,
                "baseline_answer": baseline,
                "verdicts": verdicts,
            }
        )
        with open(OUT, "w") as fh:
            json.dump(results, fh, indent=2)
        print(f"done: [{expert_id}] {question[:60]}  ({time.monotonic() - started:.0f}s)", flush=True)
        # Cohere trial key: 10 rerank calls a minute.
        await asyncio.sleep(7)


asyncio.run(main())
