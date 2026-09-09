"""Measure the screening decision against human labels.

Every change to what gets kept — a new preview, a second opinion, a different
threshold, a different model — moves the corpus. Without a fixed labelled set,
the only signal after such a change is "the corpus looks different", and that is
not evidence of anything. This is the harness that turns it into a number.

    python -m peritus.eval.screening eval/golden/screening/<topic>.json

It reconstructs the exact ``RawSource`` objects the validator saw from a capture
file (see :mod:`peritus.sources.capture`), re-runs ``validate_sources`` against
them, and reports precision, recall and Cohen's kappa of the keep decision
against the human labels, plus concept-tagging agreement — split by source type
and by discovery path, because a rubric can improve on web articles and get
worse on preprints and the aggregate will hide it.

Two runs of this on the same golden file, under two rubric versions, are what
makes "screening got better" a claim rather than an assertion. The output
records ``rubric_version``, both model ids and whether the second opinion was on,
so two reports can be diffed without ambiguity about what produced them.

**What this does not do.** It does not label anything. The labels are human, and
a golden file with model-produced labels would measure the validator against
itself. See ``eval/golden/screening/README.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.eval.metrics import cohen_kappa, concept_jaccard, screening_precision_recall
from peritus.sources.capture import record_to_source
from peritus.sources.domain import RawSource
from peritus.sources.validator import RUBRIC_VERSION, review_model, validate_sources

logger = get_logger(__name__)


@dataclass
class Label:
    """One human decision about one source."""

    url: str
    decision: str                       # "keep" | "drop"
    reason: str = ""
    labeller: str = "human"
    covered_concepts: list[str] = field(default_factory=list)

    @property
    def keep(self) -> bool:
        return self.decision.strip().casefold() == "keep"


@dataclass
class GoldenSet:
    topic: str
    key_concepts: list[str]
    captured_from: str
    labels: list[Label]

    @classmethod
    def load(cls, path: Path) -> GoldenSet:
        data = json.loads(path.read_text())
        labels = [Label(**entry) for entry in data["labels"]]
        decisions = {label.decision.strip().casefold() for label in labels}
        unknown = decisions - {"keep", "drop"}
        if unknown:
            raise ValueError(f"{path}: unknown decision value(s) {sorted(unknown)}")
        return cls(
            topic=data["topic"],
            key_concepts=list(data.get("key_concepts") or []),
            captured_from=data.get("captured_from", ""),
            labels=labels,
        )

    def by_url(self) -> dict[str, Label]:
        return {_norm(label.url): label for label in self.labels}


@dataclass
class SourceOutcome:
    url: str
    title: str
    source_type: str
    discovered_via: str
    human_keep: bool
    model_keep: bool
    quality: float
    relevance: float
    validator_model: str | None
    reviewed: bool
    concept_agreement: float
    drop_reason: str | None


@dataclass
class ScreeningReport:
    topic: str
    golden_file: str
    rubric_version: str
    validator_model: str
    review_model: str
    second_opinion: bool
    labelled: int
    scored: int
    missing_from_capture: list[str]
    overall: dict[str, Any]
    kappa: float
    mean_concept_jaccard: float
    by_source_type: dict[str, dict[str, Any]]
    by_discovered_via: dict[str, dict[str, Any]]
    outcomes: list[SourceOutcome]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def render(self) -> str:
        lines = [
            f"Screening report — {self.topic}",
            f"  golden set      {self.golden_file}",
            f"  rubric          {self.rubric_version}",
            f"  validator       {self.validator_model}",
            "  second opinion  "
            + (f"on ({self.review_model})" if self.second_opinion else "off"),
            f"  scored          {self.scored} of {self.labelled} labelled",
        ]
        if self.missing_from_capture:
            lines.append(
                f"  MISSING         {len(self.missing_from_capture)} labelled "
                "source(s) absent from the capture file"
            )
        o = self.overall
        lines += [
            "",
            f"  precision {o['precision']:.3f}   recall {o['recall']:.3f}   "
            f"F1 {o['f1']:.3f}   kappa {self.kappa:+.3f}",
            f"  concepts (Jaccard vs human) {self.mean_concept_jaccard:.3f}",
            f"  confusion  kept-and-should {o['true_positives']}  "
            f"kept-but-shouldn't {o['false_positives']}  "
            f"dropped-but-shouldn't {o['false_negatives']}  "
            f"dropped-and-should {o['true_negatives']}",
        ]
        for title, table in (
            ("by source type", self.by_source_type),
            ("by discovery path", self.by_discovered_via),
        ):
            if not table:
                continue
            lines += ["", f"  {title}:"]
            width = max(len(k) for k in table)
            for key in sorted(table):
                row = table[key]
                lines.append(
                    f"    {key:<{width}}  n={row['n']:<4} "
                    f"P={row['precision']:.2f} R={row['recall']:.2f} "
                    f"kappa={row['kappa']:+.2f}"
                )
        return "\n".join(lines)


def _norm(url: str) -> str:
    from peritus.sources.dedup import normalise_url

    return normalise_url(url or "")


def load_capture(path: Path) -> list[RawSource]:
    """Every source in a capture file, de-duplicated by URL (last write wins)."""
    sources: dict[str, RawSource] = {}
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                sources[_norm(json.loads(line).get("url", ""))] = record_to_source(
                    json.loads(line)
                )
            except Exception as exc:
                logger.warning("%s:%d unreadable capture line: %s", path, line_no, exc)
    return list(sources.values())


async def run(golden_path: Path, capture_path: Path) -> ScreeningReport:
    golden = GoldenSet.load(golden_path)
    labels = golden.by_url()
    captured = {_norm(s.url): s for s in load_capture(capture_path)}

    # Score only what is both labelled and captured, and say plainly how many
    # labelled sources the capture could not supply. Quietly scoring a subset
    # would make an incomplete capture look like a good result.
    scored_urls = [u for u in labels if u in captured]
    missing = [labels[u].url for u in labels if u not in captured]
    if not scored_urls:
        raise SystemExit(
            f"None of the {len(labels)} labelled sources appear in {capture_path}. "
            "Check that captured_from points at the right capture file."
        )

    sources = [captured[u] for u in scored_urls]
    passed, dropped = await validate_sources(golden.topic, sources, golden.key_concepts)

    verdicts: dict[str, Any] = {}
    for vs in passed:
        verdicts[_norm(vs.url)] = (True, vs)
    for ds in dropped:
        verdicts[_norm(ds.raw.url)] = (False, ds)

    outcomes: list[SourceOutcome] = []
    for url in scored_urls:
        label = labels[url]
        entry = verdicts.get(url)
        if entry is None:
            missing.append(label.url)
            continue
        model_keep, verdict = entry
        raw = verdict.raw
        outcomes.append(
            SourceOutcome(
                url=raw.url,
                title=raw.title,
                source_type=raw.source_type.value,
                discovered_via=str(raw.metadata.get("discovered_via", "plan")),
                human_keep=label.keep,
                model_keep=model_keep,
                quality=verdict.quality_score,
                relevance=verdict.relevance_score,
                validator_model=verdict.validator_model,
                reviewed=bool(verdict.review_model),
                concept_agreement=concept_jaccard(
                    list(getattr(verdict, "covered_concepts", [])),
                    label.covered_concepts,
                ),
                drop_reason=None if model_keep else verdict.drop_reason,
            )
        )

    predicted = [o.model_keep for o in outcomes]
    actual = [o.human_keep for o in outcomes]
    return ScreeningReport(
        topic=golden.topic,
        golden_file=str(golden_path),
        rubric_version=RUBRIC_VERSION,
        validator_model=settings.FAST_MODEL,
        review_model=review_model(),
        second_opinion=settings.VALIDATE_SECOND_OPINION,
        labelled=len(labels),
        scored=len(outcomes),
        missing_from_capture=missing,
        overall=screening_precision_recall(predicted, actual),
        kappa=cohen_kappa(predicted, actual),
        mean_concept_jaccard=(
            round(sum(o.concept_agreement for o in outcomes) / len(outcomes), 4)
            if outcomes else 0.0
        ),
        by_source_type=_split(outcomes, lambda o: o.source_type),
        by_discovered_via=_split(outcomes, lambda o: o.discovered_via.split(":")[0]),
        outcomes=outcomes,
    )


def _split(outcomes: list[SourceOutcome], key) -> dict[str, dict[str, Any]]:
    """The same metrics per subgroup. A rubric can improve overall and regress
    on one source type; only the split shows it."""
    groups: dict[str, list[SourceOutcome]] = defaultdict(list)
    for outcome in outcomes:
        groups[key(outcome)].append(outcome)
    table: dict[str, dict[str, Any]] = {}
    for name, members in groups.items():
        predicted = [m.model_keep for m in members]
        actual = [m.human_keep for m in members]
        table[name] = {
            **screening_precision_recall(predicted, actual),
            "kappa": cohen_kappa(predicted, actual),
        }
    return table


async def _main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m peritus.eval.screening",
        description="Score the source validator against a human-labelled golden set.",
    )
    parser.add_argument("golden", type=Path, help="eval/golden/screening/<topic>.json")
    parser.add_argument(
        "--capture",
        type=Path,
        help=(
            "JSONL capture of the sources as the validator saw them. Defaults to "
            "the golden file's captured_from, resolved against SCREENING_CAPTURE_DIR."
        ),
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args()

    capture = args.capture
    if capture is None:
        golden = GoldenSet.load(args.golden)
        if not golden.captured_from:
            raise SystemExit(
                "No --capture given and the golden file has no captured_from. Run a "
                "build with SCREENING_CAPTURE_DIR set, then point one of them at "
                "the resulting .jsonl."
            )
        root = Path(settings.SCREENING_CAPTURE_DIR or ".")
        capture = root / golden.captured_from
    if not capture.exists():
        raise SystemExit(f"Capture file not found: {capture}")

    report = await run(args.golden, capture)
    print(report.to_json() if args.json else report.render(), file=sys.stdout)


if __name__ == "__main__":
    asyncio.run(_main())
