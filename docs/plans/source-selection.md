# Source selection: why builds miss the best sources, and what to change

**Date:** 2026-09-15
**Method:** one STANDARD build traced end to end from its persisted events and
`sources` rows (Thomism, expert 55, job 53, built today), the same rows for the
four builds before it (experts 40–43), one live re-run of triage on the
candidates that build fetched, one probe of Gutendex, and the code as it is on
the `web` branch. Where a claim rests on a single build it says so. Nothing in
this document was measured against a golden set, because none exists — that is
finding S7, and building one is phase 0.

**The brief:** a build should end up with the *best* sources for its topic, and
today it ends up with *acceptable* ones. The short answer to why is that the
pipeline is a chain of admission filters ("is this worth fetching?", "is this
acceptable?") followed by a breadth floor ("does every concept have two
sources?"). No stage ranks the corpus as a whole against the syllabus, the
channels that carry primary texts fail silently, the one scoring stage that
decides what gets fetched fails *open*, and none of it is recorded in a form
that can be audited or measured afterwards.

This plan follows [corpus-quality.md](corpus-quality.md), which built the
loop, the identity layer, the full-text chain and the cost budget. Everything
here sits on top of that work and none of its calibrated constants move (see
§12).

---

## 1. Summary

| # | Finding | Measured (job 53 unless noted) | Fix | Phase |
|---|---------|----------|-----|-------|
| S1 | The channels that carry primary texts fail silently | gutenberg **0** candidates (Gutendex timed out; my own probe timed out at 25 s), pdf **0** (Semantic Scholar, almost certainly 429). Both reported as `skipped: false, reason: ""`. Later rounds never retry gutenberg | Fetcher search returns an *outcome*, transient failures retry, Gutenberg stops depending on Gutendex | 1 |
| S2 | Triage fails open above real candidates | Live re-run scores the junk that was fetched at **0.0–2.0**, all under the 3.0 floor. It was fetched anyway: its batch failed or misaligned and took `_FALLBACK_SCORE = 5.0`, which outranks every honestly scored 3 and 4. One of them, a 101,901-char visual-analytics paper, went to paid OCR | Parse by candidate id, fail closed, re-ask in halves, persist every score | 2 |
| S3 | Fetch fills a count, not a quality bar | 108 ranked, budget 60, **59 fetched**: the queue walks down the tail once the good types cap out. No score floor at fetch time | A fetch-time score floor; the count becomes a ceiling | 2 |
| S4 | Must-have works are satisfied by fragments, and the plan is not recorded | "Summa Theologiae" matched **one question of ~600** (I-II q.94), found twice. `plan_ready` carries only `key_concepts`; queries, weights and must-haves exist only in a log line | A canonical-work resolver with whole/partial/not-found outcomes; persist the plan | 3, 0 |
| S5 | Validation is a floor, tier is inert, abstract stubs pass | **12 of 43** kept sources are abstract-only catalogue records under 5,000 chars (a Library of Congress table of contents, CiNii, Choice reviews) passed at q8/r9. StudyGuides.com passed at q6/r9 as tertiary | Substance floor for coverage credit; tertiary share cap; catalogue records penalised at triage | 4 |
| S6 | The loop stops before it can improve anything | STANDARD's target (2 sources, 2 types, 1 non-tertiary per concept) was met after round 0: `rounds: 1, stop_reason: targets_met`. Feedback queries and snowballing never ran. 24 of 43 sources cover natural law; metaphysics has **0 primary**. Round 0 also committed $2.30 of the $3.00 discovery budget | Depth targets (primary per concept), a guaranteed feedback round on STANDARD+, a money reserve for it | 5 |
| S7 | Selection is unobservable | No triage score is stored anywhere; no plan; no fetcher error; no golden set for triage or screening | Migration 029: plan on the expert, a screening ledger per candidate, fetcher outcomes in events; golden sets and a triage harness | 0 |
| S8 | Search asks generic questions of noisy channels | Reddit's base quota (5) equals Exa's; Exa is not told to exclude the hosts triage will penalise; OpenAlex returns catalogue records because they have abstracts | Exa domain lists and categories, OpenAlex prefers works with a route to text, reddit quota 2 | 6 |

What the Thomism corpus looks like today, and what "fixed" means for it:

| | today | target after this plan |
|---|---|---|
| sources kept | 43 | 30–45 |
| primary | 3 (7%) | ≥ 25% |
| tertiary | 10 (23%) | ≤ 25% |
| abstract-only stubs counted as secondary | 12 (28%) | ≤ 15%, and none counted toward coverage |
| fetched with validator relevance ≤ 3 | 11 | 0–1 |
| must-have works found whole | 0 | ≥ 2 of 3 (Summa Theologiae, Summa Contra Gentiles, De Ente et Essentia) |
| concepts with no primary source | ≥ 1 (metaphysics) | 0 |

The same junk-fetched signature appears in the four builds before this one
(expert 42: 7 of 33 fetched had relevance ≤ 3; 40, 41, 43: 1–2 each), so S2
and S3 are not a one-off.

---

## 2. What runs today, with the numbers from job 53

```
plan        Sonnet, one call → 8 key concepts, per-fetcher queries and weights,
            must-have works                                (only key_concepts recorded)
search      9 active fetchers × ≤3 queries, ≥10 results per query
              wikipedia 28  reddit 20  exa 29  web 30  youtube 19
              openalex 29   thought_leaders 8  pdf 0  gutenberg 0      → 163 candidates
dedup       identity + URL                                             → 160
triage      Haiku, batches of 20, title + URL + snippet, positional parse,
            + domain prior, must-have substring match → ≥ 3.0 kept    → 108 ranked
fetch       by (priority, −round(score), cost) until 60 or list ends,
            per-type caps                                              → 59 fetched
validate    Haiku, batches of 5, q ≥ 5 and r ≥ 6 to pass               → 43 pass, 16 drop
coverage    every concept has ≥2 sources, ≥2 types, ≥1 non-tertiary   → met
stop        targets_met after round 0; $0.20 spent + $2.10 committed of $3.00
```

Ingesting what passed cost **$0.27 per 100,000 characters** (1.23 M chars,
$3.27 of contextualisation and graph extraction on the batched path). That
figure prices every trade-off below: a 100 k-char catalogue stub costs nothing
because it has no text, and a whole Gutenberg volume at 200 k chars costs
about $0.54.

---

## 3. Findings

### S1. The primary-text channels fail silently

`GutenbergFetcher.search` asks Haiku to name public-domain books for the
*query* (three calls per build, one per planner query, none of them seeing the
plan's must-have list), then looks each up on Gutendex under a single 45 s
budget and returns an empty list on timeout. Gutendex is one volunteer-run
service; it timed out for the build and it timed out for my probe. The result
reaches the build as `fetcher_done {count: 0, skipped: false, reason: ""}`,
indistinguishable from "there are no public-domain books on this topic".

`PdfFetcher.search` calls Semantic Scholar's search endpoint unauthenticated.
The shared unauthenticated pool is rate-limited hard; the fetcher retries 429
three times with the retry logged at **DEBUG**, then returns nothing. Same
empty event.

Neither channel is retried: `_LOOP_FETCHERS` is `exa, web, wikipedia, arxiv,
pdf, pubmed, openalex`, so a Gutenberg timeout in round 0 means no classic
primary text for that build, ever, and on the humanities topics this product
is most obviously for, Gutenberg *is* the primary-text channel.

### S2. Triage fails open, and above the candidates it scored honestly

`triage_candidates` runs batches of 20 and parses the tool result by
position. Two things go wrong on a bad response. If the batch fails outright
or is unparseable, every candidate in it gets `_FALLBACK_SCORE = 5.0`. If the
model returns 17 entries for 20 candidates, the last three get 5.0 and, worse,
if it *skipped one in the middle*, every score after it belongs to the wrong
candidate.

The fetch queue then sorts by `−round(score)`. A fallback 5 sits above every
genuine 3 and 4 and ties with every genuine 5. That is how the Thomism build
fetched, validated and paid for:

| candidate | live triage score today | validator relevance |
|---|---|---|
| Tracie Thoms (an actress) | 0.0 | 0.0 |
| Thom (a disambiguation page) | 0.0 | 0.0 |
| St. Thomas Aquinas College | 1.0 | 0.5 |
| Visual Analytics: A Comprehensive Overview (OCR'd, 101,901 chars) | 1.5, of which +1.5 is the `doi.org` prior | 0.0 |
| Thomism — StudyGuides.com | 2.0 | 9.0 (passed, tertiary) |
| Library of Congress table of contents | 4.5, of which +1.5 is the `.gov` prior | 9.0 (passed, "secondary", 1,484 chars) |

The first four are below the 3.0 floor when scored, so they cannot have been
fetched on a score the model gave them. The eight Wikipedia candidates fetched
look like the first eight results of a Wikipedia search in search order, which
is exactly what a whole batch at a tied 5.0 produces. The last two rows are a
different problem (S5): the model scores a catalogue page as a weak candidate
and the domain prior promotes it for being on a government site.

None of this is visible after the build. Triage scores are not persisted, the
batch failure is a warning on the worker's stdout, and the `sources` row shows
only the validator's verdict on text that should never have been fetched.

### S3. Fetch fills a count

`_fetch_with_refill` loops `while len(results) < budget and idx < len(ordered)`.
Per-type caps are enforced by *skipping* a capped candidate and moving on, so
once exa and openalex have taken their share the walk continues down the
ranked list through low-scored wikipedia and web candidates until 60 is
reached. The count was raised to 60 so that money would be the binding limit;
with triage's 3.0 floor as the only quality gate, it is the tail of the ranked
list that fills the last third of the corpus.

### S4. Must-have works are satisfied by fragments

`_matches_must_have` is a substring or a 0.7 fuzzy ratio on the title. A New
Advent page titled "SUMMA THEOLOGIAE: The natural law (Prima Secundae Partis,
Q. 94)" matches "Summa Theologiae", gets score 9 and `fetch_priority`, and the
work is considered found. The CCEL copy of the same question was fetched too
and dropped as a content duplicate. The corpus contains one question of the
Summa and nothing else by Aquinas except a single Contra Gentiles chapter.

The plan that named the must-haves is gone. `plan_ready` emits
`key_concepts` only; the queries, the weights and the must-have list are one
INFO line in a log file that, for a background build, lives on the worker.

### S5. Validation is a floor, and lenient where it matters

A source passes at `quality ≥ 5 and relevance ≥ 6`. `source_tier` is
recorded and only read by coverage's `require_non_tertiary`. Nothing after
validation prefers a primary text to a study guide when both pass, and the
rubric tells the model an abstract-only record "can still pass if the abstract
substantively states the finding". OpenAlex supplies plenty of these — book
records whose "abstract" is the publisher's blurb and whose landing page is a
library catalogue — and they pass as *secondary* at q8/r9 with 300–4,500
characters of text. Twelve of the 43 kept Thomism sources are of this kind.
They occupy secondary slots, count toward coverage, and contribute a chunk or
two of catalogue prose to retrieval.

### S6. The loop stops at a breadth floor, and could not afford to continue anyway

STANDARD's `CoverageTarget` is 2 sources, 2 source types and 1 non-tertiary
per concept. A 43-source corpus meets that for every concept whether or not
the corpus is any good, so the loop stopped after round 0 with `targets_met`.
The feedback round — the only stage that searches in the field's own
vocabulary and follows citations — did not run. Two of the three
distribution problems in the corpus (natural law over-represented, metaphysics
with no primary) are not expressible in the target at all.

Separately: round 0 fetched to its count ceiling and committed $2.10 of the
$3.00 discovery budget, with $0.20 already spent. Even with a stricter target,
round 1 would have had about $0.70, roughly fifteen sources' worth. The loop is
structurally a one-shot on STANDARD.

### S7. Selection cannot be audited or measured

What the build stores about selection: validator scores and tier, per source.
What it does not store: the plan; each candidate's triage score, prior and
fetch rank; which candidates were ranked but not fetched and why; whether a
fetcher failed or found nothing. There is no triage golden set and no
screening golden set, so no change to any of the above can be shown to be an
improvement rather than a difference.

### S8. Search is generic where it could be specific

Smaller things, in the same direction. Reddit's base quota is 5, the same as
Exa's; the planner usually zeroes it for scholarly topics but the default says
forum threads are as valuable as curated web results. Exa is never told to
exclude the hosts triage will penalise, so the penalised results are paid for
in triage tokens before they are thrown away. OpenAlex is asked for works with
an abstract and gets catalogue records back because they have one.
Wikipedia's search returns "Tracie Thoms" for a Thomism query, which is
Wikipedia's problem, but with S2 fixed it is harmless.

---

## 4. Phase 0. Make selection visible

Every later phase changes what gets kept. Without this phase none of them can
be shown to help. Small, additive, and first.

### 0.A Persist the plan

- `_emit_event(plan_ready)` carries the whole normalised plan:
  `key_concepts`, `fetcher_plans` (queries and weight per fetcher),
  `must_have_works`. Web (`types.ts` `PlanReadyEvent`) and CLI
  (`PlanReady { key_concepts }`) ignore unknown fields, so this is additive;
  the web build log can show the queries under the concepts.
- Migration 029 adds `experts.research_plan JSONB`, written when the plan is
  ready and read by the audit surface. A rebuild overwrites it.

### 0.B A screening ledger per candidate

A row for every candidate triage saw, not only the sources that were fetched:

```sql
CREATE TABLE candidate_screenings (
    id                BIGSERIAL PRIMARY KEY,
    job_id            BIGINT NOT NULL REFERENCES build_jobs(id) ON DELETE CASCADE,
    expert_id         BIGINT NOT NULL,
    round             SMALLINT NOT NULL,
    source_type       TEXT NOT NULL,
    url               TEXT NOT NULL,
    title             TEXT NOT NULL,
    discovered_via    TEXT NOT NULL,          -- plan | snowball:* | feedback:<concept> | canonical
    model_score       REAL,                   -- NULL when the model never scored it
    domain_adjustment REAL NOT NULL DEFAULT 0,
    triage_score      REAL NOT NULL,          -- what the fetch queue sorted on
    triage_status     TEXT NOT NULL,          -- scored | unscored | reasked | must_have | priority
    fetch_rank        INTEGER,                -- position in the round's fetch order, NULL if under the floor
    fetch_outcome     TEXT,                   -- fetched | failed | capped | below_floor | budget | not_reached
    source_id         BIGINT REFERENCES sources(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON candidate_screenings (job_id, round);
```

Written once per round after the fetch stage, in one transaction, by the
builder through `ExpertRepository`. `sources.triage_score` is also added so the
usual source queries can join nothing and still see it.

### 0.C Fetcher outcomes in the event

`_safe_search` returns a `SearchOutcome(candidates, status, error, elapsed)`
with `status ∈ {ok, empty, timeout, rate_limited, error, skipped}`.
`fetcher_done` gains `status` and `error`; `skipped`/`reason` stay for the
clients. The build log then says "gutenberg: timeout after 45 s (Gutendex)"
instead of "gutenberg: 0". Every fetcher's own `except` that currently logs and
returns `[]` maps to a status instead: Gutendex timeout → `timeout`, Semantic
Scholar 429 after retries → `rate_limited`, everything else → `error`. The
Semantic Scholar retry log line moves from DEBUG to WARNING.

### 0.D Corpus composition in `build_summary`

Computed once at the end of discovery and stored under
`build_summary.corpus`, then shown in the web corpus report:

```
primary_share, secondary_share, tertiary_share, abstract_only_share,
junk_fetched (fetched sources with validator relevance ≤ 3),
concept_shares (share of the corpus each concept's sources make up),
concepts_without_primary, must_have: [{title, status, source_id}]
```

These are the numbers §8 uses as done-when checks, and the ones a user of the
corpus report should see first.

### 0.E Golden sets and a triage harness

- **Triage labels are cheap.** A candidate is a title, a URL and a snippet;
  labelling 150 of them takes an hour. `eval/golden/triage/<topic>.json`
  holds `{url, keep: bool, why}` for the candidates of one job, sampled from
  `candidate_screenings` with the band around the floor over-represented.
  `python -m peritus.eval.triage <job_id> <golden>` re-scores the candidates
  and reports precision and recall of "fetched" against "keep", Spearman
  between the triage score and the label, and the same split by source type
  and discovery route that `eval/screening.py` already reports.
- **Screening labels** follow `eval/golden/screening/README.md` as written.
  Capture is already there (`SCREENING_CAPTURE_DIR`); the labels are the
  missing piece, and they also unblock `VALIDATE_SECOND_OPINION`.
- Three topics, the shapes the README names: biomedical, humanities (Thomism,
  since it is the measured case), practitioner craft.

**Done when:** a rebuilt Thomism can be queried for every candidate triage saw,
its score, whether it was fetched and why not; the plan is on the expert; the
build log names why a channel returned nothing; a triage golden set exists for
Thomism and the harness reports a number for the current code.

---

## 5. Phase 1. Channels that fail loudly and get retried

### 1.A Transient failures retry within round 0

After the `asyncio.gather` over fetchers, any fetcher whose outcome is
`timeout` or `rate_limited` is retried **once**, sequentially, with the
remaining stage time. Cost: a few seconds on a stage that already waits on the
slowest fetcher. Gutendex timing out twice is then a status the loop can act
on, not a coincidence.

### 1.B Later rounds retry the channels that failed

`_LOOP_FETCHERS` becomes a base set plus every fetcher whose last outcome was
not `ok`/`empty`. The comment that keeps gutenberg out of later rounds is right
about *queries* — a concept query is not what Gutenberg answers — so the
Gutenberg retry re-runs the canonical-work resolution of phase 3, not the
feedback queries.

### 1.C Gutenberg without Gutendex on the happy path

Project Gutenberg publishes its whole catalogue as one CSV
(`gutenberg.org/cache/epub/feeds/pg_catalog.csv`: id, title, authors, language,
subjects) and serves plain text at a predictable URL
(`gutenberg.org/cache/epub/{id}/pg{id}.txt`). So:

- A `GutenbergCatalogue` in `infrastructure/gutenberg_catalogue.py` downloads
  the CSV to `GUTENBERG_CATALOGUE_DIR` when absent or older than 7 days,
  loads English titles into memory (about 75 k rows), and resolves a
  `(title, author)` pair to ids locally with the existing `_title_matches`.
  One download per worker per week; no per-build network call to identify a
  book.
- `fetch` downloads from the predictable URL, falling back to the Gutendex
  `formats` map only if that 404s.
- Gutendex remains as the fallback *search* for a title the catalogue does not
  match, under a 10 s per-call timeout instead of a 45 s bucket, and a timeout
  returns the books resolved so far rather than nothing.
- Book identification runs **once per build from the plan** — the planner's
  must-have works plus a new `primary_texts` list (§7.A) — instead of one
  Haiku call per planner query with no sight of the plan. `search(query)` keeps
  working for the source filter path by identifying from the query as today.

### 1.D Semantic Scholar with a key

`S2_API_KEY` (free, from Semantic Scholar) sent as `x-api-key` on every
Semantic Scholar call — the pdf fetcher and `sources/snowball.py` both use
the API and both hit the same unauthenticated pool. Without a key the fetcher
stays as it is but reports `rate_limited` honestly.

**Done when:** a build on a humanities topic with Gutendex unreachable still
produces Gutenberg candidates for the works the plan named; every empty
channel in a build log carries a status; a 429 is a WARNING with the fetcher's
name in it.

---

## 6. Phase 2. Triage that fails closed and fetches to a floor

### 2.A Score by id, not by position

Each candidate block already carries `candidate_{i}`. The tool schema becomes
`{id: string, expected_value: number}` with `id` required, and
`_parse_triage_response` maps scores by id. A candidate with no score is
`unscored`, not 5.0.

### 2.B Re-ask before giving up, then fail closed

A failed or partially scored batch is re-asked live in halves (10, then 5) for
the unscored candidates only. Anything still unscored after that gets
`triage_score = 0.0`, `triage_status = unscored`, and is never fetched unless
it is a must-have or a snowball priority (which do not depend on the score).
`_FALLBACK_SCORE` is deleted. An outage now costs candidates, never a corpus
full of junk; the loop's next round sees the concept still weak and searches
again.

### 2.C A fetch-time floor

`_fetch_with_refill` stops at the first candidate below `FETCH_SCORE_FLOOR`
(setting, default **6.0**) unless it is priority-ranked. The count budget
stays as the ceiling. If fewer than `max(8, budget // 4)` candidates reach the
floor in round 0, the floor relaxes to 5.0 for that round and a
`floor_relaxed` event says so; it never relaxes in later rounds. Candidates
under the floor are recorded in the ledger as `below_floor` so the trade-off
is visible per build.

This is the change that makes the corpus smaller and better rather than
larger and mixed, and the number is a guess until phase 0's harness measures
where honest scores separate keep from drop. The relaxation rule is what keeps
a thin topic from producing an empty round.

### 2.D Priors for what the model mis-scores

Additions to `_HOST_ADJUSTMENTS` and `_PATH_ADJUSTMENTS`, each one a case from
the measured build:

| rule | delta | why |
|---|---|---|
| path `/catdir/toc/` | −4.0 | Library of Congress tables of contents; today they get `.gov` +1.5 |
| host `ci.nii.ac.jp`, `bvbr.bib-bvb.de`, `catalog.loc.gov`, `worldcat.org` | −4.0 | library catalogue records |
| DOI prefix `10.5860/choice` (path rule on `doi.org`) | −3.0 | Choice book reviews, one paragraph, currently +1.5 as a DOI |
| host `studyguides.com`, `philosophystudent.org`, `handwiki.org` | −3.0 | the overview mills that passed |
| path `/wiki/` on hosts other than `wikipedia.org`/`wikisource.org` | −1.0 | wiki mirrors |

And one line in `_SYSTEM`: institutional pages, biographies of people,
disambiguation pages, catalogue records and tables of contents score 0–1
however well the title matches. A path rule fires *before* the host/TLD
boost, so a catalogue page on `.gov` nets −2.5, not +1.5.

**Done when:** `test_triage.py` covers id mapping, a skipped entry, a failed
batch (no candidate scored 5.0 by default), the floor and its relaxation; on
the triage golden set, precision of "fetched" against "keep" is reported and
no labelled-drop candidate with an honest score under 3 is fetched.

---

## 7. Phase 3. Canonical works, found whole

### 7.A The planner names texts, not just titles

`must_have_works[]` gains `kind` (`text | book | paper | standard`),
`public_domain` (bool) and `sections` (free text: "Prima Pars qq. 2–11 and
75–89; Prima Secundae qq. 90–108"). A new `primary_texts` list is not needed:
a must-have with `public_domain: true` *is* the Gutenberg identification, and
`_route_must_have_works` routes by kind instead of sending everything to Exa
as an exact-title query.

### 7.B A resolver, in `sources/canonical.py`

For each must-have, in order, stopping at the first whole-work hit:

1. Gutenberg catalogue (1.C), for `public_domain` works.
2. Internet Archive: `archive.org/advancedsearch.php` on title and creator
   with `mediatype:texts`, full text from `download/{id}/{id}_djvu.txt`.
   Covers public-domain works Gutenberg lacks and many out-of-copyright
   scholarly editions.
3. Exa exact-title search with `include_domains` set to the primary-text hosts
   the triage prior already trusts (`gutenberg.org, archive.org, ccel.org,
   newadvent.org, perseus.tufts.edu, sacred-texts.com, marxists.org,
   oll.libertyfund.org, wikisource.org, plato.stanford.edu`).
4. Exa exact-title search, unrestricted — today's behaviour.

Each hit is classified before fetch: `whole` when the source is a
catalogue/archive record or the page title has no section marker; `partial`
when the title carries a question, chapter, book or part number
(`Q. 94`, `Chapter 13`, `Book II`) or the host is a per-section site
(`newadvent.org/summa/`, `ccel.org/.../summa/`). Partial hits keep
`fetch_priority` — a single question of the Summa is still worth having — but
do not mark the work found, and the resolver keeps going.

Outcome per work, `found_whole | found_partial | not_found`, goes into
`build_summary.corpus.must_have` (0.D) and the corpus report shows
"Canonical works: 2 of 3 found in full".

### 7.C Long works, and what they cost

The Summa is four Gutenberg volumes of about two million characters. At $0.27
per 100 k chars nobody is ingesting that on a $3 budget, and the 200 k-char cap
in `GutenbergFetcher` already truncates it to the first tenth, which is the
treatise on sacred doctrine and the Five Ways and nothing about ethics.

- `MUST_HAVE_MAX_CHARS`: 200 k on STANDARD (≈ $0.54), 400 k on PRO (≈ $1.08),
  LITE keeps the fetcher cap. Charged against the discovery budget like any
  other source, so a build that spends a third of its money on the one text
  the topic is about does so knowingly, and the ledger shows it.
- `sources/sections.py`: given the planner's `sections` hint and a text with
  detectable headings (the chunker's `_detect_sections` already finds them),
  keep the named sections first, then fill to the cap from the start of the
  work. A work with no detectable headings is truncated as today. This is the
  only part of the plan that is genuinely new code rather than a change to
  existing behaviour, and it can ship after everything else.

**Done when:** a Thomism rebuild lists Summa Theologiae `found_whole` from
Gutenberg (with the natural-law questions present); Summa Contra Gentiles,
which Gutenberg does not carry, resolves through Internet Archive or CCEL as
`found_whole` or is reported `found_partial` with the routes tried; and the
corpus report shows the outcome for each. A must-have matched only by a
fragment is reported as `found_partial`, never as found.

---

## 8. Phase 4. Validation that tells evidence from stubs

### 4.A Substance

`ValidatedSource.substance ∈ {full, partial, abstract}` from
`full_text_method` and `text_chars`: `abstract` when the method is `abstract`
or the text is under 1,500 chars; `partial` when a landing page or a
truncated fetch; `full` otherwise. Stored as `sources.substance`.

- An `abstract` source passes only with ≥ 800 characters of abstract — a real
  abstract, not a blurb — and never counts toward `coverage_min_sources` or
  the non-tertiary/primary requirements. It still ships to the corpus, because
  a good abstract is one retrievable paragraph and a citation the RIS export
  wants, but it cannot make the loop stop looking.
- Abstract-only sources are capped at 15% of the round's accepted sources,
  lowest-scoring dropped with reason `abstract only (over share)`.

### 4.B Tertiary share

Tertiary sources are capped at 25% of a round's accepted sources, lowest
relevance dropped with reason `tertiary (over share)`. This leaves the Thomism
corpus's ten tertiary sources in place and would have removed nothing there;
it exists for the builds where a web-heavy plan produces a corpus that is half
overview pages. It is a cap, not a ban: Wikipedia's Thomism article is the
right thing to cite for "what is Thomism".

### 4.C The rubric

`_SYSTEM` in the validator names the two failure cases explicitly: a
catalogue record, table of contents or publisher blurb is `tertiary` and
scores at most 3 for quality whatever the work it describes; a study guide or
overview site is `tertiary` and its relevance score should reflect the depth
of what it says, not the match of its title. Bump `RUBRIC_VERSION` to
`v6-substance-q5r6`.

**Done when:** on the screening golden set the keep decision's precision does
not fall and recall of labelled-keep primary sources does not fall; a rebuilt
Thomism has no abstract-only source counted toward coverage; the corpus report
shows `abstract_only_share` and `tertiary_share`.

---

## 9. Phase 5. A loop that stops on depth, and can afford to run

### 5.A Depth in the target

`CoverageTarget` gains `require_primary: bool` and coverage counts only
`substance != abstract` sources. New per-tier defaults, snapshotted into
`experts.config` like everything else there:

| tier | min_sources | min_types | non-tertiary | primary | rounds after 0 | min rounds |
|---|---|---|---|---|---|---|
| LITE | 1 | 1 | no | no | 1 | 0 |
| STANDARD | 3 | 2 | yes | **yes** | 2 | **1** |
| PRO | 4 | 2 | yes | **yes** | 3 | **1** |

LITE does not move; its cost profile is a product decision recorded in
`test_lite_runs_exactly_one_extra_round_so_its_cost_profile_does_not_move`.
`shortfall` weights `missing_primary` at 5, between "no sources" (10) and
"wrong mix" (3), so the loop closes holes first and primary gaps second.

### 5.B A guaranteed feedback round

`discovery_min_rounds` (1 on STANDARD+): `targets_met` cannot stop the loop
before that many rounds after round 0 have *run*. The feedback round is the
only stage that reads the corpus and searches in the field's vocabulary, and
`feedback_queries` already returns `authors` the corpus keeps citing; those
names go to the canonical resolver (7.B) as well as to Exa.

### 5.C Money for the round

`_ROUND0_BUDGET_SHARE = 0.65` on STANDARD and PRO: round 0 may commit at most
that share of `discovery_budget_usd`, so the feedback round always has at
least a third of the money. With the fetch floor (2.C) round 0 usually stops
short of the share on its own; the reserve is the backstop for a topic with
many strong candidates. LITE has no reserve because it has no guaranteed
round.

### 5.D What the feedback round is told

The weak-concept block already lists sources, types and tiers per concept; add
"primary: none" where 5.A's requirement is unmet, and add the top three
concept shares, so the model is asked in so many words to find primary
material for metaphysics rather than a twenty-fifth natural-law paper.

**Done when:** a STANDARD Thomism build runs two rounds; the second round's
`feedback_queries` event names the concepts without primary sources; the
final coverage table has no concept with `primary: none`; discovery spend
stays under $3.00.

---

## 10. Phase 6. Search that asks better questions

Each of these is small and independent.

- **Exa** (`ExaFetcher.search`): pass `exclude_domains` built from the
  penalised hosts in `_HOST_ADJUSTMENTS` — the results were going to be scored
  down anyway, and not fetching them saves triage tokens and slots. Let the
  planner set `category: research paper` on a per-query basis for scholarly
  queries (`fetcher_plans.exa.queries[].category`, optional).
- **OpenAlex**: request `per-page` at twice `max_results`, keep works with a
  route to text (`oa_pdf_url`, `pmcid`, `arxiv_id`, or a landing page on a
  publisher host) ahead of abstract-only records, and cut to `max_results`.
  Exclude `type:paratext` is already there; add `type:!review` is *not* right
  (reviews are secondary sources) — leave type alone.
- **Reddit**: base quota 5 → 2 in `_build_fetchers`. The planner can still
  weight it to 2 for a practitioner topic.
- **Wikipedia**: unchanged; the quota is small and S2 makes its noise
  harmless.
- **YouTube**: the snippet is the title. Ask Exa for `text` with a small
  character budget so triage sees a description, as the Exa fetcher already
  does.

**Done when:** triage candidate counts drop on penalised hosts to zero for Exa
results; OpenAlex's share of abstract-only records in a build falls; nothing
else changes.

---

## 11. Rollout, order, and the numbers to publish

Order by dependency and by value per hour:

| step | phase | size | why here |
|---|---|---|---|
| 1 | 0.A–0.D | S | everything after this is measured by it |
| 2 | 2.A–2.B | S | the largest quality defect, a day of work, no product change |
| 3 | 1.A, 1.D, 0.C | S | outcomes and retries; the S2 key is a setting |
| 4 | 2.C–2.D | S | the floor; needs the ledger from step 1 to pick the number |
| 5 | 5.A–5.D | M | depth targets, the guaranteed round, the reserve |
| 6 | 4.A–4.C | S | substance and shares |
| 7 | 1.C | M | Gutenberg catalogue |
| 8 | 7.A–7.B | M | the canonical resolver |
| 9 | 0.E | human time | label the Thomism triage set and one screening set; run the harnesses |
| 10 | 6 | S | search tuning |
| 11 | 7.C | L | sections for long works; ships last, and only PRO needs it |

Rebuild Thomism after step 6 and again after step 8; each rebuild's
`build_summary.corpus` goes in the table below. The retrieval golden set from
[retrieval-quality.md](retrieval-quality.md) is content-matched and survives
a rebuild, so `python -m peritus.eval.retrieval run thomism` before and after
is the check that a smaller, better corpus does not cost recall (baseline
recall@10 0.644, MRR 0.535).

### Changelog of measured results

| date | build | kept | primary | tertiary | abstract-only | junk fetched | must-haves whole | rounds | discovery $ |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-15 | Thomism STANDARD, job 53 (baseline) | 43 | 3 | 10 | 12 | 11 | 0 of ? (plan not recorded) | 1 | $2.30 committed of $3.00 |
| | after step 6 | | | | | | | | |
| | after step 8 | | | | | | | | |

---

## 12. Risks, and what not to do

- **Do not move the calibrated constants** from the corpus-quality work:
  `SIMHASH_MAX_DISTANCE = 10`, `_TYPE_CAP_HEADROOM`, `_BASE_FETCH_BUDGET = 60`,
  fetch order by score with cost as a tiebreaker (never value per dollar),
  the snowball fetchability check. Each looks like a tidy-up and each was
  measured. This plan adds a floor *beside* the count ceiling; it does not
  lower the ceiling.
- **The floor can starve a thin topic.** That is what the relaxation rule
  (2.C) and the `floor_relaxed` event are for; if a build ends with fewer than
  ten sources the corpus warning already fires. Watch `below_floor` counts in
  the ledger for the first ten builds.
- **A guaranteed round costs money on STANDARD.** Bounded by the reserve
  (5.C) and by `discovery_budget_usd`, which is unchanged. Expect STANDARD
  discovery to use more of its $3.00 than today's $2.30; the spend cap ($6.00)
  is untouched.
- **Whole canonical works are expensive and the cap truncates them.** 7.C is
  explicit about the price and takes the planner's sections first. Do not
  raise `MUST_HAVE_MAX_CHARS` without the sections selector; a 200 k-char
  prefix of the Summa is not "the Summa".
- **Do not label golden sets with a model**, for the reason the screening
  README gives. The triage harness measures the model against people or it
  measures nothing.
- **Do not fail a build because a channel failed.** Outcomes are for the log,
  the retry and the report; `BuildError` on "no sources discovered" stays
  the only fatal case.
- **Tier caps drop validated sources.** 4.A and 4.B drop with a reason and the
  rows stay in `sources` as `passed = false`, so a reviewer can see what the
  cap removed and turn it up if it was wrong.

## 13. Follow-ons this plan enables but does not include

- Turning `VALIDATE_SECOND_OPINION` on, once 0.E's screening set says it
  helps.
- Calibrating the ingest estimator (`CALIBRATED_AT`), which the ledger's
  per-round `estimated_ingest_usd` against metered spend now makes a query.
- A per-concept share cap (S6's natural-law over-representation), once
  `concept_shares` has been observed across enough builds to pick a number.
- Re-screening an existing corpus under a new rubric without a rebuild, which
  the capture and ledger make possible and nothing yet does.
