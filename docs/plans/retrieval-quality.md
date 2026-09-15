# Retrieval quality: how experts are built and used, what the numbers say, and what to change

**Date:** 2026-09-15
**Method:** every figure below is read from the production database (5 built experts,
3,484 chunks, 5,177 graph nodes, 3,868 edges, 7 audited answers) or from the code as it
is on the `web` branch. No model call was made to produce this document. Where a sample is
small it says so; the answer-audit sample is seven answers and should be re-measured once
there are fifty.

**The brief:** find the changes that genuinely improve answers, in line with how grounded
RAG systems are built elsewhere, without a large increase in token usage. The short
answer is that the biggest wins here are not "spend more tokens" changes. Three of them
are bugs, two remove model calls, and the rest move tokens from places that do nothing
(junk chunks, near-duplicate concept lists, a coverage judge that never changes the
answer) to places that do (the parts of the passage the model is currently not shown).

---

## 0. Implementation status (2026-09-15)

R1–R12 are implemented on `web`; R13 was a spike and is not. What landed, and
where it departs from the recommendation as written:

| # | Where | Notes |
|---|---|---|
| R11 | `jobs/worker._resume_point`, `ExpertBuilder.resume` | A retry of a job whose expert reached `chat_ready`/`graph_ready` resumes (graph from stored chunks, or persona only) instead of resetting. A persona failure against a terminal provider error raises `BuildError` (not retried). Web build log keeps state on a `resumed_from` retry. |
| R2 | `search/service.py` | OR tsquery built from `plainto_tsquery` lexemes (`_FTS_QUERY`); question searched as an extra query (`include_question`). |
| R1 | `ingestion/chunker.py`, `graph/retriever.py`, `chat/faithfulness.py` | 1,000-char chunks, one-sentence overlap, whole passage shown. Existing experts show their 1,500-char chunks whole until rebuilt. |
| R3 | `ingestion/chunker.clean_text` | Patterns calibrated on production lines. Re-chunking every production source from its stored chunks: 3,484 → 2,605 chunks (−25%), sub-300-char chunks 26% → 0%, 3.7% of characters dropped. Also fixes text before the first heading being discarded. |
| R6 | `chat/agent.py` | Coverage judge removed. Gate: fewer than `RELEVANCE_MIN_PASSAGES` (3) reranked passages at `RELEVANCE_FLOOR` (0.15) → second pass on the planner's `fallback_queries`. Only applies when scores are a reranker's (`SearchResponse.reranked`). |
| R7 | `chat/agent.py` | Planner sees the last exchange (400 chars each) and returns `standalone_question`, which is what the question is searched and reranked as. |
| R4 | `experts/builder._reconcile_claims`, `graph/reconciler.ReconcileStats`, `graph/extractor.attach_orphan_claims` | `claims_reconciled` fires every run with examined / failed / returned / rejected-by-reason / inserted. Build events for the church-fathers build show the reconcile stage took 23 s for ~120 calls, 4 s before the provider refused the persona call — most likely every call failed; the new event will say. |
| R5 | `graph/resolution.py` | Canonical-label merge for concepts (acronym alias must share its first letter — a bracketed qualifier otherwise merged "(CIFAR10)" with "(MNIST)"), then embedding merge at 0.90 for same head noun / 0.93 otherwise, never across node types. Dry run on production: 91 of 3,072 concepts merge by label. The optional Haiku 0.85–0.90 step is not implemented. |
| R8 | `chat/grounding.build_grounded_context` | `(Where this passage sits: …)` line under `[n] citation`. |
| R9 | `graph/retriever.py`, PRO `graph_hops=1` | 4 concepts, labels only unless the passage has a reportable edge; one hop always fetched. |
| R10 | `chat/agent.apply_relevance_floor` | Floored passages stay in the audit trail as `not_in_context`; the audit now maps steps to passages by chunk id. |
| R12 | `eval/retrieval.py`, migration 028 | `python -m peritus.eval.retrieval generate|run|audits <expert>`. Gold passages are matched by content (5-shingle containment), so a set survives the rebuild that R1/R3 need. `answer_audits.dangling_citations` persisted. Use `--pace 6.5` on a Cohere trial key (10 calls/min): past it, rerank silently falls back to Haiku windows and the run measures two rerankers. |

Thomism, before the rebuild (old corpus, new retrieval code, 45 generated
questions, 44 of 45 reranked by Cohere): recall@10 0.644, MRR 0.535, source
recall@10 0.733.

---

## 1. Summary

| # | Finding | Measured | Fix | Tokens |
|---|---------|----------|-----|--------|
| F1 | The model is shown only the first 800 chars of each passage, but cites the whole chunk | 39% of retrieved text per answer is hidden; 61% of chunks exceed 800 chars | Chunk at ~1,000 chars, show the whole chunk | +0.6K/turn |
| F2 | The keyword arm of hybrid search is dead for planner subqueries (AND semantics) | 0 keyword hits for 5 of 6 real subqueries; 300–900 with OR | OR-semantics tsquery; also search the verbatim question | 0 |
| F3 | A quarter of the corpus is junk chunks: table-of-contents lines, reference entries, nav boilerplate | 904 of 3,484 chunks under 300 chars; the Summa Contra Gentiles is 201 TOC lines out of 213 chunks | Chunk hygiene at ingest | −20–25% build tokens |
| F4 | Cross-source reconciliation has produced zero edges in production | every claim-to-claim edge is a legacy migration row; the two post-reconciler builds have none | Instrument, find the cause, require `about` edges | 0 (already paid for) |
| F5 | Entity resolution leaves obvious duplicates | 7 "Varroa" concept variants, 3 "DWV" variants in one expert | Normalise labels before the embedding pass | −0.3K/turn |
| F6 | The LLM coverage check costs a call every turn and a second retrieval on 43% of turns, and its passages were never cited | 0 of 2 follow-up passages cited; follow-up queries are paraphrases | Deterministic gate on reranker scores; fallback queries from the planner | −1.7K/turn |
| F7 | The planner never sees the conversation | `_plan(question, topic)` only | Pass the last two turns, trimmed | +0.25K/turn |
| F8 | The contextual prefix is paid for at build, indexed, and never shown to the model | 226 chars per chunk | Show it as the passage lead line | +0.55K/turn |
| F9 | A persona failure retried the whole build and wiped a finished PRO corpus | expert 54: 66 sources, 2,446 chunks, 2,921 nodes → 0 | Degrade, don't raise; or resume from readiness | 0 |
| F10 | No retrieval golden set with real chunk ids exists | `stoic-philosophy.example.json` has placeholder ids | Synthetic QA set from chunks, plus the audit trail | one-off ~50K Haiku |

Net effect per chat turn: roughly 1K fewer Anthropic tokens than today and more relevant
evidence in front of the model. Net effect per build: fewer chunks, so fewer
contextualisation, embedding and graph-extraction calls.

---

## 2. What runs today

### 2.1 One chat turn (STANDARD tier)

```
question
  └─ plan          1 Haiku call → 4 subqueries + asker/type/directive   (~0.8K in)
  └─ embed         4 OpenAI query embeddings
  └─ hybrid search 4 × (200 semantic ∪ 200 keyword → RRF → 50)         (Postgres)
  └─ merge         RRF-sum across subqueries → top 50
  └─ rerank        1 Cohere call, question vs 50 docs → top 10
  └─ graph expand  anchors for 10 chunks → 1-hop edges → concepts
  └─ coverage      1 Haiku call over 10 × 600 chars                    (~1.7K in)
       └─ 43% of turns: 2 more embeds, 2 searches, 1 rerank, appended to context
  └─ compose       Sonnet: ~2.3K cached system + ~2.8K evidence + history (~650 out)
```

The composition prompt is well built: the system prompt is byte-stable per expert and
sits above Sonnet 5's 1,024-token cache minimum, history carries a cache breakpoint, and
per-turn shaping lands after it. Nothing below touches that. The Haiku helper calls are
each below Haiku 4.5's 4,096-token cache minimum and do not cache, which is fine as long
as there are few of them; the point of F6 is that there is one too many.

### 2.2 One build

Plan → discovery loop → validate → chunk (1,500 chars, section-aware) → contextualise
(Haiku, 5 chunks per call, 3K-char window) → embed (text-embedding-3-large) → chat-ready
→ graph extract (Haiku, 10 chunks per call: claims, concepts, `about`, `part_of`) →
entity resolution (embedding cosine ≥ 0.93) → reconcile (Haiku, one call per concept
with claims from ≥ 2 sources, up to 120 concepts) → graph-ready → persona (Sonnet).

---

## 3. Findings

### 3.1 The chat path

**F1. The model sees 800 characters of a chunk it cites in full.**
`EnrichedResult.context_block()` in `graph/retriever.py` renders `self.text[:800]`.
Chunks are cut at 1,500 chars (`CHUNK_SIZE_CHARS`), and the corpus median is 1,148.

| Per answer (n = 7) | chars |
|---|---|
| passage text retrieved into context | 12,235 |
| passage text actually shown | 7,415 |
| hidden by the 800-char cap | 4,820 (39%) |

Across the whole corpus, 35% of all chunk characters can never reach a prompt. The
citation `[n]` still resolves to the full chunk, so the audit trail, the faithfulness
judge (which also truncates at 800) and the reader are all looking at text the model was
not given. The coverage judge sees 600 characters, so it decides "unsatisfied" about
passages it saw less than half of. This is the single largest retrieval-quality defect
in the system and it costs nothing to fix except the tokens of the text itself.

**F2. Hybrid search is semantic-only on most turns.**
`_hybrid_search` matches the keyword arm with `plainto_tsquery`, which ANDs every term.
The planner is told to write "declarative retrieval-phrased subqueries", which are four
to seven content words. A chunk has to contain all of them to match.

| Query (expert: thomism) | AND hits | OR hits |
|---|---|---|
| ultimate end of man beatitude happiness Aquinas | 0 | 913 |
| final cause human purpose natural law Thomism | 0 | 909 |
| contemplation God intellect human flourishing | 0 | 719 |
| summum bonum human good Thomistic ethics | 0 | 705 |
| potency and actuality Aristotle metaphysics | 1 | 334 |
| potency definition philosophy potential capacity | 0 | 406 |
| *What is the end of man?* (verbatim question) | 31 | 254 |
| *what is potency* (verbatim question) | 13 | 13 |

The RRF fusion is therefore fusing one arm with an empty list on five of six subqueries.
The verbatim question, which does match, is not searched at all: only the subqueries are.
Migration 022's index and the `_FTS_EXPR` alignment are correct; the query shape is the
problem.

**F3 is a build finding but it shows up here:** junk chunks compete for the ten context
slots. See §3.2.

**F6. The coverage check is a call that does not change the outcome.**
`_assess_coverage` runs a Haiku call every turn. On 3 of 7 audited answers it said
"unsatisfied" and triggered a second retrieval. Its follow-up queries were paraphrases
of the primary subqueries ("potency definition philosophy" after "potency definition
philosophy potential capacity"). Two follow-up passages reached a prompt; neither was
cited. The follow-up pass costs two embeddings, two hybrid searches and a rerank, and
the coverage call itself costs about 1.7K Haiku input tokens on every turn, satisfied or
not. Seven answers is a small sample, but nothing in the design suggests the result would
change: the judge is asked whether 600-char previews "provide direct substantive
evidence", which is a question the reranker score already answers numerically.

**F7. Follow-up questions are planned blind.**
`ChatAgent._plan` receives the question and the topic. History reaches composition but
not planning. "What about the second one?" or "and how does Fisher differ?" are
decomposed with no idea what "the second one" or "Fisher" refer to. Query condensation
against the last turn or two is standard in every conversational RAG system and costs a
few hundred Haiku tokens.

**F8. The contextual prefix is never shown.**
Each chunk carries a `context_text` (avg 226 chars) generated at build time in the
Anthropic contextual-retrieval shape: which source, which section, what it is about. It
is embedded and full-text indexed, which is what it is for, but the model composing the
answer never sees it. For a passage from the middle of a paper, that one line is what
tells the model which study it is reading and whether the passage is background or the
finding.

**What the reranker ordering is worth.** Citation rate by retrieval rank, over the 67
passages that reached a prompt:

| rank | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| cited | 71% | 57% | 43% | 29% | 14% | 33% | 50% | 33% | 0% | 33% |

Cited passages averaged a Cohere score of 0.31; uncited ones 0.22. The ordering is
informative at the top and noise from rank 6 down. Passages 6–10 are still cited a third
of the time, so they earn their place; they are also the first to drop when a score
floor is applied (R10).

**Graph annotation at chat time.** A passage's "About:" block lists up to 8 concepts
with descriptions. Chunks anchor 2.2 concepts on average (p90 5), so this adds roughly
3K characters (~0.7K tokens) per turn. Because of F5 the lists are often near-synonyms
of each other. PRO's `graph_hops=2` is unused: `_enrich_one` only keeps edges touching
the passage's own anchors, so the second hop is fetched and discarded. No evaluation has
ever tested whether the concept list changes an answer; the earlier `A --supports--> B`
annotation was removed on exactly that ground.

### 3.2 The build path

**F3. A quarter of the corpus is not prose.**

| | count | share |
|---|---|---|
| chunks under 300 chars | 904 | 26% |
| chunk text identical to its section heading | 299 | 9% |
| reference-list entries (author/year/"Google Scholar"/DOI patterns) | 284 | 8% |
| table-of-contents lines (`... 195`) | 181 | 5% |

By source type the tiny-chunk share is 34% for `exa`, 34% for `openalex`, 33% for
`thought_leader`, and under 6% for wikipedia, youtube, web and pdf. Worst single
sources: the Summa Contra Gentiles (201 of 213 chunks are TOC lines, so the planner's
must-have primary text for Thomism is present as a table of contents), a bee virology
paper (81 of 158, the reference list), a natural-law paper (75 of 140).

The cause is in `ingestion/chunker.py`. `_CHAPTER_PATTERNS` includes
`^\s{0,4}\d{1,2}\.\s+[A-Z][A-Za-z ]{3,}`, which matches every numbered TOC line and
every numbered reference; each becomes its own section, and `_split_paragraphs` has no
minimum size, so each becomes its own chunk. There is no boilerplate strip for HTML
sources, so "### MDPI Initiatives", "## Next Steps" and "HOME | PERIODICALS | …" are
chunks too. Every one of these is contextualised (a share of a Haiku call), embedded, sent
to graph extraction, and eligible to take a context slot at chat time.

The overlap logic also rarely overlaps: the tail is rebuilt from whole paragraphs that fit
in 200 chars, which for prose paragraphs is usually none.

**F4. Reconciliation has never produced an edge in production.**

| edge type | edges | with `point`/`condition` | `cross_source` flag |
|---|---|---|---|
| about | 1,997 | – | – |
| part_of | 1,762 | – | – |
| supports | 79 | 0 | 0 |
| contradicts | 30 | 0 | 0 |
| qualifies | 0 | – | – |

All 109 claim-to-claim edges belong to the four experts built on 23 August, have empty
properties, and are what migration 024 kept from the old vocabulary. The reconciler
requires a stated `point` or `condition` and stamps `cross_source`, so none of these
came from it. Thomism (built 9 September, after the reconciler shipped) has 90 concept
groups that meet the eligibility rule (claims from ≥ 2 sources) and zero claim-to-claim
edges. The church-fathers build reached `graph_ready` with 2,921 nodes and emitted no
`claims_reconciled` event either. The event only fires when at least one relation was
inserted, so a pass that examined 90 concepts and returned nothing looks identical to a
pass that failed. The root cause is not determinable from the data; it needs one
instrumented run (§4, R4).

Independently, the graph the reconciler reads is thin:

| | count | share |
|---|---|---|
| claims with no `about` edge (invisible to reconciliation) | 722 | 34% of claims |
| concepts with no edge at all | 956 | 31% of concepts |
| chunks anchoring no node | 863 | 25% of chunks |
| reconcile-eligible concept groups, experts 40/41/42/43 | 1 / 4 / 1 / 7 | |

The extractor prompt says "every claim gets at least one `about` edge" and nothing
enforces it; an edge whose concept label the same batch did not emit is rejected as an
unresolved endpoint, and the claim stays orphaned.

**F5. Entity resolution merges too little.**
In the beekeeping expert the concept nodes include "Varroa destructor" (59 chunks),
"Varroa destructor mite" (11), "Varroa destructor mites" (9), "Varroa mite" (25),
"Varroa mites" (15), "Varroa mite infestation" (13) and "Varroa infestation" (4), plus
"Deformed Wing Virus (DWV)", "DWV virus" and "DWV (Deformed Wing Virus)". The pass
compares embeddings of `label: description` at cosine ≥ 0.93; inflection, a
parenthetical acronym, or a different description sentence is enough to keep two nodes
apart. The consequences compound: `about` groups fragment across the duplicates, so a
concept that three sources discuss can fail the reconciler's two-source rule; hop
expansion and the "About:" list repeat the same thing in four spellings.

**Source mix is healthy.** Of 120 passing sources, 42 are primary, 57 secondary, 21
tertiary (17.5%). The corpus-quality work did its job; the losses are downstream of it.

### 3.3 Robustness: the wipe

Expert 54 (the-church-fathers, PRO) on 12 September:

| time | event |
|---|---|
| 16:01:46 | chat_ready: 66 sources, 2,446 chunks |
| 16:25:44 | graph_ready: 2,921 nodes, 3,007 edges |
| 16:25:48 | retry, attempt 1: "Build finished without: a persona/description" |
| 16:26:30 | attempt 2, plan stage, retry: "research planning failed" |
| 16:27:36 | attempt 3, plan stage, error: same |

The expert is now `pending` with 0 sources, 0 chunks, 0 nodes. The completeness gate in
`experts/builder.py` raises `IncompleteBuildError` when the persona is missing, with a
comment saying "the corpus stays exactly where it is — nothing is thrown away". It is
thrown away: the worker calls `reset_build_state` at the start of every attempt
(`jobs/worker.py:330`), and `IncompleteBuildError` is deliberately retryable. Persona
failed four seconds into its stage and planning failed within a second on both retries,
which is the signature of the API refusing requests, not of a flaky persona. A retry
could not have succeeded and each one destroyed the paid corpus. Thomism shows the same
failure in a different shape: `graph_ready`, no persona, still listed. Not a retrieval
finding, but it decides whether there are results at all.

### 3.4 Measurement

The harness in `eval/` has grounding metrics, helpfulness metrics and a screening
harness, and no retrieval golden set with real chunk ids: `stoic-philosophy.example.json`
carries placeholder ids and the investing set deliberately leaves them empty. So none of
F1, F2, F3 or F5 can currently be shown to have moved recall. `dangling_citations` is
logged per answer and not persisted, so the one free grounding signal the system emits
is not queryable.

---

## 4. Changes, ranked

Ranked by expected quality gain per unit of work, with the token effect per STANDARD
turn or per build. "Chars/4" is used for token estimates.

**R1. Show the whole passage; chunk at ~1,000 chars.**
`ingestion/chunker.py`: `CHUNK_SIZE_CHARS=1000`, split on sentence boundaries when a
paragraph must be cut, overlap of one sentence rather than a whole-paragraph tail.
`graph/retriever.py`: drop the `[:800]`. `chat/agent.py::_assess_coverage` and
`chat/faithfulness.py`: same text the composer sees. Requires a rebuild to take effect
on existing experts; new experts get it immediately.
Effect: the model can cite what it reads; the median passage stops losing its second
half. Tokens: 10 × ~1,000 chars vs 10 × 800 shown today, about +0.6K per turn. (Keeping
1,500-char chunks and showing them whole would be +1.2K; the smaller chunk is also the
better retrieval unit for a reranker.)

**R2. Fix the keyword arm and search the question.**
`search/service.py`: build the tsquery as OR-joined lexemes
(`websearch_to_tsquery('english', 'a OR b OR c')` or `to_tsquery` over
`plainto_tsquery`'s lexemes joined with `|`) and keep `ts_rank_cd` for ordering, so a
chunk matching four of six terms outranks one matching two. Add the verbatim question
as a fifth query in `batch_search` (one embedding, no LLM tokens); RRF-sum already
rewards a chunk that both the question and a subquery find.
Effect: the keyword arm returns candidates on every subquery; short factual questions
match their own wording. Tokens: none.

**R3. Chunk hygiene at ingest.**
In `ingestion/chunker.py`, before section detection: drop lines matching a
table-of-contents pattern (`^\d+\.\s.*(\.{3}|…)\s*\d+\s*$`) and reference-entry
patterns (`^\d+\.\s+[A-Z][A-Za-z-]+ [A-Z]{1,3}[,.]`, `\[Google Scholar\]`, `\[CrossRef\]`,
bare DOI lines); drop markdown nav blocks (`^#{2,3} .+\n(\|.*|- .*\n)+` with no prose);
remove the numbered-line pattern from `_CHAPTER_PATTERNS` or require it to be followed
by at least 200 chars of body before it counts as a heading; merge any chunk under 300
chars into its neighbour; log the dropped share per source so a source that is 90%
junk (the Summa) is visible in the build log and can be re-fetched from a better
resolver.
Effect: roughly 20–25% fewer chunks, none of them prose; retrieval stops surfacing
"### MDPI Initiatives". Tokens: −20–25% on contextualisation, embedding and graph
extraction per build. This is the one change that reduces the build bill.

**R4. Make reconciliation produce edges, and prove it.**
Emit a `claims_reconciled` event with `concepts_examined`, `relations_returned`,
`relations_rejected` even when the insert count is zero; log `rejected` from
`insert_relations` at INFO with the reason counts (it already does when non-empty).
Run one interactive build of a small topic and read the event. Two likely causes, both
cheap to rule out: `parse_relations` rejecting everything because the model returns
`point`/`condition` under a different key, or `gather_claude_calls` returning `None`
for the whole stage. Then, at extraction, enforce the prompt's own rule: a claim whose
`about` edge cannot be resolved is attached to the concept nodes extracted from the same
chunk (deterministic, no model call), so the 34% of orphaned claims become visible to
the pass.
Effect: the contradiction and qualification surfaces in chat, the audit page and the
graph view start carrying real data. Tokens: the reconcile calls are already budgeted
(≤ 120 per build) and are currently spent for nothing.

**R5. Normalise before resolving entities.**
In `_resolve_entities` (`experts/builder.py`): before the embedding pass, canonicalise
each label (casefold, strip a trailing parenthetical and register it as an alias,
singularise the head noun, drop leading articles) and merge nodes whose canonical labels
are equal, same `node_type`. Then run the embedding pass at ≥ 0.90 for same-type pairs
whose canonical labels share a head noun, keeping 0.93 otherwise. Optionally hand the
0.85–0.90 band to one Haiku call per candidate cluster ("are these the same thing?"),
capped at ~30 clusters per build.
Effect: the Varroa family becomes one node; `about` groups consolidate, which feeds R4;
"About:" lists stop repeating themselves. Tokens: −0.3K per turn from shorter concept
lists; ≤ 30 small Haiku calls per build if the optional step is used.

**R6. Replace the LLM coverage judge with a score gate.**
Drop `_assess_coverage`. After reranking, if fewer than 3 passages exceed a Cohere
relevance floor (start at 0.15 and calibrate on the audit data, where cited passages
average 0.31 and uncited 0.22), run the follow-up pass using two "fallback" subqueries
that the planner is asked for in its existing call (broader phrasings to use if the
first set finds little). No second Haiku call, no second planning step.
Effect: the second pass runs when retrieval was actually weak, with queries that are
not paraphrases of the first set. Tokens: −1.7K Haiku input on every turn, plus the
follow-up embeddings, searches and rerank on most of the 43% of turns that currently
trigger it.

**R7. Give the planner the conversation.**
`ChatAgent.retrieve` receives `history` already available to the caller; pass the last
user and assistant turns, each trimmed to ~400 chars, into `_plan` as a "Conversation
so far" block, with the instruction to resolve references in the question before
decomposing it.
Effect: follow-up questions retrieve on what they mean. Tokens: +0.25K Haiku input per
turn.

**R8. Show the contextual prefix.**
`build_grounded_context`: render `[n] citation — <context_text>` as the passage lead
line, then the text. It is already in `SearchResult.context_text`.
Effect: the model knows which study, which section, and whether a passage is the
finding or the background. Tokens: +0.55K per turn, paid for by R6 and R9.

**R9. Trim graph annotation to what it can defend.**
`_MAX_CONCEPTS_PER_RESULT = 4`; label only, no description, unless the passage has a
reportable (`contradicts`/`qualifies`) edge; set PRO `graph_hops` to 1 or make
`_enrich_one` use the second hop. Keep the disputed/qualified blocks exactly as they are:
they are the part of the graph that says something about the evidence.
Tokens: −0.4K per turn; no DB work on a hop that is discarded.

**R10. Apply a relevance floor before building context.**
Drop passages below the Cohere floor from the context block, keeping at least 3.
Effect: easy questions get 4–6 relevant passages instead of 10 with padding; hard
questions still get the full set. Tokens: −0 to −1K per turn depending on the question.

**R11. Stop the persona gate from destroying corpora.**
Either return to degrade-don't-raise for the persona (expert stays `graph_ready`,
nameless, `regenerate_persona` fixes it later, and the catalog hides nameless experts
rather than the builder failing them), or make a retry resume from the recorded
readiness: `graph_ready` → skip to persona, `chat_ready` → skip to graph. Either way,
`reset_build_state` must not run on a retry of a job whose expert is already
`chat_ready` or better. Also treat a persona or plan failure that returns within
seconds as a provider error (`_raise_if_provider_down` already exists for this) rather
than a retryable build.
Effect: a $4 PRO corpus survives a $0.01 persona call failing. Tokens: none.

**R12. A retrieval golden set, generated once.**
For each built expert, sample ~80 prose chunks (post-R3) and ask Haiku for one question
each chunk answers on its own; store `(question, chunk_id, source_id)`. Run the
retrieval-only path (plan → search → rerank, no composition) and report recall@10 and
MRR per expert. Cost: one-off ~50K Haiku tokens per expert to generate, and per run only
embeddings and one Cohere call per question. Add the audit trail's cited chunks as a
second, weakly-labelled set that grows for free. Persist `dangling_citations` in
`answer_audits`. Every change above should be run against this before and after; R1,
R2, R3 and R5 in particular can be measured with no composition calls at all.

**R13. Spike, not a recommendation: the Citations API.**
Anthropic's Messages API can take each passage as a `document` content block with
`citations: {enabled: true}` and return `cited_text` and `document_index` per claim,
verified server-side, so a dangling `[n]` cannot happen and the audit trail gets
character-level provenance. It would replace `parse_citations`, change the SSE
`sources` event, and the web, TUI and CLI clients all parse `[n]` today, so this is a
contract change to be sized separately. Input tokens are comparable; check the current
docs for how cited text is billed before deciding.

---

## 5. Token budget, per STANDARD turn

| Component | Today | After | Δ |
|---|---|---|---|
| Sonnet system prompt (cached) | ~2.3K | ~2.3K | 0 |
| Sonnet evidence: passage text | ~1.85K | ~2.5K (R1) | +0.65K |
| Sonnet evidence: context prefix | 0 | ~0.55K (R8) | +0.55K |
| Sonnet evidence: graph annotation | ~0.7K | ~0.3K (R9) | −0.4K |
| Sonnet evidence: relevance floor | – | (R10) | −0 to −1K |
| Haiku plan | ~0.8K in | ~1.05K in (R7) | +0.25K |
| Haiku coverage | ~1.7K in | 0 (R6) | −1.7K |
| Follow-up pass (43% of turns) | 2 embeds, 2 searches, 1 rerank | only when the gate trips | fewer |
| Sonnet output | ~650 | ~650 | 0 |

Net: about −1K Anthropic tokens per turn, with Sonnet input up ~0.8K and Haiku input down
~1.5K. At list prices that is within a tenth of a cent of neutral either way. Per build:
R3 removes the 20–25% of chunks that were never prose, and every later stage scales
with chunk count.

---

## 6. Order of work

1. **R11** first. It is the one that loses money and corpora today.
2. **R2, R1, R3** together: they are the retrieval-correctness set and all need a rebuild
   to show on existing experts. Measure with **R12** before and after.
3. **R6, R7** next: the chat loop gets cheaper and follow-ups work.
4. **R4, R5**: the graph. R4 needs an instrumented build; R5 is a pure-function change with
   tests.
5. **R8, R9, R10**: tuning, once R12 can show the effect.
6. **R13**: size it; adopt only if the client contract change is worth the verified
   provenance.

---

## 7. What not to do

- Do not re-add a live grounding percentage to answers; it was removed on purpose.
- Do not retune the discovery constants (`SIMHASH_MAX_DISTANCE`, `_BASE_FETCH_BUDGET`,
  the fetch ordering) as part of this. They were calibrated on real builds.
- Do not cache the full document as a prompt prefix in the contextualiser; the sliding
  window is cheaper for any document over ~10K tokens.
- Do not make the graph the retrieval index. Passages are retrieved; the graph annotates.
  The findings here are about making the annotation true, not about walking the graph
  for candidates.
- Do not raise `max_context_passages` to compensate for F1. More partial passages is
  worse than fewer whole ones.

---

## Appendix: how the numbers were produced

All from the production Postgres, read-only. Rerun after any of the changes above.

- Chunk length distribution and tiny-chunk share: `source_chunks`, `length(text)`,
  grouped by `sources.source_type` and by source.
- Hidden text: join `answer_audit_passages` (where `passage_n IS NOT NULL`) to
  `source_chunks`, sum `least(length(text), 800)` against `length(text)`.
- Keyword arm: for each subquery in `answer_audits.subqueries`, count chunks matching
  `plainto_tsquery` against the migration-022 expression, versus the same terms joined
  with `OR` through `websearch_to_tsquery`.
- Citation rate by rank: `answer_audit_passages`, `disposition = 'cited'` grouped by
  `retrieval_rank`.
- Graph: `expert_edges` grouped by `edge_type` with `properties ? 'point'` and
  `properties->>'cross_source'`; claims lacking `about` via `NOT EXISTS`; anchors per
  chunk via `expert_nodes.chunk_ids @> ARRAY[source_chunks.id]`.
- Reconcile eligibility: claims grouped by the concept they are `about`, counting
  distinct `source_chunks.source_id` behind each claim's `chunk_ids`.
- The wipe: `build_events` for job 52, ordered by `seq`.
