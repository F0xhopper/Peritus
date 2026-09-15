# Plan: the syllabus — a planner that has read something, facets, voices, and tags that cost something

**Date:** 2026-09-15
**Method:** one STANDARD build read end to end from its persisted plan,
`build_summary`, `sources` rows and `candidate_screenings` ledger (Thomism,
expert 60, built today on the `web` branch after
[source-selection.md](source-selection.md) phases 0–7 shipped), and the code as
it is. Expert 60 is one build; nothing here is measured against a golden set.
Where a claim rests on that single build it says so.

**The brief:** a corpus can only contain what its syllabus asks for. Today the
syllabus is written in one model call whose entire input is the topic string,
is capped at eight concepts whatever the tier, and is then the only thing
coverage measures and the feedback loop chases. For Thomism that produced eight
concepts that are all Aquinas's philosophy — nothing on the theology, nothing on
the history of the school, no contemporary debate — and a corpus with no Thomist
commentator in their own voice, although the plan's own definition of "primary"
names Cajetan, Gilson and Maritain. The tags that satisfy the syllabus are free,
so the loop declared every concept covered with primary material while the one
passage the plan had named for natural law was missing.

This plan follows [source-selection.md](source-selection.md), which built the
resolver, the substance rules and the depth targets. Everything here sits on top
of that work, and none of its calibrated constants move (§7).

---

## Implementation status (2026-09-15)

Phases 0–4 implemented on the `web` branch, same day, in the rollout order of
§5. **Phase 5 has not run**: nothing in §1's target column is claimed, and the
changelog in §8 has only its "before" row. Measuring means recreating Thomism
STANDARD, beekeeping LITE and production ML STANDARD (live builds, real spend)
and running `peritus.eval.retrieval run thomism` before and after.

| step | phase | status | where |
|---|---|---|---|
| 1 | 0.A | done | `sources/triage.py` `rank_candidates`: near-duplicate titles compared within `(must_have_title, must_have_sections)` groups only, and never across numbered volume designators |
| 1 | 0.B | done | `canonical.matching_work` refuses about-host URLs, encyclopedia/summary title suffixes and the work named after in/of/on/about; `builder._boosted_must_have_titles` drops a work resolved whole (round 0) or found whole in the corpus (later rounds) |
| 1 | 0.C | done | `builder._enforce_ceiling` at the fetch boundary, logged `ceiling_enforced` with the fetcher |
| 2 | 1 | done | `sources/orientation.py`; `_plan_research` builds the pack itself, so tests that stub the planner stay offline; `research_plan.orientation`, `plan_ready.orientation` |
| 3 | 4.A–4.D | done | validator `covered_concepts` as `{concept, depth}`, rubric `v8-graded-tags-q5r6`; `coverage.counting_tags`, `has_primary`; `canonical.concept_named_texts`; `sources.concept_depths` (migration 030); audit `coverage` concepts carry `primary_sources` / `has_primary` / `named_text` |
| 4 | 2 | done | `facets` in the tool schema and `_normalise_facets`; `ExpertConfig.max_key_concepts` 8/10/14; `CoverageReport.facets`, `weakest_by_facet`, `thinnest_by_facet`; feedback grouped by facet |
| 5 | 3.A–3.E | done | `figures` in the plan, `SCOPE_FIGURE` lookups (`figure_texts` 0/3/6); `open_text`, `substitute`, `NOT_OBTAINABLE`; `sources/hosts.py`; `ThoughtLeadersFetcher(figures, topic)` / `search_people`; validator author rule; `canonical.figure_outcomes` → `build_summary.corpus.figures`, audit `selection.figures` |
| 6 | 5 | **not run** | see above |

Decisions the text left open, each deliberate:

- **The gate with no named text.** §4.C says primary is met by a `sets_out`
  primary source *or* a found named text. Read literally that re-grades every
  concept the planner named no text for — most concepts of a technical topic,
  whose primary material is many papers — so a concept with **no** named text
  keeps the old rule (any primary source tagged with it). The gate engages
  exactly where F5 found the lie: a named text that is missing.
- **Named-text status is per lookup, not per work.** A work found whole in one
  volume does not find a concept whose lookup named sections elsewhere: a hit
  counts for a concept only when it was looked up for that concept, or its
  lookup named no sections. Whole but truncated before named sections is
  `partial`.
- **Boost exclusion by round.** Round 0 has no corpus, so it drops the boost
  for works the resolver found whole; later rounds drop it only once the work
  is found whole in the accepted corpus, so a whole copy that failed to
  download keeps its boost.
- **Designators in the near-duplicate filter.** Grouping by work and sections
  alone would still collapse three volumes proposed by one overall lookup, so
  within a group, titles whose numbered part / volume / book designators differ
  are never duplicates. Two copies of one volume still collapse.
- **Substitutes** are resolved only for a work that is not obtainable *and* was
  not resolved whole, after the first resolution rather than beside it, and
  inherit the concepts of the work they stand in for.
- **An in-copyright book** (neither `public_domain` nor `open_text`) gets one
  open Exa search. Papers and standards keep their routes: `open_text` is not
  asked of them.
- **Feedback `authors`** come back on `Feedback.authors`, beside the
  per-concept queries, and go to
  `ThoughtLeadersFetcher.search_people` as extra candidates, not into concept
  queries.
- **Orphan concepts** — in `key_concepts` but no facet — join a facet named
  "Other" (or, with no facets at all, one named after the topic).
- **The about-page rules** (host, title site suffix, the work named after a
  preposition) live in `names_the_work`, so the resolver's routes refuse the
  same pages triage's boost does, and `plato.stanford.edu` is no longer a
  primary-text host. **The about-host list** lives in `sources/hosts.py`. Triage's scored table
  keeps its per-host numbers; a test holds every summary service in the list to
  a negative prior, rather than regenerating the calibrated table from it.
- **Migration 030** is applied to the local test database only. Deploying
  `api/` to Fly runs migrations in its release command; a local build against
  the production database before then would fail writing `concept_depths`.

---

## 1. Summary

| # | Finding | Measured (expert 60) | Fix | Phase |
|---|---------|----------------------|-----|-------|
| F0 | Two bugs hide the syllabus's outcome: triage's near-duplicate title filter dropped the Summa volumes the resolver had deliberately queued separately, and the must-have boost still fetches pages *about* a work | Part I-II and Part III marked `near_duplicate` of Part I (title ratios 0.93 and 0.97 against a 0.85 threshold); the treatise on law, the plan's named text for natural law, is absent. Round 1: 5 of 10 fetches must-have boosted, 3 not the work. Part I stored at 584k chars, 420 chunks, against a 200k ceiling | Exempt resolver candidates from the title filter; switch the boost off once a work is found whole; enforce the ceiling at the fetch boundary | 0 |
| F1 | The planner is blind | `_plan_research` sends `Topic: Thomism` and nothing else. The concept list reads as an introductory philosophy syllabus; Wikipedia's article on the same topic outlines philosophy, theology, the history of the school and its modern schools | An orientation pack — one or two reference overviews' leads and section outlines — shown to the planner as a checklist of facets | 1 |
| F2 | The syllabus is flat and capped at eight, and the loop chases the four largest shortfalls | `maxItems: 8` in the schema and `[:8]` in `_normalise_plan` for every tier; `_LOOP_MAX_CONCEPTS = 4`. Round 1 fetched four more essence-and-existence sources; act and potency ended at a 52% share | Facets: the planner groups concepts under 2–5 facets; the count scales with tier; the feedback round takes the weakest concept from each facet in turn | 2 |
| F3 | The tradition's voices are defined as primary and never sought as such | `primary_source_definition` names Cajetan, John of St Thomas, Garrigou-Lagrange, Maritain, Gilson, Feser. Own-voice sources from any of them: 0. The thought-leaders channel returned the SEP entry on Maritain and the IEP entry on Aquinas, both kept as tertiary. The validator's expected-author rule passes a page that "substantively presents their work" | The planner names figures and one obtainable work each; the resolver looks those up; the thought-leaders channel excludes the about-hosts and searches for writing *by* the person; the validator rule says about-pages are tertiary | 3 |
| F4 | An in-copyright must-have is reported `not_found`, as if the search had failed, and nothing substitutes for it | Gilson, *The Elements of Christian Philosophy*: `not_found`, one route tried | `not_obtainable` as a distinct outcome; the planner names a substitute with a free English text | 3 |
| F5 | Tags are free, so targets are cheap and the named text is never checked | Summa Contra Gentiles tagged with four concepts including natural law and the five ways; Part I with four; every concept "met" with 21 sources; natural law shows `primary: 2` while its named text is missing; `concepts_without_primary: []` | Graded tags (`sets_out` / `treats` / `mentions`), at most three counting tags per source, a section-cut work counts only for the concepts its sections were cut for, and a concept's named text gates "has primary" | 4 |

What the Thomism syllabus and corpus look like today, and what "fixed" means:

| | today (expert 60) | target |
|---|---|---|
| facets the concepts span | 1 (Aquinas's philosophy) | ≥ 4, including the school's history and its theology |
| largest single concept share | 52% | ≤ 35% |
| figures with a source in their own voice | 0 of 6 named | ≥ 2 |
| thought-leader channel's kept sources that are not tertiary | 0 of 2 | ≥ half |
| concepts reported met-with-primary while their named text is missing | 1 (natural law) | 0 |
| in-copyright must-have reported as a search failure | 1 | 0 (reported `not_obtainable`, substitute tried) |
| primary share | 52% | 30–50% |
| sources kept | 21 | 25–40 |

---

## 2. What runs today, with the numbers from expert 60

```
plan        Sonnet, one call, input = "Topic: Thomism"
            → 8 key_concepts (cap 8), per-fetcher queries and weights,
              primary_source_definition, 4 must_have_works, 8 concept_primary_texts
resolve     canonical works and concept texts looked up by title, per volume
            → Summa Part I fetched; Part I-II and Part III dropped by triage as
              near-duplicate titles of Part I
search      9 active fetchers, 152 candidates; 108 below the fetch floor
fetch       12 in round 0; 21 above-floor candidates left as `budget`
validate    Haiku tags each source with the key concepts it "substantively
            covers" — one tag per concept, no depth, no cap
coverage    3 sources · 2 types · non-tertiary · a primary, per concept
            → met after round 1; every concept has a primary by tag
loop        round 1 = the 4 concepts with the largest shortfall (all met, so
            `thinnest`): feedback queries, 161 candidates, 10 fetched, 62 left
              as `budget`; 4 of the 10 were more essence-and-existence
stop        targets_met · 21 kept · $2.85 of $3.00 estimated ingest, a third of
            it one 584k-character volume
```

The concept list the planner wrote, against the outline of the reference
overview it never saw:

| planner's key concepts (all eight) | Wikipedia "Thomism", top-level sections |
|---|---|
| The five ways; act and potency, hylomorphism and the metaphysics of being; analogy of being; natural law and the ethics of virtue; the real distinction; faculty psychology; the transcendentals; epistemology and abstraction | Philosophy (metaphysics · epistemology · ethics · psychology); **Theology** (revelation, grace, sacraments); **History** (Aquinas's own period · the Thomistic commentators · second scholasticism · **Neo-Thomism and *Aeterni Patris*** · **analytic Thomism** · the twentieth-century schools) ; Influence |

Everything in bold is a facet an expert on Thomism must be able to teach and
nothing in the build will ever look for, because coverage only measures the
eight, the feedback round only searches the eight, and the planner's own
`web` query "Neo-Thomism revival 20th century" fed a channel whose results were
scored against a syllabus that has no such concept.

---

## 3. Findings

### F1. The planner is blind

`_plan_research` (`experts/builder.py`) calls the strong model with
`_PLAN_SYSTEM` and the user message `Topic: {topic}`. The system prompt asks
for breadth and for a count that "scales with how much ground the topic
actually covers", but the model has nothing to measure the ground with except
its memory of the topic name. The same argument that built `experts/feedback.py`
applies one stage earlier: a query written by a model that has read the field's
own material beats one written blind, and a syllabus written by a model that has
read how a reference work structures the topic beats one written blind. Reading
one overview before planning is not the loop rewriting its own goal — the
brief is still written once, before any search, and never changed after.

### F2. Flat, capped, and searched by shortfall

`key_concepts` is `minItems: 5, maxItems: 8` in the tool schema and `[:8]` in
`_normalise_plan`, for every tier. A LITE build on a narrow topic and a PRO
build on a whole tradition get the same ceiling.

The loop then asks about the `_LOOP_MAX_CONCEPTS = 4` concepts with the
largest shortfall (`CoverageReport.weakest`), or, once everything is met, the
four thinnest. Shortfall is a per-concept number, so when a corpus is heavy in
one area the four thinnest concepts are often that area's neighbours: round 1's
`feedback_queries` on expert 60 went to analogy, the five ways, the real
distinction and act-and-potency — the last two already the two largest shares
of the corpus. Nothing in the loop knows that these are one facet.

### F3. Voices: defined, not sought

The plan's definition of primary is right: "the original writings of Thomas
Aquinas himself … together with the works of major Thomist commentators and
interpreters writing in their own philosophical voice (e.g., Cajetan, John of
St. Thomas, Garrigou-Lagrange, Maritain, Gilson, Feser)". Three things then
happen to those names:

- **Nobody looks for their works.** `must_have_works` (≤ 4) and
  `concept_primary_texts` are the only title lookups, and the planner filled
  them, correctly, with Aquinas.
- **The thought-leaders channel finds pages about them.**
  `ThoughtLeadersFetcher` asks Haiku for 4–6 names (a second, blind call that
  does not see the plan's definition), then queries Exa with `"{name}" {topic}`
  for two neural results each. For "Jacques Maritain Thomism" the best neural
  match is the Stanford Encyclopedia entry on Maritain, which the domain prior
  then lifts by 2.5. Both thought-leader sources expert 60 kept are
  encyclopedia entries, classified tertiary — the validator got the tier right
  and the channel produced nothing the tier rule could accept.
- **The validator's author rule has a hole.** `_source_context` says: "If this
  content is not by {leader} *or does not substantively present their work*,
  score relevance low." An encyclopedia entry on Maritain substantively presents
  his work, so it passes at relevance 8 and the channel's purpose is not
  enforced.

### F4. In copyright is not "not found"

Gilson's *Elements* is `public_domain: false`; the resolver tried Exa on
primary-text hosts and reported `not_found`. The summary cannot tell a reader
whether the search failed or the work cannot legally be had, and the planner
was never asked what to use instead. For a tradition whose leading modern
voices published in the twentieth century, this is the common case, not the
edge.

### F5. Tags are free

The validator's `covered_concepts` asks for "which of the listed key concepts
this source substantively covers", one flat list. `compute_coverage` then counts
every tag on every counting source toward that concept's target — sources,
types, tier and primary alike. Three consequences on expert 60:

- The Summa Contra Gentiles carries four tags; Part I carries four; De Ente
  four. A 200k-character volume "covers" the five ways, the transcendentals,
  natural law and analogy at once, and each of those concepts gains a primary,
  a Gutenberg or web type and a counting source from one fetch. Targets that
  were meant to need three sources per concept are met by three long texts.
- **Natural law** shows `primary: 2` (Contra Gentiles and Part II-II, both
  tagged with it) and is "met", while the plan's own named text — Summa I-II
  qq. 90–97 — was never fetched. `concepts_without_primary` is empty. The
  named-text machinery that source-selection.md §7 built runs and reports
  per work (`found_whole`, because Part I was), never per concept.
- Act and potency, the catch-all concept, ends at a 52% share; the feedback
  prompt's "already well represented — do not search for more of these" line
  is the only thing pushing back, and it pushes on the query writer, not on the
  measure.

---

## 4. Design

### Phase 0 — prerequisites: two bugs that hide the syllabus's outcome

Cheap, certain, and the reason the natural-law text is missing. Land first.

**0.A The near-duplicate title filter and resolver candidates.**
`rank_candidates` (`sources/triage.py`) drops any candidate whose title is
within `_NEAR_DUP_TITLE_RATIO` (0.85) of one already kept. `merge_works`
(`sources/canonical.py`) deliberately produces one lookup per volume of a
multi-volume work, and the filter then collapses them: the three Summa volumes
score 0.93 and 0.97 against each other. Fix: a candidate carrying
`must_have_title` (any resolver candidate) is compared for near-duplication only
against candidates for the *same* work and the *same* `must_have_sections`; it
never dedups against a plan-fetcher candidate, and plan-fetcher candidates never
dedup against it. Test with the three volume titles and with two copies of the
same volume from two routes (which must still collapse).

**0.B The must-have boost after the work is found.** `must_have_titles` passed
into a round's triage should exclude every work whose resolution is already
`whole` (`self._canonical`). And `matching_work` should refuse a title that
carries a site suffix after `|`, `—` or `-` naming an about-host (Philopedia,
the encyclopedias, the summary services already in `_HOST_ADJUSTMENTS`), or the
pattern `… in <Work>` / `… of <Work>` where the work's title is the object of a
preposition ("The Aristotelian context of the existence-essence distinction in
De Ente et Essentia" is about De Ente). Test with the three round-1 examples
from expert 60 and with the true hits that must still match ("Thomas Aquinas:
De ente et essentia: English").

**0.C The text ceiling at the fetch boundary.** Part I was stored at 584k
characters in 420 chunks against a 200k `text_max_chars`; `select_sections`
caps correctly in isolation, so a fetch path skipped `apply_sections`. Rather
than find that path only: where the builder receives a `RawSource` for a
candidate stamped `text_max_chars`, cut to the ceiling and log `ceiling_enforced`
with the fetcher's name, so the next build says which path it was. Then check
`text_chars ≤ text_max_chars` for every canonical source on the measured
rebuild (phase 5).

**Done when:** a Thomism recreate keeps Summa I-II with `sections_matched` and
qq. 90–97 present; no round-1 fetch is must-have boosted for a work already
found whole; no source exceeds its stamped ceiling.

### Phase 1 — read before planning

**What.** A new module `sources/orientation.py` assembles an *orientation
pack* before `_plan_research` runs, and the planner is shown it.

**The pack.** Two lookups in parallel under one 8-second budget:

1. **Wikipedia.** `WikipediaFetcher.search(topic, 3)`; take the first hit whose
   title matches the topic (`SequenceMatcher` ≥ 0.6 on `title_key`) or whose
   snippet contains the topic. Fetch its extract with `explaintext` and
   `exsectionformat=wiki` (today's fetcher uses `plain`, which loses the
   heading markers) and split it into the **lead** (text before the first
   `== Heading ==`, capped at 3,000 characters) and the **outline** (headings of
   depth 1–2, boilerplate sections dropped — See also, References, Notes,
   External links, Further reading, Bibliography — capped at 60).
2. **A reference overview** through Exa, when a key is present:
   `search_and_contents(topic, num_results=3, include_domains=[plato.stanford.edu,
   iep.utm.edu, britannica.com], text={"max_characters": 4000})`; take the
   first whose title loosely matches the topic. SEP and IEP entries open with
   their own table of contents, which is the outline.

Either lookup failing, or matching nothing, leaves the pack short; both failing
leaves it empty and the plan runs exactly as today. The pack never fails the
build.

**The prompt.** `_PLAN_SYSTEM` gains one paragraph: "You may be shown how one
or two reference overviews structure this topic — their opening paragraphs and
section outlines. Use them as a *checklist of the topic's facets*, not as the
syllabus: every major facet they treat should be represented in your concepts
unless it is clearly outside what an expert on this topic must teach, and you
should add what they omit. Take the field's own terms and names from them for
your queries. If an overview is about something adjacent rather than this
topic, say so in `orientation_note` and rely on it less." The user message
carries the pack after the topic:

```
Topic: Thomism

<overview source="Wikipedia" title="Thomism" url="…">
Lead: …
Outline:
- Philosophy
  - Metaphysics
  - Epistemology
  …
- Theology
- History
  - Neo-Thomism
  - Analytic Thomism
</overview>
```

**The record.** `research_plan.orientation = {overviews: [{source, title, url,
headings}], note}`; the same on `plan_ready`; the stage log line names what
was read. The orientation pages are *not* injected into the corpus as sources —
the Wikipedia and Exa fetchers will find them on their own merits, and the
screening ledger stays an honest record of what search produced.

**Cost.** Two HTTP calls and roughly 4–6k extra input tokens on `PLAN_MODEL`,
about $0.02 a build. Latency two to four seconds, in parallel.

**Tests.** Outline parsing (heading depths, boilerplate dropping, a page with
no headings, a lead longer than the cap); hit selection (topic "Thomism"
against hits "Thomism", "Thomas Aquinas", "Thomas the Tank Engine"); the pack
rendering; `_plan_research` with a pack and with an empty one.

**Done when:** the stored plan for a Thomism recreate lists concepts under at
least four facets including the school's history and its theology; the plans
for the four other existing topics (beekeeping, epigenetics, production ML,
Aristotelian logic) are regenerated and recorded in the changelog, and no
narrow topic's count grows by more than one.

### Phase 2 — facets: a syllabus with two levels, sized by tier

**The planner's output.** `create_research_plan` gains `facets`:

```
facets: [{ name: "History of the school",
           concepts: ["Neo-Thomism and Aeterni Patris", "Analytic Thomism", …] }]
```

Two to five facets, two to four concepts each. `key_concepts` stays in the
schema for one release for a model that ignores the new field; `_normalise_plan`
flattens `facets` into `key_concepts` in facet order (casefold-deduplicated)
and, when only `key_concepts` came back, wraps them in one facet named after the
topic. Every downstream reader — triage, validation, coverage, feedback, the
picture finder, both clients — keeps reading the flat list; the wire type of
`key_concepts` (`string[]` in `web/lib/api/types.ts`, `Vec<String>` in
`cli/src/tui/screens/build.rs`) does not change.

**The count.** New `ExpertConfig.max_key_concepts`, default 8 so a snapshotted
config builds as it did: LITE 8 (unchanged), STANDARD 10, PRO 14. The value is
passed into the schema's `maxItems` and named in the prompt. A cap trims from
the largest facet first, so trimming never empties a facet. The prompt's
existing rule stands: the number the topic supports, not the maximum.

The honest constraint: more concepts at unchanged per-concept targets need more
counting sources, and STANDARD's $3.00 discovery budget was 95% committed on
expert 60 — with a third of it spent on one uncut volume (0.C). Phase 5
measures a 10-concept STANDARD build; if it stops `budget_exhausted` with
concepts unmet after 0.C has landed, STANDARD holds at 8 and the facet spread is
what improves it.

**Coverage.** `CoverageReport` gains `facets: [{name, concepts, met, primary}]`
(met = every concept met; primary = any concept has one) and two selectors:
`weakest_by_facet(n)` — from each facet with an unmet concept, its
largest-shortfall concept, cycling facets in order of their unmet count, until
`n` — and `thinnest_by_facet(n)` likewise. The loop calls these in place of
`weakest` / `thinnest`. Facets change *what the loop looks for next*, not when
it stops: `met` is still every concept at target.

**Feedback.** `weak_concepts_block` groups the weak concepts under their facet
names, so the query writer sees "Facet: History of the school — Neo-Thomism
and *Aeterni Patris*: 0 accepted sources, primary: none".

**The record.** `research_plan.facets`; `plan_ready.facets`;
`coverage_report.facets` and `build_summary.coverage.facets`. No migration:
`research_plan` is JSON. A client follow-up, not in this plan: the overview page
groups its concept chips by facet.

**Tests.** Normalisation (flatten, dedupe across facets, orphan concepts, the
cap trimming the largest facet, legacy `key_concepts`-only output);
`weakest_by_facet` ordering on a corpus heavy in one facet; the integration
loop test with two facets, one fully met, asserting round 1's concepts come
from the other.

**Done when:** on the Thomism recreate, round 1's `feedback_queries.concepts`
span at least two facets, and the largest `concept_share` is ≤ 0.35 (0.524
today).

### Phase 3 — voices, and works that can actually be had

**3.A The planner names figures.** `create_research_plan` gains `figures`, up
to six: `{name, why, work: {title, kind, public_domain, sections}, obtainable}`
— "people whose own writing is primary for this topic by your definition; for
each, one work of theirs with a freely available English text: public domain,
open access, or published by them online (a blog, a lecture transcript, a
preprint). Set `obtainable: false` and leave `work` empty when nothing of theirs
is freely available — name them anyway." New `ExpertConfig.figure_texts`,
default 0 (old snapshots unchanged): LITE 0, STANDARD 3, PRO 6. Obtainable
works become `MustHaveWork(scope=SCOPE_FIGURE)` lookups, resolved after the
concept texts inside the existing priority share (`_PRIORITY_BUDGET_SHARE`), so
a plan naming six long books cannot starve the corpus.

**3.B `not_obtainable`.** Works gain `open_text: bool` ("an authorised full
text is freely online: an open-access edition, the publisher's free chapter, the
author's own site") and an optional `substitute` work. The resolver skips the
Gutenberg and Internet Archive routes for a work that is neither public domain
nor open text (the licence check would refuse the hit anyway), tries Exa once,
and reports `not_obtainable` rather than `not_found` when that finds nothing;
the substitute is then resolved as a work of its own. `must_have_outcomes`
reports both. The prompt tells the planner to name an in-copyright canonical
work *and* its substitute, never to silently swap one for the other.

**3.C The thought-leaders channel searches for writing by the person.**
`ThoughtLeadersFetcher`:

- takes the plan's `figures` when the builder has them and skips its own
  identification call (one fewer blind Haiku call, and the same definition of
  "primary" the validator is judging by); the self-identify path stays for a
  plan without figures;
- queries Exa twice per figure: `{name} {topic}` with `exclude_domains` set to
  the about-hosts, and `{name}` with `category="personal site"` where the API
  accepts it; three results each. The about-host list is one tuple in
  `sources/hosts.py` shared with the triage prior and Exa's existing
  `exclude_domains`: the encyclopedias, Wikipedia, Britannica, the Catholic
  Encyclopedia, the summary and review services;
- drops, before triage, a hit whose title is `{Name} (Stanford Encyclopedia…)`,
  `{Name} | Internet Encyclopedia…`, `{Name} - Wikipedia` — the shape of an
  entry about a person, matched on the same host list.

**3.D The validator's author rule.** `_source_context` changes to: "Expected
author: {leader}. If this is *by* {leader}, judge it as their own work. If it
is *about* {leader} — an encyclopedia entry, a profile, a review of their work —
classify it tertiary; do not score relevance on how well it presents their
work." No new output field: a thought-leader source that passes as primary or
secondary is, by this rule, in the author's own voice.

**3.E The record.** `build_summary.corpus.figures: [{name, status: own_voice |
about_only | not_found | not_obtainable, source_urls}]`, where `own_voice`
needs a passed non-tertiary source from the figure's lookup or the
thought-leader channel with that `leader`. The feedback prompt lists "Figures
with no work in their own voice" beside "primary: none", and the feedback
round's `authors` output (names the corpus keeps citing but does not contain)
goes to the thought-leader search with the exclusions, not to raw Exa. The
audit report's `selection` block shows figures.

**Tests.** Query construction and exclusions (Exa called with the host list;
the "personal site" call present when the key is set); the about-title filter
against the two entries expert 60 kept and against a genuine essay by the
person; `not_obtainable` routing (no Gutenberg or archive call for a
non-public-domain, non-open work); `must_have_outcomes` figure statuses.

**Done when:** the Thomism recreate has at least two figures `own_voice`
(Feser's essays are self-published online; Garrigou-Lagrange, Cajetan and the
early Maritain have public-domain or openly hosted English texts); at least half
the thought-leader channel's kept sources are non-tertiary (0 of 2 today);
Gilson's *Elements* is reported `not_obtainable` with its substitute tried.

### Phase 4 — tags that cost something, and the named text gates "has primary"

**4.A Graded tags.** The validation tool's `covered_concepts` becomes a list of
`{concept, depth}` with depth ∈ `sets_out | treats | mentions`: "`sets_out` —
this source is where the concept is set out or argued at length (a chapter, a
section, the paper's subject); `treats` — a substantial discussion, more than a
passing page; `mentions` — referred to in passing. A source that sets out or
treats more than three of the listed concepts is probably a survey: give its
three deepest." `_match_concepts` keeps canonical names and depths; a legacy
string list (an old batch result) is read as `treats`. `ValidatedSource.
covered_concepts` stays the list of names at depth ≥ `treats` — the shape the
ledger, the feedback digest and `corpus_composition` already read — and gains
`concept_depths: dict[str, str]`; `sources.concept_depths jsonb` in migration
030. `compute_coverage` counts at most three tags per source, deepest first.
Rubric version `v8-graded-tags-q5r6`.

**4.B A section-cut work counts for the concepts it was cut for.** A source
whose candidate carried `must_have_concepts` and whose fetch recorded
`sections_matched = true` counts toward exactly those concepts — the sections
were cut out for them and nothing else is in the text. A whole work (no
sections hint, or none matched) counts by its graded tags like any source.

**4.C The named text gates "has primary".** `must_have_outcomes` becomes a
per-round call (it is a pure function over the works, the resolutions and the
accepted sources' metadata) and `compute_coverage` receives, per concept, the
status of its named text: `found` (whole or sections), `partial`, `missing`
(not found, not obtainable, or resolved but dropped before validation), or
`none_named`. `ConceptCoverage.named_text` reports it. `require_primary` is
satisfied by **either** a primary source tagged `sets_out` **or** a named text
`found` or `partial`. A concept whose named text is `missing` and whose only
primary tags are `treats` is not met on primary — which is natural law on
expert 60 exactly. LITE (`require_primary = false`) is unchanged.

`_retry_canonical`, which today re-resolves works whose route *failed*, also
re-resolves works whose best hit was dropped before fetch (0.A makes that rare;
this makes it recoverable), and the feedback prompt names the missing text:
"named text missing: Summa Theologiae I-II qq. 90–97".

**4.D The record.** `coverage_report.concepts[].named_text` and
`.depth_counts`; `build_summary.corpus.concepts_missing_named_text`;
`sources.concept_depths`; the audit report's per-concept table shows the named
text's status next to the primary count.

**Tests.** `compute_coverage`: depth counting, the three-tag cap, the
`must_have_concepts` restriction with and without `sections_matched`, the
named-text gate in each of its four states, LITE unchanged; `_match_concepts`
with graded and legacy input; the loop test asserting a concept with a
`missing` named text is `unmet` even with two `treats`-tagged primary sources.

**Done when:** on the Thomism recreate no concept is met-with-primary while its
named text is `missing`; the largest concept share is ≤ 0.35; and the stop
reason is still `targets_met` inside the budget — if it is `budget_exhausted`,
0.C's ceiling is the first suspect, not the targets.

### Phase 5 — measure

Recreate, not rebuild: every new `ExpertConfig` field defaults to the old
behaviour on a snapshotted config, so a rebuild of expert 60 would measure
nothing.

1. **Thomism STANDARD** (the build this plan was written from) — the table in
   §1, plus kept sources, primary share, rounds, stop reason, `$`, and the
   canonical ceiling check from 0.C.
2. **Beekeeping LITE** (a craft) and **production machine learning STANDARD**
   (a technical field with no public-domain primary texts) — to show the
   orientation pack and facets do not pad a narrow topic or send a technical
   one looking for classics. Their concept lists before and after go in the
   changelog.
3. Export the three builds' screening ledgers with `python -m
   peritus.eval.triage export` for the human labelling that
   source-selection.md phase 0.E is still waiting on.
4. `peritus.eval.retrieval run thomism` before and after, since a broader
   syllabus changes what the graph reconciles and what chat can cite.

Nothing in §1's target column is claimed until this table is filled in.

---

## 5. Rollout order and cost

| step | phase | why in this position |
|---|---|---|
| 1 | 0.A–0.C | certain, small, and the reason the named text is missing |
| 2 | 1 | the largest gain to the syllabus itself, no behaviour change downstream |
| 3 | 4 | a broader syllabus must not be met by free tags, or the loop stops before it searches for the new facets |
| 4 | 2 | facets need 4's honest measure to be worth iterating against |
| 5 | 3 | depends on the planner's new output shape (1, 2) and the resolver's outcomes (0) |
| 6 | 5 | measure, fill the changelog, then decide STANDARD's concept count |

Per-build cost, all tiers: the orientation pack (two HTTP calls, ~$0.02 of
planner input), graded tags (a few more output tokens per validated source on
the fast model), and the named-text gate (no calls). STANDARD and PRO add up to
three or six figure lookups — Exa searches, with fetches inside the existing
priority share. The loop may run its guaranteed round for a facet it would
previously have called met; that is bounded by `discovery_max_rounds` and the
discovery budget as today. No new model calls on the strong model beyond the
larger plan prompt.

## 6. Decisions deliberately not taken

- **Re-planning after round 0 with the corpus in view.** Rejected for the
  reason source-selection.md gave: a loop that can rewrite its syllabus can
  always declare itself finished. The orientation pack is read once, before
  the plan, and the plan is then fixed.
- **One planner call per facet.** More calls, each as blind as the first; the
  gain is in what the planner reads, not how many times it is asked.
- **Injecting the orientation pages into the corpus.** They are exactly the
  kind of source the fetchers already find, and the screening ledger should
  record what search produced, not what the planner was shown.
- **A per-concept or per-facet money purse.** Cost is per round and per
  source; a purse per concept would starve the concepts whose primary texts
  are long, which are the ones the corpus exists for. Round-robin selection
  gets most of the breadth without touching the budget.
- **A hard cap on any concept's share.** The composition share caps were
  switched off (`experts/composition.py`) because they removed sources that
  were fine; the same would happen here. Graded tags plus facet-first search
  move the share without dropping anything.

## 7. What does not move

- Every calibrated constant in [source-selection.md](source-selection.md) §12
  and `docs/build-flow.md`: `SIMHASH_MAX_DISTANCE`, `_TYPE_CAP_HEADROOM`,
  `_BASE_FETCH_BUDGET`, the score-then-cost fetch order, `FETCH_SCORE_FLOOR`,
  the priority share, the text ceilings.
- The brief is written once and never rewritten between rounds.
- `key_concepts` as a flat `string[]` on the expert, the `plan_ready` event and
  both clients.
- LITE's count (8), its coverage target, and its cost profile: LITE gets the
  orientation pack and graded tags, `figure_texts = 0`, and `require_primary`
  stays off so the named-text gate never engages.
- The validator's pass thresholds (q ≥ 5, r ≥ 6) and the tier definitions.

## 8. Changelog

| date | build | facets | max share | figures own voice | named texts found / named | primary | kept | stop | $ |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-15 | Thomism STANDARD, expert 60 (before) | 1 | 0.52 | 0 / 6 | 5 / 7 (I-II missing, De Veritate not found) | 52% | 21 | targets_met | 2.85 est. |
