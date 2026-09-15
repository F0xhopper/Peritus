"""Measure triage — the stage that decides what gets fetched — against human labels.

Triage used to fail open: a batch that failed or came back misaligned gave every
candidate in it 5.0, and the Thomism build (job 53) fetched an actress, a
disambiguation page and an OCR'd visual-analytics paper that way. The fix is in
(scores by id, re-ask, fail closed, a fetch floor), and whether the floor of 6.0
separates keep from drop is a guess until this harness says otherwise.

    # 1. Export one job's candidates, sampled for labelling
    python -m peritus.eval.triage export eval/golden/triage/thomism.json --expert thomism

    # 2. A person fills in "keep" and "why" for each candidate

    # 3. Re-score the candidates under the current code and report
    python -m peritus.eval.triage run eval/golden/triage/thomism.json

The report gives precision and recall of "would be fetched" against "keep",
Spearman between the triage score and the label, the same split by source type
and by discovery route, the keep rate in each score band (which is where a floor
should sit), and — from the ledger the export was taken from — the same numbers
for what the build *actually* fetched, so the old run and the new code can be
compared on one labelled set.

**What this does not do.** It does not label anything. A golden set labelled by
a model measures triage against a model. See ``eval/golden/triage/README.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from peritus.core.config import settings
from peritus.eval.metrics import screening_precision_recall, spearman
from peritus.sources.domain import SourceCandidate, SourceType
from peritus.sources.triage import rank_candidates, triage_candidates

# Candidates around the floor are where the decision is in doubt, so an export
# over-represents them.
_BAND = (3.0, 8.0)
_DEFAULT_SAMPLE = 150
_SCORE_BANDS = ((0.0, 3.0), (3.0, 5.0), (5.0, 6.0), (6.0, 7.0), (7.0, 8.0), (8.0, 10.01))


@dataclass
class LabelledCandidate:
    url: str
    title: str
    source_type: str
    snippet: str = ""
    author: str | None = None
    discovered_via: str = "plan"
    must_have: bool = False
    # From the ledger at export time: what the build that produced the
    # candidate decided about it.
    ledger_score: float | None = None
    ledger_outcome: str | None = None
    # Human. ``None`` until labelled, and unlabelled entries are skipped.
    keep: bool | None = None
    why: str = ""

    def candidate(self) -> SourceCandidate:
        return SourceCandidate(
            source_type=SourceType(self.source_type),
            url=self.url,
            title=self.title,
            author=self.author,
            snippet=self.snippet,
            metadata={"discovered_via": self.discovered_via},
        )


@dataclass
class TriageGolden:
    topic: str
    key_concepts: list[str]
    must_have_titles: list[str]
    job_id: int | None
    candidates: list[LabelledCandidate] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> TriageGolden:
        data = json.loads(path.read_text())
        return cls(
            topic=data["topic"],
            key_concepts=list(data.get("key_concepts") or []),
            must_have_titles=list(data.get("must_have_titles") or []),
            job_id=data.get("job_id"),
            candidates=[LabelledCandidate(**c) for c in data.get("candidates", [])],
        )

    def dump(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n")


@dataclass
class TriageReport:
    topic: str
    golden_file: str
    model: str
    floor: float
    labelled: int
    now: dict[str, Any]
    at_build: dict[str, Any] | None
    spearman_score_vs_keep: float
    keep_rate_by_score_band: dict[str, dict[str, Any]]
    by_source_type: dict[str, dict[str, Any]]
    by_discovered_via: dict[str, dict[str, Any]]
    labelled_drops_fetched_below_3: list[str]
    rows: list[dict[str, Any]]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def render(self) -> str:
        n = self.now
        lines = [
            f"Triage report — {self.topic}",
            f"  golden set   {self.golden_file}",
            f"  model        {self.model}   floor {self.floor:g}",
            f"  labelled     {self.labelled}",
            "",
            f"  now        precision {n['precision']:.3f}  recall {n['recall']:.3f}  "
            f"F1 {n['f1']:.3f}   spearman(score, keep) {self.spearman_score_vs_keep:+.3f}",
        ]
        if self.at_build:
            b = self.at_build
            lines.append(
                f"  at build   precision {b['precision']:.3f}  recall {b['recall']:.3f}  "
                f"F1 {b['f1']:.3f}"
            )
        lines += ["", "  keep rate by score band (where a floor belongs):"]
        for band, row in self.keep_rate_by_score_band.items():
            lines.append(f"    {band:<10} n={row['n']:<4} keep={row['keep_rate']:.2f}")
        for title, table in (
            ("by source type", self.by_source_type),
            ("by discovery route", self.by_discovered_via),
        ):
            if not table:
                continue
            lines += ["", f"  {title}:"]
            width = max(len(k) for k in table)
            for key in sorted(table):
                row = table[key]
                lines.append(
                    f"    {key:<{width}}  n={row['n']:<4} P={row['precision']:.2f} R={row['recall']:.2f}"
                )
        if self.labelled_drops_fetched_below_3:
            lines += ["", "  LABELLED DROPS THAT WOULD BE FETCHED WITH A SCORE UNDER 3:"]
            lines += [f"    {t}" for t in self.labelled_drops_fetched_below_3]
        return "\n".join(lines)


async def run(golden_path: Path, floor: float | None = None) -> TriageReport:
    golden = TriageGolden.load(golden_path)
    labelled = [c for c in golden.candidates if c.keep is not None]
    if not labelled:
        raise SystemExit(f"{golden_path} has no labelled candidates (keep is null everywhere).")
    floor = settings.FETCH_SCORE_FLOOR if floor is None else floor

    candidates = [c.candidate() for c in labelled]
    triaged = await triage_candidates(
        golden.topic, golden.key_concepts, golden.must_have_titles, candidates
    )
    ranked_ids = {id(t.candidate) for t in rank_candidates(triaged)}

    rows: list[dict[str, Any]] = []
    for label, item in zip(labelled, triaged, strict=True):
        priority = bool(item.candidate.metadata.get("fetch_priority"))
        would_fetch = id(item.candidate) in ranked_ids and (item.score >= floor or priority)
        rows.append(
            {
                "title": label.title,
                "url": label.url,
                "source_type": label.source_type,
                "discovered_via": label.discovered_via.split(":")[0],
                "keep": bool(label.keep),
                "score": item.score,
                "model_score": item.model_score,
                "status": item.status,
                "would_fetch": would_fetch,
                "fetched_at_build": label.ledger_outcome == "fetched"
                if label.ledger_outcome is not None else None,
                "why": label.why,
            }
        )

    predicted = [r["would_fetch"] for r in rows]
    actual = [r["keep"] for r in rows]
    at_build_rows = [r for r in rows if r["fetched_at_build"] is not None]
    return TriageReport(
        topic=golden.topic,
        golden_file=str(golden_path),
        model=settings.FAST_MODEL,
        floor=floor,
        labelled=len(rows),
        now=screening_precision_recall(predicted, actual),
        at_build=screening_precision_recall(
            [r["fetched_at_build"] for r in at_build_rows], [r["keep"] for r in at_build_rows]
        ) if at_build_rows else None,
        spearman_score_vs_keep=spearman([r["score"] for r in rows], [float(k) for k in actual]),
        keep_rate_by_score_band=_bands(rows),
        by_source_type=_split(rows, "source_type"),
        by_discovered_via=_split(rows, "discovered_via"),
        labelled_drops_fetched_below_3=[
            r["title"] for r in rows
            if not r["keep"] and r["would_fetch"] and (r["model_score"] or 0.0) < 3.0
        ],
        rows=rows,
    )


def _bands(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for low, high in _SCORE_BANDS:
        members = [r for r in rows if low <= r["score"] < high]
        keeps = sum(1 for r in members if r["keep"])
        table[f"{low:g}–{min(high, 10):g}"] = {
            "n": len(members),
            "keep_rate": round(keeps / len(members), 3) if members else 0.0,
        }
    return table


def _split(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(row)
    return {
        name: screening_precision_recall(
            [m["would_fetch"] for m in members], [m["keep"] for m in members]
        )
        for name, members in groups.items()
    }


def sample_for_labelling(
    screenings: list[dict[str, Any]], size: int = _DEFAULT_SAMPLE, seed: int = 0
) -> list[dict[str, Any]]:
    """Up to ``size`` candidates, two thirds from the band around the floor.

    Deterministic for a seed, so two people exporting the same job label the
    same candidates.
    """
    rng = random.Random(seed)
    band = [s for s in screenings if _BAND[0] <= (s.get("triage_score") or 0.0) < _BAND[1]]
    rest = [s for s in screenings if s not in band]
    take_band = min(len(band), (size * 2) // 3)
    chosen = rng.sample(band, take_band)
    chosen += rng.sample(rest, min(len(rest), size - take_band))
    if len(chosen) < size:
        leftover = [s for s in band if s not in chosen]
        chosen += rng.sample(leftover, min(len(leftover), size - len(chosen)))
    return sorted(chosen, key=lambda s: (s.get("round", 0), -(s.get("triage_score") or 0.0)))


async def export(job_id: int | None, out: Path, size: int, expert_name: str | None = None) -> None:
    from peritus.experts.repository import ExpertRepository
    from peritus.infrastructure.database import close_pool, get_pool, init_pool

    await init_pool()
    try:
        pool = get_pool()
        repo = ExpertRepository(pool)
        if expert_name is not None:
            found = await repo.get_by_name(expert_name)
            if found is None:
                raise SystemExit(f"No expert named {expert_name!r}.")
            screenings = await repo.latest_candidate_screenings(found.id)
            job_id = screenings[0]["job_id"] if screenings else None
        else:
            screenings = await repo.candidate_screenings(job_id) if job_id is not None else []
        if not screenings:
            raise SystemExit(
                f"No candidate_screenings rows for {'expert ' + expert_name if expert_name else f'job {job_id}'}."
            )
        expert = await repo.get_by_id(screenings[0]["expert_id"])
        async with pool.acquire() as conn:
            raw_plan = await conn.fetchval(
                "SELECT research_plan FROM experts WHERE id = $1", screenings[0]["expert_id"]
            )
    finally:
        await close_pool()

    plan = json.loads(raw_plan) if isinstance(raw_plan, str) else (raw_plan or {})
    sample = sample_for_labelling(screenings, size)
    golden = TriageGolden(
        topic=expert.topic if expert else "",
        key_concepts=list(plan.get("key_concepts") or (expert.key_concepts if expert else [])),
        must_have_titles=[w["title"] for w in plan.get("must_have_works") or []],
        job_id=job_id,
        candidates=[
            LabelledCandidate(
                url=s["url"],
                title=s["title"],
                source_type=s["source_type"],
                snippet=s.get("snippet") or "",
                author=s.get("author"),
                discovered_via=s["discovered_via"],
                ledger_score=s["triage_score"],
                ledger_outcome=s["fetch_outcome"],
            )
            for s in sample
        ],
    )
    golden.dump(out)
    print(
        f"Wrote {len(sample)} of {len(screenings)} candidates to {out}. Label each one's "
        "\"keep\" (true/false) and \"why\" without looking at ledger_score.",
        file=sys.stderr,
    )


async def _main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m peritus.eval.triage",
        description="Measure candidate triage against a human-labelled golden set.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("export", help="sample one build's screening ledger for labelling")
    ex.add_argument("out", type=Path)
    which = ex.add_mutually_exclusive_group(required=True)
    which.add_argument("--job", type=int, help="the build job's id")
    which.add_argument("--expert", help="an expert's name: its most recent build, job or not")
    ex.add_argument("--size", type=int, default=_DEFAULT_SAMPLE)
    rn = sub.add_parser("run", help="re-score a labelled golden set and report")
    rn.add_argument("golden", type=Path)
    rn.add_argument("--floor", type=float, default=None)
    rn.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.command == "export":
        await export(args.job, args.out, args.size, args.expert)
        return
    report = await run(args.golden, args.floor)
    print(report.to_json() if args.json else report.render())


if __name__ == "__main__":
    asyncio.run(_main())
