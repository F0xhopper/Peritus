"""Is an expert's answer better than the same model's with no corpus?

    python -m peritus.eval.headtohead run [--set PATH] [--expert ID] [--out PATH]
    python -m peritus.eval.headtohead compare BASELINE.json RUN.json

The only harness that asks the question users ask. ``eval/retrieval.py``
measures recall on questions generated *from* chunk text, so it cannot see a
corpus that is missing the text; ``eval/helpfulness.py`` scores an answer on its
own. This one puts two answers side by side:

- **Peritus**: the production path — ``ChatAgent.gather_context`` and the same
  compose call ``stream_expert_answer`` makes. Read-only: no conversation and no
  audit row is written.
- **Closed-book**: the same model, effort and token limit, a one-line system
  prompt, no corpus.

``[n]`` markers are stripped from the Peritus answer so the arms cannot be told
apart, and a stronger model judges them **in both orders**. A verdict counts
only when the two orders agree; otherwise the question is a split. Each
question carries a class (``held``, ``edge``, ``broad``, ``multi_part``,
``how_to`` …) and its retrieval diagnostics sit beside its verdict, because a
loss is only diagnosable joined to what reached the prompt.

Cost: about $0.25 and 90 seconds a question. Retrieval runs one question at a
time, paced for a Cohere trial key (10 reranks a minute); composition and
judging overlap it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam

from peritus.chat.agent import (
    ChatAgent,
    build_cached_system,
    build_composition_messages,
    composition_params,
)
from peritus.chat.grounding import parse_cited_indices
from peritus.core.config import settings
from peritus.eval.metrics import answer_form
from peritus.experts.service import ExpertService
from peritus.infrastructure.anthropic_client import get_anthropic_client, tool_input
from peritus.infrastructure.database import get_pool, init_pool

DEFAULT_SET = Path(__file__).parent / "golden" / "headtohead" / "set-2026-09.json"
JUDGE_MODEL = "claude-opus-5"
AXES = ("directness", "completeness", "depth_specificity", "accuracy", "usefulness")

_CITE = re.compile(r"\s?\[\d{1,3}\]")

JUDGE_TOOL: ToolParam = {
    "name": "judge",
    "description": "Score two answers to the same question.",
    "input_schema": {
        "type": "object",
        "properties": {
            **{
                f"{arm}_{axis}": {"type": "integer", "minimum": 1, "maximum": 5}
                for arm in ("a", "b")
                for axis in AXES
            },
            "a_has_that_b_lacks": {"type": "array", "items": {"type": "string"}},
            "b_has_that_a_lacks": {"type": "array", "items": {"type": "string"}},
            "a_errors_or_padding": {"type": "array", "items": {"type": "string"}},
            "b_errors_or_padding": {"type": "array", "items": {"type": "string"}},
            "preferred": {"type": "string", "enum": ["a", "b", "tie"]},
            "reason": {"type": "string"},
        },
        "required": [
            *(f"{arm}_{axis}" for arm in ("a", "b") for axis in AXES),
            "a_has_that_b_lacks",
            "b_has_that_a_lacks",
            "a_errors_or_padding",
            "b_errors_or_padding",
            "preferred",
            "reason",
        ],
    },
}


async def closed_book(topic: str, question: str, max_tokens: int, qtype: str | None) -> str:
    client = get_anthropic_client()
    resp = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        system=(
            f"You are a knowledgeable expert in {topic}. Answer the question clearly, in Markdown."
        ),
        messages=[MessageParam(role="user", content=question)],
        **composition_params(settings.CLAUDE_MODEL, max_tokens, qtype),
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
        tool_choice=ToolChoiceToolParam(type="tool", name="judge"),
        messages=[
            MessageParam(
                role="user",
                content=f"Question: {question}\n\n=== ANSWER A ===\n{a}\n\n=== ANSWER B ===\n{b}",
            )
        ],
    )
    return dict(tool_input(resp) or {})


def verdict_of(verdicts: list[dict]) -> str:
    """ "peritus", "closed_book" or "split": both orders must agree."""
    picks = []
    for v in verdicts:
        pref = v.get("preferred")
        if pref == "tie" or pref not in ("a", "b"):
            picks.append("tie")
        else:
            picks.append("peritus" if pref == v["peritus_is"] else "closed_book")
    return picks[0] if len(set(picks)) == 1 and picks[0] != "tie" else "split"


def axis_scores(verdicts: list[dict]) -> dict[str, dict[str, float]]:
    """Per-arm mean of each axis over the verdicts."""
    out: dict[str, dict[str, float]] = {"peritus": {}, "closed_book": {}}
    for axis in AXES:
        p, c = [], []
        for v in verdicts:
            mine, theirs = ("a", "b") if v.get("peritus_is") == "a" else ("b", "a")
            if f"{mine}_{axis}" in v:
                p.append(v[f"{mine}_{axis}"])
                c.append(v[f"{theirs}_{axis}"])
        if p:
            out["peritus"][axis] = sum(p) / len(p)
            out["closed_book"][axis] = sum(c) / len(c)
    return out


async def run(
    items: list[dict], out: Path, pace: float = 7.0, seed: int = 7
) -> list[dict[str, Any]]:
    await init_pool()
    pool = get_pool()
    agent = ChatAgent(pool)
    experts = ExpertService(pool)
    client = get_anthropic_client()
    rng = random.Random(seed)
    results: list[dict[str, Any]] = [{} for _ in items]
    lock = asyncio.Lock()

    async def finish(i: int, item: dict, expert: Any, ctx: Any, seconds: float) -> None:
        question = item["question"]
        qtype = ctx.plan.question_type if ctx.plan else None
        resp = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            system=build_cached_system(expert.persona_style, expert.topic),
            messages=build_composition_messages(
                [],
                question,
                ctx.context_block,
                ctx.plan,
                ctx.has_contradiction,
                ctx.contradiction_points,
                ctx.evidence,
            ),
            **composition_params(settings.CLAUDE_MODEL, expert.config.max_response_tokens, qtype),
        )
        peritus = "".join(b.text for b in resp.content if hasattr(b, "text"))
        baseline = await closed_book(
            expert.topic, question, expert.config.max_response_tokens, qtype
        )
        blind = _CITE.sub("", peritus)
        orders = rng.sample([True, False], 2)
        verdicts = []
        for peritus_is_a in orders:
            a, b = (blind, baseline) if peritus_is_a else (baseline, blind)
            v = await judge(expert.topic, question, a, b)
            v["peritus_is"] = "a" if peritus_is_a else "b"
            verdicts.append(v)

        trail = ctx.trail
        steps = trail.steps if trail else []
        in_ctx = {p.chunk_id for p in ctx.passages}
        cited = parse_cited_indices(peritus, len(ctx.passages))
        results[i] = {
            **item,
            "topic": expert.topic,
            "plan": {
                "subqueries": ctx.plan.subqueries if ctx.plan else [],
                "fallback_queries": ctx.plan.fallback_queries if ctx.plan else [],
                "question_type": qtype,
                "asker_level": ctx.plan.asker_level if ctx.plan else None,
            },
            "retrieval": {
                "coverage_satisfied": trail.coverage_satisfied if trail else None,
                "second_pass": trail.second_pass if trail else None,
                "reranker": trail.reranker if trail else None,
                "evidence": ctx.evidence,
                "scores": [
                    round(s.score, 3) for s in steps if s.via in ("primary", "coverage_followup")
                ],
                "context_passages": len(ctx.passages),
                "context_sources": len({p.source_id for p in ctx.passages}),
                "cited_sources": len({p.source_id for p in ctx.passages if p.index in cited}),
                "seats": sum(1 for s in steps if s.via == "subquery_seat" and s.chunk_id in in_ctx),
                "neighbours": sum(
                    1 for s in steps if s.via == "neighbour" and s.chunk_id in in_ctx
                ),
                "labels": sorted({p.citation for p in ctx.passages})[:30],
                "seconds": round(seconds, 1),
            },
            "form": answer_form(peritus, expert.persona_style),
            "peritus_answer": peritus,
            "peritus_context": ctx.context_block,
            "baseline_answer": baseline,
            "verdicts": verdicts,
            "verdict": verdict_of(verdicts),
        }
        async with lock:
            await asyncio.to_thread(out.write_text, json.dumps([r for r in results if r], indent=2))
        print(
            f"[{item['expert_id']}] {item['class']:<10} {results[i]['verdict']:<11} "
            f"{question[:60]}",
            flush=True,
        )

    tasks = []
    for i, item in enumerate(items):
        started = time.monotonic()
        expert = await experts.get(item["expert_id"])
        ctx = await agent.gather_context(expert, item["question"], [])
        tasks.append(asyncio.create_task(finish(i, item, expert, ctx, time.monotonic() - started)))
        if i < len(items) - 1:
            await asyncio.sleep(pace)
    done = await asyncio.gather(*tasks, return_exceptions=True)
    for item, d in zip(items, done, strict=True):
        if isinstance(d, BaseException):
            print(f"FAILED: {item['question'][:60]}: {d!r}", file=sys.stderr)
    final = [r for r in results if r]
    await asyncio.to_thread(out.write_text, json.dumps(final, indent=2))
    return final


def summarise(results: list[dict]) -> str:
    lines: list[str] = []
    by_class: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        by_class[r.get("class", "?")][r.get("verdict") or verdict_of(r["verdicts"])] += 1
    total: Counter = Counter()
    lines.append("| Class | Peritus | Closed-book | Split |")
    lines.append("|---|---|---|---|")
    for cls, c in sorted(by_class.items()):
        total.update(c)
        lines.append(f"| {cls} | {c['peritus']} | {c['closed_book']} | {c['split']} |")
    lines.append(
        f"| **all** | **{total['peritus']}** | **{total['closed_book']}** | {total['split']} |"
    )
    lines.append("")
    axes = axis_scores([v for r in results for v in r["verdicts"]])
    lines.append("| Axis | Peritus | Closed-book |")
    lines.append("|---|---|---|")
    for axis in AXES:
        pv, cv = axes["peritus"].get(axis), axes["closed_book"].get(axis)
        if pv is not None and cv is not None:
            lines.append(f"| {axis} | {pv:.2f} | {cv:.2f} |")
    forms = [r["form"] for r in results if "form" in r]
    if forms:
        lines.append("")
        lines.append(
            f"Form over {len(forms)} answers: heading first line "
            f"{sum(f['first_line_heading'] for f in forms)}, persona overlap ≥5 words "
            f"{sum(f['persona_overlap'] >= 5 for f in forms)}, summary section "
            f"{sum(f['summary_section'] for f in forms)}, 'my sources' asides "
            f"{sum(f['my_sources_asides'] > 0 for f in forms)}, with a quotation "
            f"{sum(f['quotations'] > 0 for f in forms)}, naming a locus "
            f"{sum(f['loci'] > 0 for f in forms)}; mean length "
            f"{sum(f['chars'] for f in forms) // len(forms)} chars."
        )
    return "\n".join(lines)


def compare(baseline: list[dict], run_: list[dict]) -> str:
    before = {r["question"]: r for r in baseline}
    lines = [
        "| Q | Class | Before | After | Evidence | Passages / sources |",
        "|---|---|---|---|---|---|",
    ]
    for r in run_:
        b = before.get(r["question"])
        was = (b.get("verdict") or verdict_of(b["verdicts"])) if b else "—"
        ret = r.get("retrieval", {})
        lines.append(
            f"| {r['question'][:55]} | {r.get('class')} | {was} | {r['verdict']} | "
            f"{ret.get('evidence')} | {ret.get('context_passages')} / "
            f"{ret.get('context_sources')} |"
        )
    return "\n".join(lines)


def load_set(path: Path, expert: int | None = None) -> list[dict]:
    items = json.loads(path.read_text())["items"]
    return [i for i in items if expert is None or i["expert_id"] == expert]


async def _main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m peritus.eval.headtohead")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--set", type=Path, default=DEFAULT_SET)
    r.add_argument("--expert", type=int)
    r.add_argument("--class", dest="cls", action="append")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--pace", type=float, default=7.0)
    c = sub.add_parser("compare")
    c.add_argument("baseline", type=Path)
    c.add_argument("run", type=Path)
    s = sub.add_parser("summary")
    s.add_argument("run", type=Path)
    args = parser.parse_args(argv)

    if args.cmd == "run":
        items = load_set(args.set, args.expert)
        if args.cls:
            items = [i for i in items if i["class"] in args.cls]
        results = await run(items, args.out, pace=args.pace)
        print(summarise(results))
    elif args.cmd == "summary":
        print(summarise(json.loads(args.run.read_text())))
    else:
        base = json.loads(args.baseline.read_text())
        new = json.loads(args.run.read_text())
        print(compare(base, new))
        print()
        print(summarise(new))


if __name__ == "__main__":
    asyncio.run(_main())
