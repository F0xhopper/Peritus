# Plan: a larger, better-screened corpus

**Status:** implemented, 2026-09-07. Where this document and the code disagree,
the code is right — sections 0 to 6 below describe the pipeline *as it was
before* this work and are kept as the record of what changed and why.

## What shipped, and what did not

| Phase | State | Where |
|---|---|---|
| 0 · Measurement | **Partly.** Capture, runner and metrics shipped; the golden sets have not been built. | `sources/capture.py`, `eval/screening.py`, `eval/metrics.py`, `eval/golden/screening/` |
| 1 · Identity and dedup | Shipped | `sources/identifiers.py`, `sources/dedup.py`, migration 025 |
| 2 · Full-text chain | Shipped | `sources/fulltext.py` |
| 3 · Preview and second opinion | Shipped, reviewer **off by default** | `sources/preview.py`, `sources/validator.py` |
| 4 · Coverage targets and the loop | Shipped | `experts/coverage.py`, `experts/feedback.py`, `experts/builder.py` |
| 5 · Snowballing | Shipped | `sources/snowball.py` |
| 6 · Cost budget | Shipped, **estimator not yet calibrated** | `billing/pricing.py`, `billing/domain.py` |
| 7 · Rollout | Docs and clients updated; the measured numbers are still missing | — |

**Three things are deliberately not done, and each is blocking a claim rather
than a feature:**

1. **No golden set exists.** The harness to score screening against human labels
   is written and tested; the labels are not, because they have to be human and
   nobody has made them yet. Until they do, the changelog below stays empty and
   the README continues to say there is no accuracy figure. See
   `api/src/peritus/eval/golden/screening/README.md` for how to build one.
2. **The second opinion ships off** (`VALIDATE_SECOND_OPINION=false`). Phase 7
   says to measure it with and without on the golden set before flipping the
   default, and (1) is why that measurement cannot happen yet. Turning it on is
   one setting.
3. **The cost estimator is under-calibrated, and it reads low.** One measured
   build (STANDARD Thomism, 48 sources, 1,374 chunks): the chunk model is exact
   — it predicted 138 graph batches and the build ran 138 — but the $2.45
   forecast sat against $4.73 of post-discovery spend. That comparison is
   unfair, since post-discovery also covers entity resolution, reconciliation
   over 112 concepts and persona, which the estimator neither models nor is
   meant to; but the gap is too wide to be only those. **Under-forecasting is
   the dangerous direction** — the loop spends against this number, so a low
   estimate commits a build to more corpus than its budget covers.

   The attribution is not sharper because the measurement came from a script
   driving `ExpertBuilder` directly, and per-stage attribution is set by the
   *worker* forwarding progress events — so every dollar landed in the "other"
   bucket. To calibrate properly: run three builds through `peritus-worker` and
   read `GET /experts/{slug}/build/usage`, which returns the forecast beside the
   metered contextualisation and graph cost and their signed error. Then set the
   constants and the date next to `CALIBRATED_AT` in `billing/pricing.py`.

### Found by running it

Ten defects, all fixed, none of which inspection would have produced — four
of them are places where the plan's own instructions were followed and turned
out to be wrong in the field — including the one that mattered most, which
produced a Thomism expert containing nothing written by Aquinas. Recorded because each is a class of bug rather
than an incident.

1. **A bare string where a verdict was expected took the whole batch with it.**
   The tool schema asks for an array of objects; a model returned an array
   containing a string, `.get` raised out of the batch's result handler, and
   five sources were lost. The identical bug existed in graph extraction, where
   it cost ten chunks per occurrence — it fired four times across two builds.
   Both now drop the malformed entry and keep the batch, and in the validator's
   case the source is routed to the second-opinion path as unjudged rather than
   dropped for the model's formatting.
2. **`full_text_method` was NULL for 27 of 30 sources**, because only the four
   scholarly fetchers went through the resolver. Worse than a gap in the ledger:
   the validator's preview fell back to reading the absent flag as `abstract`,
   so it was told a 72,000-character Exa article was an abstract — a claim about
   depth, made to the one caller judging depth. Every source type now has a
   named retrieval method, stamped centrally rather than in seven fetchers.
3. **The count ceiling bound before the money did.** Phase 6.B says to raise
   `_BASE_FETCH_BUDGET` to 60 so the count rarely binds; that was missed. A live
   PRO build filled its 60-source count in round 0 and left round 1 able to add
   four sources with $4.71 of its $7.00 unspent. Raised, and — separately — the
   two limits no longer share a stop reason: reporting `budget_exhausted` when
   the money was untouched made the one surface this loop publishes a false
   statement. New reason: `source_limit`.
4. **Snowballing produced fifteen candidates and kept none.** The fetch queue
   orders by expected value per *dollar*, which ranks a long canonical paper
   below a cheap web page — precisely inverting the ranking for the highest-
   precision channel there is. Phase 5.A already said a work co-cited by two or
   more seeds should be "fetched ahead of everything else in the round"; that
   is now implemented, and such candidates skip the cost ordering.

5. **The content fingerprint could not fire.** The Hamming threshold of 3 that
   the plan specifies is the textbook near-duplicate value, and it is wrong for
   this data. Measured over 40 real corpus documents — 780 distinct pairs and 75
   same-document pairs transformed the way two renderings of one paper actually
   differ — distance 3 catches **9.3%** of true duplicates. It can only see
   documents differing by whitespace, which identity and URL dedup already
   catch, which is why it never fired once across three live builds.

   | distance | catches duplicates | wrongly merges distinct pairs |
   |---|---|---|
   | 3 (as planned) | 9.3% | 0.000% |
   | 8 | 52.0% | 0.000% |
   | **10 (chosen)** | **60.0%** | **0.000%** |
   | 12 | 72.0% | 0.128% |
   | 16 | 85.3% | 0.128% |

   10 rather than 12+ because the errors are asymmetric: a missed duplicate
   costs money and is visible in the ledger, a false merge silently deletes a
   good source. Replayed over 110 already-ingested sources the new threshold
   finds one genuine duplicate that shipped into a live corpus — the same
   Aristotle translation under two titles, at distance 7, with no shared
   identifier — and merges nothing else. ~40% of real near-duplicates still get
   through; a shingle simhash is a blunt instrument for two texts differing by a
   quarter of their sentences, and it should not be described as more.
6. **Per-type caps, not cost, were the real limit.** Phase 6.B says "per-type
   caps stay as they are", and with them staying, budgeting in dollars is
   decorative: on a live STANDARD build four of six productive types capped out
   at 43 sources while the count ceiling (60) and the money ($1.58 of $3.00)
   were both untouched. A cap fixed at `quota × 2` was sized for a 30-source
   budget and does not scale. It is now `headroom × the type's planned share of
   the budget`, so the caps sum to twice the budget — they shape the *mix* of
   the corpus and can never decide its *size*, which is the money's job. They
   are also computed once per build rather than per round, since a cap reapplied
   each round is not a cap on the corpus.

7. **Snowballing proposed works it could not possibly fetch.** Sixteen of
   twenty proposals on a real humanities corpus returned nothing: Semantic
   Scholar has no abstract for most books and older canonical works, so the
   openalex fetcher they are routed to returned `None` for want of anything to
   ingest, and the slot silently refilled. The sixteen included *Metaphors We
   Live By*, *The Cambridge History of Medieval Philosophy* and *Reasons and
   Persons* — exactly the canonical works the channel exists to surface, and
   because they were marked priority they were displacing candidates that could
   actually be read. Snowball now checks, before proposing, that some route to
   text exists (an abstract that can stand alone, an open-access PDF, an arXiv
   id or a PMCID) and logs the well-cited works it had to skip. On the same
   corpus: 20 proposals of which 4 were usable → **10 proposals, all 10 usable**.
8. **The plan's own phase 5.A priority rule was not implemented** (see 4 above),
   and with (7) it now works end to end. On a live round 1: three candidates
   co-cited by two or more accepted sources, **all three fetched**, two of them
   full-length works of 120,000 characters, found by following citations in both
   directions. Before these two fixes the channel had produced fifteen
   candidates and landed none.
9. **The budget reserved money for sources it would never ingest.** The ingest
   estimate is necessarily made at fetch time, before anything has been judged,
   so it covers every source fetched — but only the accepted ones are ever
   ingested. Holding the rejected ones' cost against the discovery budget stops
   the loop roughly a rejection-rate early: a live STANDARD build reserved
   $3.04 of a $3.00 budget for 60 fetched sources when only the 48 that passed
   would ever cost anything. The reservation for rejected sources is now
   released after each round's validation, before the stop conditions are
   evaluated.

10. **Phase 6.C's fetch ordering emptied the corpus of primary sources.** The
    worst of these, and the only one visible from the outside rather than in a
    log. "Once cost is known at fetch time, order the fetch queue by
    `triage_score / max(cost, floor)`" is what the plan says, and it is wrong:
    cost scales with length, the longest texts are the primary sources, and so
    the rule systematically removes the material a corpus most needs. A live
    STANDARD build of "Thomism" produced 48 sources containing **no work by
    Thomas Aquinas** — 29 secondary, 17 tertiary, 2 primary, and both of those
    were modern journal articles the validator mis-tiered.

    Everything upstream had worked. The planner named *Summa Theologica* and
    *Summa Contra Gentiles* as must-have works, weighted Project Gutenberg at
    2.0, and gave it the right queries; Gutenberg returned three hits. They
    were then ranked last by construction — a Reddit thread scoring 4 outranked
    the Summa scoring 9 by seven to one, because 120,000 characters cost ten
    times what a web page costs. The score-9 must-have override, which exists
    precisely so a canonical work can never be lost, was divided away by the
    denominator.

    The fetch order is now **triage score first, estimated cost only as a
    tiebreaker**, with a reserved front rank for candidates the pipeline has
    independent evidence about (a work the plan named, or one two or more
    accepted sources both cite). That keeps what cost-awareness was actually
    for — free full text ahead of paid OCR between two equally-rated papers —
    without letting price decide what a corpus is made of. Same topic, same
    tier, before and after:

    | | before | after |
    |---|---|---|
    | primary | 2 | **7** |
    | secondary | 29 | 25 |
    | tertiary | 17 | **11** |
    | works by Aquinas | **0** | Summa Theologica I and II-II, Summa Contra Gentiles ×2 |
    | Gutenberg sources | 0 | 1 (200,000 chars) |

    Also recovered: Maritain's *The Degrees of Knowledge*, another work the plan
    had named and the old ordering had lost.

Measured effect of (2), (3) and (6) together, same topic and tier, before and after:
23 accepted sources → 36 → **43**, at $2.59 of estimated ingest against the same
$3.00 discovery budget, with `full_text_method` populated on every row. The
money is now the constraint that binds, which is what phase 6 is for.

Two deviations from the plan as written, both deliberate:

- **Phase 5 was not deferred to a separate rollout flag.** Snowballing and the
  loop share the same round scaffolding, and the plan says they should land
  together — they did, under `DISCOVERY_LOOP`, which defaults to on for
  interactive builds and off for batched ones rather than being globally on.
- **The old gap-fill round is gone rather than kept alongside.** Its behaviour
  is round 1 at LITE targets, and running both would have meant two code paths
  answering the same question. Builds that already ran it keep their
  `coverage_gaps` / `gapfill_done` events, and the audit surface still reads
  them.

**Goal.** Turn corpus assembly from a single pass with a fixed source count into a
measured, iterating loop that stops when the syllabus is covered to a stated depth or
the money runs out, and that can prove its screening decisions are getting better
rather than merely changing.

**Scope.** Stages 0 to 2b of the build (`api/src/peritus/experts/builder.py`), the
fetchers and validator under `api/src/peritus/sources/`, the sources table, and the
build-event vocabulary the web and CLI clients consume. The chat side, the graph, ledger
overrides and living reviews are out of scope and listed as follow-ons at the end.

**Order.** Seven phases. Phase 0 (measurement) is a hard prerequisite for phases 3 to 6,
because every one of them changes what gets kept and there is currently no way to tell an
improvement from a regression. Phases 1 and 2 are independent of each other and can land
in either order. Phases 4 and 5 share the loop scaffolding and should land together.

---

## 0. What the pipeline does today, precisely

This section exists so the rest of the plan can say "change X" without re-deriving X.
Everything here was read from the code on 2026-09-07.

### 0.1 Discovery is one shot, sized by a count

`ExpertBuilder._build` (`builder.py`) runs: plan → `_stage_discover` → `_snowball_citations`
→ `_deduplicate_by_url` → `validate_sources` → `_fill_coverage_gaps` → persist → ingest.

| Constant | Value | Where |
|---|---|---|
| `_BASE_FETCH_BUDGET` | 30 | `builder.py:106` |
| Fetch budget | `max(5, round(30 × source_multiplier))` → 15 / 30 / 60 | `builder.py:390` |
| `_SEARCH_OVERFETCH` | 3 | `builder.py:107` |
| `_MIN_RESULTS_PER_QUERY` | 10 | `builder.py:124` |
| `_TYPE_CAP_FACTOR` | 2 (per-type cap = fetcher quota × 2) | `builder.py:113` |
| `_FETCH_CONCURRENCY` | 6 | `builder.py:108` |
| Fetcher base quotas | wikipedia 3 · gutenberg 4 · arxiv 2 · pdf 3 · youtube 3 · exa 5 · web 3 · reddit 5 · thought_leaders 3 · pubmed 2 · openalex 3 | `_build_fetchers`, `builder.py:295-307` |
| `source_multiplier` | 0.5 / 1.0 / 2.0 | `experts/domain.py:58-86` |
| Spend cap | $3 / $6 / $12 | `experts/domain.py:123-127` |

`source_multiplier` is consumed in exactly two places (`builder.py:384` and `:390`), so
changing what "budget" means is a contained change.

### 0.2 Snowballing is tiny and runs before validation

`_snowball_citations` (`builder.py:1211`): seeds are any fetched source with an arXiv id or
DOI in `RawSource.metadata`, capped at `_SNOWBALL_MAX_SEEDS = 3`; each seed pulls 20
references from Semantic Scholar; a reference is kept only if `citationCount >= 50`
(`_SNOWBALL_MIN_CITATIONS`); at most `max_extra = 3` are fetched. It runs on
`raw_sources` before `validate_sources`, so the seeds have not themselves been judged yet.
Backward citations only. No forward citations, no co-citation counting.

### 0.3 Gap-fill is one narrow round with no triage

`_fill_coverage_gaps` (`builder.py:892`): coverage is binary (`_compute_coverage`, a
concept is a gap only at zero accepted sources); at most `_GAPFILL_MAX_CONCEPTS = 4`
concepts; per concept, each of `_GAPFILL_FETCHERS` runs one query `f"{topic} {concept}"`
for `_GAPFILL_RESULTS_PER_QUERY = 2` results and fetches them directly, bypassing triage.
Results are validated and tagged `discovered_via = gapfill:<concept>`.

### 0.4 Identity is not tracked; dedup is URL and title only

- `SourceCandidate` and `RawSource` (`sources/domain.py`) have no identifier fields. DOI,
  arXiv id, PMID, PMCID and OpenAlex id live only in the free-form `metadata` dict.
- The `sources` table has no identifier columns and no metadata column, so **DOI and
  arXiv id never reach the database** (`_persist_sources`, `builder.py:~985-1035`).
- Dedup is `_deduplicate_by_url` (`builder.py:1763`, `url.rstrip("/").lower()`) plus a
  near-duplicate title check in `rank_candidates` (`sources/triage.py:290-313`,
  `SequenceMatcher` ratio ≥ 0.85). The same paper as arXiv preprint, journal DOI and
  Semantic Scholar OA PDF survives all three checks.
- The PDF fetcher (`sources/fetchers/pdf.py:45-47`) requests `externalIds` from Semantic
  Scholar and then discards them; its candidates carry only `semantic_scholar_id` and
  `year`.

### 0.5 Full text: mostly good, with specific holes

| Fetcher | Full text path | Fallback | Cap |
|---|---|---|---|
| pubmed | Europe PMC `fullTextXML` when `pmcid` and open access | title + abstract | 120k chars |
| openalex | OA PDF via Mistral OCR, else OA landing page via the web fetcher | title + abstract | 120k (landing page 50k) |
| arxiv | ar5iv HTML | title + summary | 120k, and it does not prepend title/abstract |
| pdf | Mistral OCR of the OA PDF URL | none, returns `None` | 200k |
| exa | `get_contents` | none | 80k |
| web | page text, prefers `<article>`/`<main>` | none | 50k |

Holes: a biomedical DOI found through OpenAlex goes through OCR or a landing page even
when Europe PMC has free JATS full text for it; an arXiv paper whose ar5iv render fails
gets abstract only although the PDF is one fetch away; a DOI-only snowball reference is
resolved by `openalex_by_doi` and then a landing page. Unpaywall is not needed: OpenAlex's
`best_oa_location` already ingests it.

### 0.6 Validation sees about 2,400 characters, once, on Haiku

`validate_sources` (`sources/validator.py:209`): batches of 5, `settings.FAST_MODEL`,
forced tool call. The model sees `_build_preview(text)`: the whole text if ≤ 2,400 chars,
else head 800 + middle 800 + tail 800. Thresholds `q ≥ 5.0`, `r ≥ 6.0`; rubric
`v4-tiered-q5r6`. A source is judged exactly once. `_persist_sources` writes
`validator_model = settings.FAST_MODEL` for every row rather than what actually judged it.
An errored batch drops all five of its sources with `drop_reason = "validation error"`.

### 0.7 Nothing measures screening

`eval/` (runner, metrics, compare, helpfulness) scores chat answers only. No golden set
of keep/drop decisions exists; no code computes validator precision or recall; a rubric
change from v3 to v4 has no number attached.

### 0.8 Cost is metered per build but not used for decisions

`billing/metering.py` `BuildMeter` records every Claude and embedding call, attributes it
to a stage from the builder's events, exposes `spent_usd` and sets `over_cap` at the tier
cap. The builder can reach it via `current_meter()`. Nothing in the builder reads it; the
only consumer is the worker's heartbeat, which cancels the build when the cap is hit.

Cost per source is dominated by ingestion, which scales with **characters**, not source
count: a 120k-char paper is ~80 chunks, each a contextualisation call with a 3k-char
window, plus embedding, plus a share of graph extraction. OCR is priced per page on top.
Validation (≤ 2.4k chars in, ≤ 512 tokens out) is the cheap step. A "budget" expressed in
sources therefore has no fixed relationship to spend.

---

## Phase 0. Measure screening before touching it

**Why first.** Phases 3 to 6 all change which sources are kept. Without a fixed labelled
set, the only signal after each change is "the corpus looks different", which is not
evidence. This phase is small and unblocks everything else.

### 0.A Capture raw sources during a build

The `sources` table stores no text, and dropped sources have no chunks, so a fixture
cannot be rebuilt from the database. Add an opt-in capture.

- `core/config.py`: `SCREENING_CAPTURE_DIR: str = ""`. When set, the builder writes one
  JSONL line per `RawSource` that reaches `validate_sources`, before validation, to
  `<dir>/<expert_slug>/<job_id>.jsonl`: `source_type, url, title, author, text,
  metadata, discovered_via`. Also write a `manifest.json` with `topic, key_concepts,
  rubric_version, validator_model`.
- Implementation point: a thin wrapper around `validate_sources` in `builder.py`, so
  gap-fill and later loop rounds are captured too. Do not put it inside the validator.

### 0.B A screening golden set

`eval/golden/screening/<topic-slug>.json`:

```json
{
  "topic": "intermittent fasting and cardiometabolic risk",
  "key_concepts": ["…"],
  "captured_from": "<expert_slug>/<job_id>.jsonl",
  "labels": [
    {"url": "…", "decision": "keep" | "drop", "reason": "…", "labeller": "human",
     "covered_concepts": ["…"]}
  ]
}
```

Labels are human. Start with three topics of different shape (one biomedical, one
humanities, one practitioner craft) and 40 to 60 sources each, sampled to over-represent
the band around the threshold, since that is where errors live. Include every
`discovered_via` value.

### 0.C A screening runner

`eval/screening.py`, mirroring `eval/runner.py`'s shape:

```
python -m peritus.eval.screening path/to/golden.json [--capture path.jsonl]
```

- Reconstructs `RawSource` objects from the capture file, calls `validate_sources`
  (live execution, not batched), and compares to labels.
- Reports, per rubric version and model: precision and recall of `keep`, Cohen's kappa
  against the human label, agreement on `covered_concepts` (Jaccard), and a confusion
  table split by `source_type` and by `discovered_via`.
- Pure metric functions go in `eval/metrics.py` next to the chat ones
  (`screening_precision_recall`, `cohen_kappa`, `concept_jaccard`) with unit tests in
  `tests/unit/test_eval_metrics.py`.
- Output is JSON plus a short rendered table, and it records `RUBRIC_VERSION` so two
  runs can be diffed.

### 0.D Record who actually judged each source

Migration `025_validator_provenance.sql` is not needed for this step; the column exists.
Change `_persist_sources` to take `validator_model` from the `ValidatedSource` /
`DroppedSource` rather than from settings. Add `validator_model: str` to both
dataclasses, set by the validator. Phase 3 depends on this.

**Acceptance.** Three golden files committed; the runner reproduces the current
`v4-tiered-q5r6` numbers; those numbers are written into this document's changelog as
the baseline.

---

## Phase 1. Identity and deduplication

**Why.** A bigger corpus that contains the same paper three times is worse than a smaller
one, and every duplicate is paid for three times (fetch, validate, contextualise, embed,
graph). Identity is also what phase 5 (snowballing) keys on.

### 1.A Identifiers on the domain objects

`sources/domain.py`:

```python
@dataclass
class Identifiers:
    doi: str | None = None          # bare, lowercased, no https://doi.org/
    arxiv_id: str | None = None     # bare, version stripped
    pmid: str | None = None
    pmcid: str | None = None
    openalex_id: str | None = None  # W…
    s2_id: str | None = None        # Semantic Scholar paperId

    def canonical_key(self) -> str | None:
        """First non-null in priority order doi → arxiv → pmcid → pmid → openalex → s2."""
```

Add `identifiers: Identifiers = field(default_factory=Identifiers)` to both
`SourceCandidate` and `RawSource`. Keep `metadata` as is so nothing else breaks; the
builder's snowball seeds and the fetchers migrate to the typed field.

Normalisation helpers in a new `sources/identifiers.py`: `normalise_doi`,
`normalise_arxiv_id` (reuse `arxiv._extract_id`), `doi_from_url`, `arxiv_id_from_url`.
The URL-based ones matter because exa and web find arXiv and doi.org URLs all the time and
currently carry no ids at all.

### 1.B Fetchers populate them

| Fetcher | Change |
|---|---|
| pubmed | move `pmid, pmcid, doi` from metadata into `identifiers` (keep metadata copies for one release) |
| openalex | `openalex_id, doi`; also read `ids.pmid` / `ids.pmcid` from the OpenAlex work record, which it already returns |
| arxiv | `arxiv_id`; read `doi` from `paper.doi` (the `arxiv` library exposes it) |
| pdf | **stop discarding `externalIds`**: `DOI`, `ArXiv`, `PubMed`, `PubMedCentral` → identifiers; `paperId` → `s2_id` |
| exa, web | `doi_from_url` / `arxiv_id_from_url` on the candidate URL |
| snowball | build `RawSource.identifiers` from the Semantic Scholar `externalIds` it already fetches |

Unit tests: extend `tests/unit/test_pubmed_fetcher.py`, `test_openalex_fetcher.py`; add
`test_identifiers.py` for the normalisers; add a pdf fetcher test with a recorded
Semantic Scholar payload asserting the ids are kept.

### 1.C Persist them

Migration `025_source_identifiers.sql`:

```sql
ALTER TABLE sources
    ADD COLUMN doi TEXT,
    ADD COLUMN arxiv_id TEXT,
    ADD COLUMN identifiers JSONB;
CREATE INDEX idx_sources_expert_doi ON sources (expert_id, doi) WHERE doi IS NOT NULL;
CREATE INDEX idx_sources_expert_arxiv ON sources (expert_id, arxiv_id) WHERE arxiv_id IS NOT NULL;
```

`_persist_sources` writes all three for passed and dropped rows. `uploads/repository.py`
`insert_source` accepts them as optional. The audit corpus report and the RIS export
(`audit/` and `sources_to_ris`) gain `DO` and `ID` fields; RIS without a DOI is a weak
export for the users the README targets.

### 1.D Identity dedup before triage, content dedup before validation

Replace `_deduplicate_by_url` with `_deduplicate_candidates` in `sources/dedup.py`:

1. **Identity.** Group by `identifiers.canonical_key()`; keep one per group. Preference
   order when merging: the candidate whose fetcher will yield the best full text (arxiv or
   pubmed with pmcid > openalex with OA PDF > pdf > exa > web), and union the other
   candidates' identifiers and `discovered_via` provenance into it. Record the losers in
   the candidate's metadata as `merged_from: [urls]` so the ledger can show them.
2. **URL.** Existing behaviour, after stripping tracking params and `www.`, and mapping
   `arxiv.org/pdf/<id>` ↔ `arxiv.org/abs/<id>` ↔ `ar5iv…/<id>` to one key.
3. **Title.** Existing near-duplicate check, kept.

After fetch and before validation, add **content fingerprinting** on `RawSource.text`:
a simhash over word 5-shingles (pure Python, no model call, ~1 ms per source). Hamming
distance ≤ 3 on a 64-bit hash means the same document. This catches the preprint versus
published-version case that identity misses when one side has no DOI. Keep the copy with
more text; note the other as `duplicate_of` in the dropped ledger with
`drop_reason = "duplicate of <url>"` so it is visible, not silently gone. Do **not** use
embeddings here: they cost money and the chunk embeddings do not exist yet at this point.

Emit a `dedup_done` event: `{candidates, identity_merged, url_merged, title_merged,
content_merged}`. The audit `screening-flow` should surface these as an explicit stage
so the count of records identified versus screened stays honest.

Tests: `tests/unit/test_dedup.py` with the arXiv/DOI/S2 triple, the preprint/published
pair, and a near-title false positive (two different books by the same author, which
`test_source_discovery.py` already guards against for must-have matching).

**Acceptance.** On the three golden capture files, zero identity-duplicates reach
validation; the screening runner's totals change only by the removed duplicates.

---

## Phase 2. A full-text resolution chain

**Why.** Full text over abstract is the largest per-source quality gain available, and it
is also what makes phase 3's richer preview possible. The pieces exist; they are not
composed.

### 2.A One resolver, used by every scholarly path

New `sources/fulltext.py`:

```python
async def resolve_full_text(ids: Identifiers, hints: FullTextHints) -> FullText | None
```

`FullTextHints` carries what a fetcher already knows (`oa_pdf_url`, `oa_landing_url`,
`is_open_access`). The chain, stopping at the first result ≥ `MIN_FULL_TEXT` (3,000
chars):

1. arXiv id → ar5iv HTML (existing `fetch_ar5iv`); on failure or short text → arXiv PDF
   via Mistral OCR when `MISTRAL_API_KEY` is set.
2. pmcid, or pmid resolved to pmcid via Europe PMC's id converter → Europe PMC
   `fullTextXML` (existing `pubmed.fetch_full_text` and `_jats_to_text`). This is free,
   fast, and structured; prefer it over OCR whenever it exists, whichever fetcher found
   the source.
3. `oa_pdf_url` → Mistral OCR (existing `parse_pdf_url`).
4. `oa_landing_url` → web fetcher page text, raised from 50k to 120k chars for parity.
5. DOI with none of the above → `openalex_by_doi` to obtain hints, then steps 2 to 4.

Return `FullText(text, method, chars)` and record `method` in `RawSource.metadata`
(`full_text_method`) so the ledger can say how a source's text was obtained. Extend the
`sources` table in the same migration as phase 1 with `full_text_method TEXT` and
`text_chars INTEGER`; both are cheap and both are exactly what a reviewer asks.

### 2.B Fetchers call it

- `openalex.fetch`: replace `_fetch_open_access_text` with the resolver. Biomedical
  OpenAlex results now get Europe PMC XML rather than OCR of the publisher PDF.
- `pubmed.fetch`: unchanged behaviour, routed through the resolver for one code path.
- `arxiv.fetch`: gains the PDF fallback; also prepend `title + summary` to the full text
  the way pubmed and openalex do, so the validator preview's head is the abstract.
- `_snowball_fetch_one`: use the resolver for both the arXiv and DOI branches.
- `pdf.fetch`: unchanged (it already has a PDF URL), but the identifiers from 1.B let the
  resolver try Europe PMC first when the paper has a pmcid, which avoids an OCR charge.

### 2.C Cost-aware fetch order

OCR is the one paid step in fetching. `_fetch_with_refill` should sort each wave so that
candidates whose resolver path is free (ar5iv, Europe PMC, HTML) go first and OCR
candidates go last; with a fixed budget this alone shifts spend towards text. Phase 6
formalises this with an estimate; here it is a sort key.

Tests: resolver unit tests with recorded fixtures per step (`tests/unit/test_fulltext.py`),
asserting the chain order and the recorded `method`. Existing fetcher tests keep passing.

**Acceptance.** On a biomedical golden topic, the share of accepted scholarly sources
with `full_text_method` other than `abstract` rises, and OCR calls per build fall. Both
are readable from `build/usage` and the new column.

---

## Phase 3. Validation: a better preview and a second opinion at the margin

**Why.** The validator is grading about 2,400 characters. It is fast and cheap, which is
right for the bulk of sources, but the sources that matter most are the ones near the
threshold, and those deserve a closer read. Phase 0 makes the effect measurable.

### 3.A A structured preview

Replace `_build_preview` with `build_preview(raw: RawSource) -> str` in
`sources/preview.py`:

- **Head:** title, author, source type, year and venue when known, and the abstract
  when the fetcher captured one (pubmed, openalex, arxiv, pdf all have it in metadata).
- **Structure:** up to 12 section headings detected by `ingestion/chunker._detect_sections`
  (already written, currently only used at chunk time), so the model sees the shape of
  the document.
- **Samples:** two 700-char windows from the body, chosen from the first and last
  thirds, excluding the reference list.
- **Tail signals:** character count, whether a reference list was detected and roughly
  how long, `full_text_method`, `discovered_via`, and citation count when the fetcher
  had it. These are facts the model would otherwise infer badly from a text window.

Budget: ≤ 3,500 chars. That is a modest increase per source at Haiku prices and the
batch of 5 still fits comfortably. Bump `RUBRIC_VERSION` to `v5-structured-q5r6` because
the input changed even if the thresholds did not, and screening runs must be able to tell
the two apart.

### 3.B Second opinion in the borderline band

After the first pass, sources with `4.0 ≤ q < 6.0` or `5.0 ≤ r < 7.0` (either side of
each threshold) go to a second call on `settings.CLAUDE_MODEL` (Sonnet) with a larger
preview (≤ 12,000 chars: abstract, headings, and four body windows). The second verdict
replaces the first. Expected volume is 15 to 25 % of sources, one per call, so the cost
is bounded and small relative to ingestion.

- New config: `VALIDATE_SECOND_OPINION: bool = True`, `VALIDATE_REVIEW_MODEL` defaulting
  to `CLAUDE_MODEL`, band edges as constants in the validator.
- Both verdicts are kept: add `review_model TEXT`, `first_pass_quality REAL`,
  `first_pass_relevance REAL` to `sources` (same migration). The ledger and CSV export
  show that a decision was reviewed and what the first pass said. The `validator_model`
  column (from 0.D) records the model whose verdict stands.
- `drop_reason` on a reviewed drop is the reviewer's reason.
- Emit `source_reviewed` events with both score pairs so the build log shows the
  reversal when one happens.

### 3.C Fail-open on batch errors, not fail-drop

Today an errored batch drops five sources as `validation error`. With the second-opinion
path in place, route the members of an errored batch through it individually instead of
dropping them; only if that also fails do they drop with the existing reason. Cheap
insurance against a single bad batch removing a fifth of a lite corpus.

Tests: `tests/unit/test_validator.py` (new): band selection, reviewer overrides first
pass, errored-batch rerouting, rubric version string. Screening runner comparison:
`v4` versus `v5` versus `v5 + review` on the same golden captures, numbers into the
changelog.

**Acceptance.** Kappa against human labels on the golden set rises with the second
opinion enabled, and precision in the borderline band rises by more than the overall
figure. If it does not, the band edges are wrong, not the idea; adjust and re-run.

---

## Phase 4. Coverage targets and an iterating discovery loop

**Why.** This is the structural change. Everything else in this plan makes a single pass
better; this phase makes the number of passes a function of the evidence rather than a
constant.

### 4.A Coverage becomes a target, not a boolean

Replace `_compute_coverage` with a `CoverageReport` in `experts/coverage.py`:

```python
@dataclass(frozen=True)
class ConceptCoverage:
    concept: str
    sources: int                  # accepted sources tagged with it
    source_types: set[SourceType]
    tiers: set[str]               # primary / secondary / tertiary
    met: bool

@dataclass(frozen=True)
class CoverageTarget:
    min_sources: int
    min_source_types: int
    require_non_tertiary: bool
```

Tier defaults, added to `ExpertConfig` (they belong with retrieval settings, and
`ExpertConfig` is what the builder already reads):

| Tier | min_sources | min_source_types | require_non_tertiary | max_rounds |
|---|---|---|---|---|
| LITE | 1 | 1 | no | 1 |
| STANDARD | 2 | 2 | yes | 2 |
| PRO | 3 | 2 | yes | 3 |

`max_rounds` counts discovery rounds **after** the first; LITE keeps today's behaviour
(one gap-fill-style round) so its cost profile does not move. Existing
`ExpertConfig.from_tier` and `test_expert_config.py` are the places to extend.

`CoverageReport.weakest(n)` returns the concepts furthest from target, ordered by
shortfall, which is what the next round searches for.

### 4.B The loop

Restructure `_build` stages 1 to 2b into:

```
plan
round 0:  discover (search → dedup → triage → fetch) → validate → coverage
while coverage not met and round < max_rounds and spend < discovery budget:
    round n:  feedback queries for weakest concepts
              → search (loop fetchers only) → dedup against everything seen
              → triage (same brief) → fetch (remaining budget)
              → snowball from newly accepted scholarly sources   (phase 5)
              → validate → coverage
stop with a stated reason
```

Concretely in `builder.py`:

- Extract the body of `_stage_discover` into `_discovery_round(queries_by_fetcher,
  budget, seen, on_event, round_n)` that takes an explicit query plan and a `SeenSet`
  (identity keys + URLs + simhashes from phase 1) so later rounds never re-fetch.
- `_fill_coverage_gaps` is deleted; its behaviour is round 1 with the LITE targets.
- Loop fetchers are today's `_GAPFILL_FETCHERS` plus `openalex` and `pubmed` (already
  there) and `arxiv`; the identify-then-fetch fetchers (gutenberg, thought_leaders) and
  the noisy ones (reddit, youtube) stay round-0 only, for the reason the existing
  comment gives.
- Per-round fetch budget: `round_budget = min(remaining_count_budget,
  ceil(0.5 × round_0_budget))`, so a later round can add at most half the initial corpus.
  Phase 6 replaces the count with cost.
- Stop reasons, emitted in a `discovery_done` event and stored in
  `experts.build_summary` (new JSONB column, same migration as phase 1):
  `targets_met`, `max_rounds`, `budget_exhausted`, `no_new_candidates`,
  `acceptance_collapsed` (a round accepted < 20 % of what it fetched, which means the
  search space is exhausted and another round would be spend without return).

### 4.C Feedback queries

Round 0's queries come from the planner reading only the topic. Later rounds should read
the corpus. `experts/feedback.py`:

```python
async def feedback_queries(topic, weakest: list[ConceptCoverage],
                           accepted: list[ValidatedSource]) -> dict[str, list[str]]
```

One `FAST_MODEL` call. Input: the weak concepts with their current counts, and for each
of the top accepted sources its title, `key_claims`, and `covered_concepts`. Output: 1 to
2 queries per weak concept per loop fetcher, using the field's own vocabulary as it
appears in the accepted material, plus author names and venues worth searching directly.
This is pseudo-relevance feedback, and it is the cheapest large gain in this plan because
the planner's blind queries are the main reason niche concepts come back empty.

Fallback when the call fails: today's `f"{topic} {concept}"`.

### 4.D Events, clients and the audit surface

New events: `round_started {round, targets, weakest}`, `feedback_queries {round,
queries}`, `dedup_done`, `coverage_report {round, concepts: [...]}`, `discovery_done
{rounds, stop_reason}`. Existing per-round events (`fetcher_done`, `triage_done`,
`fetch_done`, `validate_done`) gain a `round` field.

- `web/lib/api/types.ts` and `web/components/experts/build-progress.tsx`: render rounds
  as nested groups and the final coverage table with targets.
- `cli/src/api/types.rs`: the CLI parses the full event vocabulary with serde tests
  pinned to captured payloads; add the new variants and capture new fixtures from a real
  build, or the TUI will fail to parse the stream.
- `billing/metering.py` `_EVENT_STAGE_MAP`: map the new event names to stages
  (`round_*`, `feedback_queries`, `dedup_done` → TRIAGE) so spend attribution keeps
  working.
- `audit/service.py` screening flow: sum counts across rounds and expose `rounds` and
  `stop_reason`; update `method_statement`. `tests/unit/test_audit_screening.py` and
  `tests/api/test_audit_endpoints.py` cover this surface.
- `docs/build-flow.md` and the README's build diagram: redraw stages 1 to 2b as the loop.

### 4.E Batched execution

In `BuildExecution.BACKGROUND` mode each validation pass is a Message Batch that can
queue for up to an hour, and the loop multiplies that. Two rules: the loop's per-round
`gather_claude_calls` fall below `ANTHROPIC_BATCH_MIN_REQUESTS` for small rounds and run
live anyway; and a rebuild (which is what takes the batched path) inherits the previous
build's `build_summary.stop_reason` and starts at round 1 with the prior corpus's coverage
already known, rather than re-running round 0 blind. The second rule is the seed of the
"living review" follow-on and can be left as a stub that simply logs for now.

Tests: `tests/integration/test_build_loop.py` with fetchers and validator stubbed
(follow `test_build_degradation.py`): targets met in round 1 stops; acceptance collapse
stops; max rounds stops; seen-set prevents refetch; LITE runs exactly one round.

**Acceptance.** On a STANDARD build of each golden topic, every key concept reaches its
target or the stop reason says why, and the build log shows the queries each round used.

---

## Phase 5. Snowballing that pulls its weight

**Why.** Accepted sources vouch for what they cite. It is the highest-precision discovery
available and it is currently capped at three papers.

Runs inside the loop after each round's validation, seeded only from **accepted**
scholarly sources found in that round (round 0 included), so a junk paper's references
never enter.

### 5.A Backward, forward, and co-citation

`sources/snowball.py`, replacing the builder's private functions:

- Seeds: every accepted source with an `Identifiers.canonical_key()` resolvable by
  Semantic Scholar (arXiv, DOI, pmid, s2_id), no cap on seed count; requests are batched
  through the S2 `paper/batch` endpoint (up to 500 ids per call) to stay polite.
- **Backward:** references, `limit=100` rather than 20.
- **Forward:** `paper/{id}/citations`, `limit=100`, sorted by citation count. Forward
  citation is how a corpus finds the work that superseded a seed, which the planner
  cannot know about.
- **Co-citation score:** for each candidate, count how many distinct seeds cite or are
  cited by it. Rank by `(co_citation_count, percentile_of_citation_count_within_its_list)`.
  The percentile replaces the flat 50-citation floor: a reference in the top 20 % of its
  own list is worth fetching whatever the field's absolute numbers are. A candidate
  co-cited by two or more seeds is fetched ahead of everything else in the round.
- Candidates enter the round's **triage** as `SourceCandidate`s with identifiers, a
  snippet from the S2 abstract, and `discovered_via = snowball:backward` or
  `snowball:forward`, instead of bypassing triage as today. Triage's domain prior gives
  them a small lift via `doi.org`/`arxiv` already.
- Fetch through the phase 2 resolver.

### 5.B Depth by tier

| Tier | hops | max per round |
|---|---|---|
| LITE | 1 | 3 (today's number) |
| STANDARD | 1 | 10 |
| PRO | 2 | 20 |

Two hops means accepted snowball finds seed the next round's snowball, which the loop
gives for free.

### 5.C Ledger

`discovered_via` values become `snowball:backward`, `snowball:forward`; add
`snowball_seed_ids JSONB` on `sources` (which accepted sources led here, by `sources.id`)
so the corpus report can draw the citation trail. This is the "reference trail" the
README already promises and can only half deliver.

Tests: `tests/unit/test_snowball.py` with recorded S2 payloads: co-citation ranking,
percentile threshold, forward and backward tagging, seen-set exclusion, tier caps.

**Acceptance.** On a scholarly golden topic at STANDARD, snowball contributes at least a
quarter of accepted sources and its acceptance rate at validation exceeds the plan
fetchers' rate. If it does not exceed it, the ranking is wrong.

---

## Phase 6. Budget the corpus in estimated cost

**Why.** The count budget (15 / 30 / 60) treats a 2,000-character blog post and a
120,000-character monograph as the same unit. Cost scales with characters and with OCR.
A budget in estimated dollars lets a pro build take 150 open-access papers instead of 60
mixed sources for the same spend, and it makes the loop's stop condition honest.

### 6.A An estimator, not the meter

The meter reports actual spend but only after the fact, and ingestion (the expensive
step) happens after the loop has already decided what to keep. So the loop needs an
**estimate** of what a candidate will cost to ingest, made at fetch time:

```python
def estimated_ingest_cost_usd(text_chars: int, ocr_pages: int) -> Decimal
```

in `billing/pricing.py` next to the existing per-model prices (`test_billing_pricing.py`
covers that module). Inputs: chunk count = `chars / CHUNK_SIZE_CHARS`; per chunk one
contextualisation call (`CONTEXT_MAX_CHARS` window + chunk, FAST_MODEL, batched price
when `should_batch`), one embedding (`EMBED_MODEL` per-token price), and 1/`GRAPH_BATCH_SIZE`
of a graph-extraction call; plus OCR per page. Calibrate the constants once against three
real builds' `build/usage` breakdowns and write the calibration date next to them.

### 6.B Two budgets, clearly named

- `discovery_budget_usd` per tier, a **soft target** the loop spends towards: starting
  values LITE 1.25 / STANDARD 3.00 / PRO 7.00, chosen to leave room under the hard caps
  (3 / 6 / 12) for graph, reconciliation and persona. These live in `TierEconomics`
  beside `spend_cap_usd`, with the same env override pattern
  (`PERITUS_TIER_DISCOVERY_{TIER}_USD`).
- The hard cap is unchanged and still enforced by the worker. The loop additionally reads
  `current_meter().spent_usd` at each round boundary and stops with
  `budget_exhausted` when `spent + committed_estimate ≥ discovery_budget`.

`fetch_budget` as a count is retained as a ceiling (raise `_BASE_FETCH_BUDGET` to 60
so the ceiling rarely binds) and `_fetch_with_refill` gains a running
`committed_estimate` that stops the wave when the estimate would exceed the round's
share of the discovery budget. Per-type caps stay as they are.

### 6.C Value per dollar in triage order

Once cost is known at fetch time, order the fetch queue by `triage_score / max(cost,
floor)` rather than triage score alone, with a floor so a free 800-character page does not
outrank a paper. This is the point at which the pipeline stops preferring whatever
happened to rank first and starts preferring evidence per dollar. Ties and must-have
works keep their score-9 override.

### 6.D Surfaces

- `build/usage` already returns stage breakdowns; add `discovery_budget_usd`,
  `estimated_ingest_usd` and `actual_ingest_usd` so the estimator's error is visible and
  can be recalibrated.
- `coverage_report` and `discovery_done` events carry `spent_usd` and `budget_usd`.
- Web build progress shows a budget bar per round.

Tests: `tests/unit/test_billing_pricing.py` for the estimator; loop tests from phase 4
extended with a budget stop; a tier test in `test_builder_tiers.py` asserting PRO's
discovery budget is under its cap.

**Acceptance.** Estimator error on three real builds within 25 % of metered ingest
cost. A PRO build of a scholarly topic accepts more sources than before at equal or
lower metered spend, with the difference visible in `build/usage`.

---

## Phase 7. Rollout, calibration, and the numbers to publish

1. Land phase 0 alone. Record the baseline in the changelog below.
2. Land phases 1 and 2 behind no flag; they remove waste and add text, and neither
   changes verdict logic. Re-run the screening runner: the numbers should not move
   except through removed duplicates.
3. Land phase 3 with `VALIDATE_SECOND_OPINION=false` by default, run the screening
   runner with it on and off, then flip the default if kappa improves.
4. Land phases 4 and 5 together behind `DISCOVERY_LOOP_ENABLED` (default on for
   INTERACTIVE builds, off for BACKGROUND until the batched-latency behaviour in 4.E is
   confirmed on a real rebuild).
5. Land phase 6 after three builds' worth of usage data exist for calibration.
6. Update `README.md` ("What happens when you type a topic", steps 3 to 6), the build
   diagram, `docs/build-flow.md`, `docs/audit-api.md` (new columns, new events, rounds
   in screening flow), and the README's "what it is not" paragraph, which can then say
   that screening has a measured agreement rate against human labels on N sources.

### Changelog of measured results

**Still empty, and that is the point.** Every row here requires a human-labelled
golden set (`api/src/peritus/eval/golden/screening/`), and none has been built.
An entry produced by scoring the validator against model-generated labels would
measure it against itself and mean nothing, so none has been added.

To fill the first row: capture a build with `SCREENING_CAPTURE_DIR` set, label
40–60 of its sources by hand (over-representing the band around the threshold,
which is where the errors are), and run
`python -m peritus.eval.screening <golden.json>`.

| Date | Rubric | Model(s) | Golden set | Precision | Recall | Kappa | Note |
|---|---|---|---|---|---|---|---|
| | v4-tiered-q5r6 | haiku-4-5 | | | | | baseline — never measured before v5 shipped |
| | v5-structured-q5r6 | haiku-4-5 | | | | | structured preview, reviewer off |
| | v5-structured-q5r6 | haiku-4-5 + sonnet-5 | | | | | reviewer on; flip the default if kappa improves |

---

## Risks and what not to do

- **Do not budget by embedding similarity for dedup before ingestion.** Embeddings cost
  money and do not exist yet at that point. Simhash is free and sufficient.
- **Do not let the loop re-plan.** Round 0's brief (key concepts, must-have works) is the
  standard the corpus is held to; later rounds add queries, they do not move the goal.
  A loop that rewrites its own syllabus can always declare itself finished.
- **Do not send every source to Sonnet.** The borderline band is where the errors are;
  the tails are cheap and right. If the screening runner shows tail errors, widen the
  band, do not remove it.
- **Do not add Unpaywall.** OpenAlex already carries its data.
- **Watch the seen-set across rounds.** A candidate rejected by triage in round 0 must
  not be re-triaged in round 1 unless its identity gained new evidence (a co-citation);
  otherwise the loop spends its rounds re-considering the same tail.
- **Rebuilds wipe the corpus** (`reset_build_state` then a fresh round 0). Nothing in
  this plan changes that; the living-review follow-on is where a rebuild becomes a
  delta.
- **CLI parsing is strict.** Every new event type needs a serde variant and a captured
  fixture in `cli/src/api/types.rs` or the TUI breaks on the first new build.

## Follow-ons this plan enables but does not include

- **Ledger overrides.** Reinstate a dropped source (identity from phase 1 and the
  resolver from phase 2 make this a single-source ingest through the existing upload
  path) or exclude a kept one, with the human decision stored beside the model's. Each
  override is a labelled example for the phase 0 golden set.
- **Living review.** A rebuild that starts from the stored `build_summary`, re-runs
  the search strategy, and reports what is new since the last build instead of
  rebuilding from nothing.
- **Per-concept evidence table.** Coverage from phase 4 plus the reconciler's
  support / contradict / qualify edges gives the surface the graph page should become.
