# Audit API

The read-only surface over Peritus's evidence record: what a corpus is made of, what it
rejected, how each source was found, where the sources disagree, and which passages an
answer actually used.

All routes live under `/experts/{slug}` and require an authenticated user. An expert the
caller cannot read returns **404**, never 403 — existence is not disclosed. A published
(public) expert is auditable by anyone who can read it, by design: a public expert whose
evidence trail was private would be a claim without a receipt.

Responses are assembled in `peritus/audit/service.py` and returned as plain dicts. This
document is the contract; the service is the authority.

---

## Conventions that apply everywhere

### `null` means "not recorded", never zero

Every count the system does not actually persist is returned as `null` alongside a
human-readable reason, rather than as `0` or an estimate.

```json
{ "count": null, "unavailable_reason": "No retained build event log for this expert's most recent build. …" }
```

**Clients must render these as "not recorded" and never as a zero.** A fabricated zero in
an evidence record is worse than a gap.

Fields following this pattern: any stage in `screening-flow.stages`, plus paired
`*_unavailable_reason` fields (`excluded_by_reason`, `fetch_failures`, `query_text`,
`candidates_identified`, `key_concepts_unavailable_reason`).

### `method_statement`

Most responses carry a `method_statement` string describing how the record was produced.
Surface it near the data. It exists so a reader can judge the record's limits.

### Pagination

Paginated responses carry a `page` object:

```json
{ "limit": 100, "offset": 0, "returned": 42, "total_matching": 42, "has_more": false }
```

`total_matching` is computed over the whole corpus, not the page — totals and breakdowns
stay true under pagination.

| Endpoint | default | max |
|---|---|---|
| `corpus-report` (`sources`) | 100 | 500 |
| `contradictions` | 25 | 100 |
| `answer-audits` | 25 | 100 |

### Provenance completeness

Columns arrived over several migrations (`validator_model`/`rubric_version` in 009,
`covered_concepts`/`discovered_via` in 012, `source_tier` in 020, and identity plus
full-text and review provenance — `doi`, `arxiv_id`, `identifiers`, `full_text_method`,
`text_chars`, `review_model`, `first_pass_quality`, `first_pass_relevance`,
`snowball_seed_urls` — in 025). Older sources have nulls, and **nothing is backfilled**:
a build from before migration 025 genuinely did not record its sources' DOIs or how their
text was fetched, and a backfilled guess would put a fabrication into the provenance
record. `rubric_version` says which rubric produced a row. The corpus report's
`provenance` block reports exactly which fields are incomplete, so a partial record is
visible rather than silently thin.

---

## `GET /experts/{slug}/corpus-report`

Every source the corpus was built from **and** every source it rejected.

**Query:** `decision` = `all` | `accepted` | `rejected` (default `all`) ·
`sort` = `decision` | `quality` | `relevance` | `title` | `type` | `discovered_via` | `added`
(default `decision`) · `limit` · `offset`

The rejected half is a first-class filter, not a debug view: excluded sources are the
evidence that the included ones were selected.

```jsonc
{
  "expert": { "name": "…", "topic": "…", "tier": "standard", "…": "…" },
  "method_statement": "…",

  "totals": {
    "considered": 47, "accepted": 21, "rejected": 26,
    "acceptance_rate": 0.4468,
    "accepted_with_passages": 21, "accepted_without_passages": 0,
    "passages_total": 412
  },

  "scores": {
    "accepted": { "mean_quality": 7.4, "mean_relevance": 7.9, "…": "…" },
    "rejected": { "mean_quality": 3.9, "mean_relevance": 4.6 },
    "distribution": { "quality": { "accepted": [0,0,…], "rejected": [0,1,…] }, "relevance": { "…": "…" } },
    "bin_edges": [[0,1],[1,2], "…", [9,10]]
  },

  "thresholds": {
    "quality_min": 5, "relevance_min": 6,
    "current_rubric_version": "v5-structured-q5r6",
    "note": "These are the floors the CURRENT code applies. Rows stamped with a different rubric_version were judged under different rules…"
  },

  "rubric_versions": [
    { "rubric_version": "v5-structured-q5r6", "validator_model": "claude-haiku-4-5-20251001",
      "sources": 47, "accepted": 21, "first_seen": "…", "last_seen": "…" }
  ],

  "provenance": {
    "sources": 47,
    "complete": true,
    "missing": { "validator_model": 0, "rubric_version": 0, "discovered_via": 0, "covered_concepts": 0 },
    "note": "Every source carries full validation and discovery provenance."
  },

  "by_source_type": [
    { "source_type": "pdf", "considered": 9, "accepted": 5, "rejected": 4,
      "accepted_mean_quality": 7.8, "accepted_mean_relevance": 8.1 }
  ],

  "by_discovery_method": [
    { "method": "plan", "considered": 38, "accepted": 16, "rejected": 22, "accepted_mean_quality": 7.2 }
  ],

  "by_search": {
    "searches": [
      { "discovered_via": "gapfill:measurement error", "method": "gapfill", "concept": "measurement error",
        "considered": 4, "accepted": 1, "rejected": 3,
        "accepted_mean_quality": 6.5, "accepted_mean_relevance": 7.0,
        "source_types": ["web", "pdf"] }
    ],
    "distinct_searches": 5,
    "note": "One row per distinct search path recorded on the sources…"
  },

  "exclusions": {
    "by_reason": [ { "reason": "…", "count": 7, "mean_quality": 3.1, "mean_relevance": 4.0 } ],
    "by_threshold": {
      "quality_below_threshold": 9, "relevance_below_threshold": 6,
      "both_below_threshold": 11, "above_both_thresholds": 0, "unscored": 0
    },
    "by_threshold_meanings": { "…": "human-readable gloss per bucket" }
  },

  "page": { "decision": "all", "sort": "decision", "limit": 100, "offset": 0, "returned": 47, "total_matching": 47, "has_more": false },

  "sources": [
    {
      "id": 812, "decision": "rejected",
      "title": "…", "url": "https://…", "author": "…",
      "source_type": "web", "content_type": "commentary", "difficulty": 2,
      "quality_score": 3.0, "relevance_score": 4.5,
      "drop_reason": "Secondary commentary; no primary data.",
      "source_tier": "tertiary",
      "doi": "10.1234/example", "arxiv_id": null,
      "identifiers": { "doi": "10.1234/example", "pmid": "31234567" },
      "full_text_method": "abstract", "text_chars": 1840,
      "validator_model": "claude-sonnet-5",
      "review_model": "claude-sonnet-5",
      "first_pass_quality": 5.5, "first_pass_relevance": 5.5,
      "reviewed": true,
      "rubric_version": "v5-structured-q5r6",
      "discovered_via": "gapfill:measurement error",
      "discovery_method": "gapfill",
      "gap_filled_for_concept": "measurement error",
      "snowball_seed_urls": [],
      "covered_concepts": [], "key_claims": [],
      "passage_count": 0,
      "created_at": "…"
    }
  ]
}
```

**`drop_reason` is `null` on accepted rows.** `discovery_method` and
`gap_filled_for_concept` are parsed from `discovered_via` for convenience — prefer them
over string-splitting client-side. Only `gapfill` carries a concept in its suffix;
`snowball:backward` and `snowball:forward` carry a citation direction, and
`gap_filled_for_concept` is `null` for both.

**`validator_model` is whose verdict stands, not who looked first.** When `reviewed` is
true, a borderline first-pass score was re-examined by a stronger model reading far more
of the source, and `first_pass_quality` / `first_pass_relevance` are what that changed.
A reviewed row is not a less reliable row — it is the one place in the ledger where a
decision was made twice.

**`full_text_method` says how much of the source was actually read**, which is the first
question a reviewer asks about a corpus and which nothing recorded before migration 025:
`ar5iv` · `europepmc_jats` · `oa_pdf_ocr` · `arxiv_pdf_ocr` · `oa_landing_html` ·
`abstract`. A source with `"full_text_method": "abstract"` was judged, and is answering
questions, on its abstract alone.

**Duplicates appear as rejections with a stated reason.** A source dropped by content
fingerprinting has `drop_reason` of the form `duplicate of <url>` and scores of 0 — it was
never judged on merit, and reading its zeros as a quality verdict would be wrong.

### `by_search` is the differentiating view

Group the ledger by `discovered_via` as a **primary** view, not a filter. Tools that begin
from a bibliographic export cannot have this field at all: every record arrived the same
way. A `gapfill:<concept>` row is a search that exists *only because* that concept had no
accepted source.

---

## `GET /experts/{slug}/corpus-report/export`

Downloads the ledger. **Query:** `format` = `csv` | `ris` (default `csv`) ·
`decision` = `all` | `accepted` | `rejected`

Returns a file with `Content-Disposition: attachment` and `X-Peritus-Export-Rows`.
Both formats include rejected sources with exclusion reason and originating search.

`ris` is the operationally important one: it is what Covidence, Zotero and EndNote import,
so it is how a grey-literature source Peritus found reaches the review the user is running.

**`507` if the corpus exceeds the 20,000-row export guard.** Exports are never partial — a
truncated ledger would misrepresent the search, so no file is produced. Render the message
and point the user at paginated `corpus-report`.

---

## `GET /experts/{slug}/screening-flow`

Counts through the funnel: identified → screened → retrieved → assessed → included.

Two sources of truth, deliberately **not** reconciled. Pre-validation stages come only from
the build event log, which may be absent. Validation onward comes from the `sources` table,
which is the corpus itself and is authoritative. Where they disagree, both are shown.

```jsonc
{
  "expert": { "…": "…" },
  "method_statement": "…",

  "build": {
    "job_id": 41, "status": "succeeded", "tier": "standard",
    "attempts": 1, "max_attempts": 3, "last_error": null,
    "started_at": "…", "finished_at": "…",
    "event_log_retained": true,
    "note": "This is the most recent build job, successful or not…"
  },

  "search_strategy": {
    "fetchers": [ { "fetcher": "pubmed", "queries_run": 2, "candidates_identified": 11, "skipped": false, "skip_reason": null } ],
    "fetchers_available": ["wikipedia", "…", "pubmed"],
    "fetchers_run": ["web", "pdf", "pubmed"],
    "queries_issued": 17,
    "query_text": null,
    "query_text_unavailable_reason": "The per-fetcher search queries are generated by the planning stage at the start of each build and are not persisted…",
    "searches_recorded_on_sources": 5,
    "note": "Peritus searches open sources — web pages, PDFs with OCR, video transcripts, books, preprints, practitioner discussion — rather than importing a bibliographic database export…"
  },

  "stages": {
    "identified": {
      "count": 143, "source": "build event log",
      "by_fetcher": [ { "fetcher": "web", "candidates": 24, "queries_run": 3, "skipped": false, "skip_reason": null } ],
      "fetchers_available": ["…"], "fetchers_run": ["…"],
      "duplicates_removed_before_triage": 12,
      "note": "Candidates are search hits (title + snippet), before any content is downloaded…",
      "unattributable": "…"
    },
    "screened_at_triage": {
      "count": 131, "source": "build event log",
      "passed": 60, "excluded": 71,
      "excluded_by_reason": null,
      "excluded_by_reason_unavailable_reason": "…",
      "note": "Triage scores every pooled candidate on title and snippet alone…"
    },
    "retrieved_full_text": {
      "count": 47, "source": "build event log",
      "fetch_budget": 30, "ranked_not_fetched": 13, "snowballed_added": 4,
      "fetch_failures": null,
      "fetch_failures_unavailable_reason": "…",
      "note": "…ranked_not_fetched is dominated by candidates the budget never reached — it is NOT an exclusion for cause…",
      "stage_timings": { "…": "…" }
    },
    "assessed_at_validation": {
      "count": 47, "source": "sources table",
      "note": "Every source the validator scored, including any added by the gap-fill round. Authoritative…",
      "reported_by_build_log": 43,
      "build_log_note": "The build log's validate_done event covers the first validation round only; gap-fill sources are validated separately…"
    }
  },

  "discovery": {
    "rounds_run": 2,
    "stop_reason": "targets_met",
    "stop_reason_meaning": "Every key concept reached this tier's coverage target…",
    "rubric_version": "v5-structured-q5r6",
    "budget": {
      "discovery_budget_usd": 3.0,
      "metered_spend_at_stop_usd": 1.42,
      "estimated_ingest_usd": 0.91,
      "note": "The discovery budget is a soft target the search spends towards, not the build's hard spend cap…"
    },
    "coverage_targets": { "min_sources": 2, "min_source_types": 2, "require_non_tertiary": true, "max_rounds": 2 },
    "coverage_met": true,
    "final_coverage": [
      { "concept": "…", "sources": 3, "source_types": ["openalex", "web"], "tiers": ["primary", "secondary"], "met": true, "shortfall": 0 }
    ],
    "duplicates_removed": {
      "by_identifier": 6, "by_url": 11, "already_seen_in_an_earlier_round": 9,
      "by_content_fingerprint": 2,
      "note": "…by identifier is certain; by content fingerprint is the only one of the three that can be wrong…"
    },
    "rounds": [
      {
        "round": 0, "targeted_concepts": [], "queries": [],
        "candidates_identified": 143, "screened_at_triage": 131, "passed_triage": 60,
        "retrieved_full_text": 28, "snowballed_candidates": null,
        "accepted": 21, "rejected": 7, "acceptance_rate": 0.75
      },
      {
        "round": 1,
        "targeted_concepts": ["measurement error"],
        "queries": ["differential misclassification cardiometabolic cohort", "…"],
        "candidates_identified": 40, "screened_at_triage": 26, "passed_triage": 14,
        "retrieved_full_text": 9, "snowballed_candidates": 6,
        "accepted": 6, "rejected": 3, "acceptance_rate": 0.667
      }
    ],
    "note": "Round 0 searches the research plan's own queries. Every later round reads the corpus that exists…"
  }
}
```

### `discovery` is where a corpus argues for its own sufficiency

`stop_reason` is the field to read. "This corpus has 34 sources" is not a claim anyone can
check; "the search met its coverage targets after two rounds" and "it stopped at the
discovery budget with two concepts still short" both are. Only `targets_met` means the
search finished rather than ran out — the other five say what it ran out of.

`rounds[].queries` is the search strategy of every round after the first, written down
verbatim. Those queries are generated by reading the accepted corpus, not by the plan, so
they are the only record of *why* the later searches looked where they did.

Two sources of truth, deliberately not reconciled: `rounds` comes from the build event
log, which can be pruned; the top-level fields fall back to `experts.build_summary`, which
the build writes and which survives. Where both exist they should agree, and showing both
is what makes a disagreement visible. A build that predates the discovery loop returns
`"rounds_run": null` with an `unavailable_reason` and reports its single gap-fill round
under `gap_fill` as before.

**`ranked_not_fetched` is not an exclusion for cause.** Do not present it as one — it is
mostly budget exhaustion and cannot be separated from per-type caps or failed downloads.

---

## `GET /experts/{slug}/coverage`

Evidence strength per planned key concept — where the corpus is weak.

```jsonc
{
  "expert": { "…": "…" },
  "method_statement": "…",
  "key_concepts_planned": ["…"],
  "key_concepts_unavailable_reason": null,
  "classification_rule": "…",
  "summary": {
    "concepts": 7, "absent": 1, "thin": 2, "adequate": 3, "strong": 1,
    "concepts_needing_gap_fill": 2, "off_plan_concepts": 0
  },
  "tagging": {
    "accepted_tagged_with_concepts": 19,
    "accepted_tagged_no_concepts": 2,
    "accepted_untagged_legacy": 0,
    "note": "untagged_legacy sources predate concept tagging (migration 012) and are invisible to every per-concept count below…"
  },
  "concepts": [
    {
      "concept": "measurement error",
      "strength": "thin",
      "needed_gap_fill": true,
      "on_plan": true,
      "…": "source counts, mean quality, contributing sources, gap-fill round"
    }
  ]
}
```

`strength` ∈ `absent` | `thin` | `adequate` | `strong`. Concepts with `"on_plan": false`
were tagged by the validator but are not on the plan — a stale-plan signal worth showing,
not hiding.

**Render the gap-fill narrative**: concept was uncovered → this search ran → these sources
came back (including the rejected ones; a re-search that returned four and kept none is a
stronger statement about the evidence base than one that found nothing).

---

## `GET /experts/{slug}/contradictions`

Where sources in this corpus were judged to disagree, resolved down to passages.

**Query:** `limit` · `offset` · `passages_per_side` · `excerpt_chars`

### Check `computed` before reading `contradictions`

```jsonc
{ "computed": false, "readiness": "chat_ready", "contradictions": [], "…": "…" }
```

Contradictions come from the reconciliation pass over the concept graph, which runs a full
stage **after** the corpus becomes searchable. An expert can be answering questions while
its graph is still empty.

**`computed: false` with an empty list means "not analysed yet" — never render it as "no
contradictions found".** For a product whose claim is that it shows where sources disagree,
reporting an unanalysed corpus as a clean one is the worst failure available.

When `computed: true`:

```jsonc
{
  "expert": { "…": "…" },
  "method_statement": "…",
  "computed": true,
  "readiness": "graph_ready",
  "summary": {
    "contradictions": 6, "claims_involved": 9,
    "relationships_total": 214, "share_of_relationships": 0.028,
    "cross_source_on_page": 4, "within_source_on_page": 1, "undetermined_on_page": 1
  },
  "relationship_mix": [ { "edge_type": "contradicts", "count": 6, "mean_evidence": 2.1 } ],
  "note": "A contradiction is a judgement a language model made between two claims the corpus makes, with the claims from every source in front of it, and `point` is what it says is in dispute…",
  "page": { "…": "…", "passages_per_side": 2, "excerpt_chars": 600 },
  "contradictions": [
    {
      "kind": "cross_source",
      "point": "whether Varroa alone causes collapse without viral co-infection",
      "evidence": 3,
      "…": "the claim on each side; per-side passages with source citations"
    }
  ]
}
```

Both ends of a contradiction are **claims**, always. Two concepts can differ; only two
propositions can be incompatible, and an edge with a concept on either end is rejected at
ingest (migration 024 removed the ones already stored). `point` is one sentence saying what
is disputed, in the subject's terms — null only on edges extracted before it was required.
`evidence` counts the distinct sources behind the two sides' passages; it is not a
confidence, and nothing in this response is.

`kind` ∈ `cross_source` | `within_source` | `undetermined`. Only `cross_source` is two
sources disagreeing; `within_source` is one source in tension with itself. Label them
differently.

**Wording:** say *"sources in this corpus were judged to disagree"*. Never *"detects
contradictions in the literature"* — the corpus is ~40 sources, not the literature.

---

## `GET /experts/{slug}/answer-audits`

Retrieval trails for answers this expert has given — the durable half of the
`retrieval_audit` SSE event, so an answer stays accountable after its stream closes.

**Query:** `conversation_id` (optional) · `limit` · `offset`

```jsonc
{
  "expert": { "…": "…" },
  "disposition_meanings": { "cited": "…", "considered": "…" },
  "page": { "…": "…" },
  "audits": [ { "id": "…", "question": "…", "passages_considered": 23, "passages_cited": 6, "…": "…" } ]
}
```

## `GET /experts/{slug}/answer-audits/{audit_id}`

One answer's full trail, with per-passage disposition. `404` on unknown or malformed id.

```jsonc
{
  "expert": { "…": "…" },
  "disposition_meanings": { "…": "…" },
  "…": "audit header fields, inlined",
  "passages": [
    {
      "n": 4, "chunk_id": 9912, "source_id": 812,
      "source_title": "…", "source_type": "pdf",
      "quality_score": 7.5,
      "retrieval_rank": 2, "retrieval_score": 0.8134,
      "retrieved_via": "semantic",
      "disposition": "cited"
    }
  ]
}
```

**This is an audit trail, not a quality score.** Render it as "grounded in 6 of 23 retrieved
passages" — a count with a link to the passages. **Do not display a grounding or
faithfulness percentage.** `chat/faithfulness.py` is offline-eval only and its live display
was deliberately removed; do not reintroduce it.

---

## Claims this API does not support

Enforced by omission — the data to back these does not exist:

- **PRISMA compliance.** The ledger produces data PRISMA asks you to *report*. Compliance is
  a property of a review, not a tool.
- **Substituting for dual human review.** Single-model screening, no second reviewer.
- **Any sensitivity / specificity / recall / precision figure.** There is no calibration set.
  A number here would be fabricated.
- **Exact search queries.** `query_text` is permanently `null` — the planning stage generates
  queries per run and never persists them. Report counts, never reconstruct strings.
- **"Systematic review software."** ~40 sources per build, no dual review, no conflict
  resolution, no extraction.
