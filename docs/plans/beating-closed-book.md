# Beating the closed-book model: retrieval and answers, evaluated, and a plan

**Date:** 2026-09-19
**The complaint:** "the answers do not seem good, or better than normal GPT."
**Method:** the chat path read end to end (`chat/agent.py`, `chat/grounding.py`,
`chat/neighbours.py`, `search/service.py`, `graph/retriever.py`,
`infrastructure/reranker.py`, and the fetchers that decide what text an expert holds);
the production database (6 experts, 20 audited answers with their passage-level trail,
the stored answers read in full); and a **blind head-to-head** run for this document —
12 questions across 4 experts, each answered by Peritus and by the same model with no
corpus, judged in both orders (§2). Every number below was read from one of those three.
Where a sample is small it says so.

---

## 0. Status — phases 1–4 implemented, 2026-09-19

Code for every item in phases 1–4 is in; phase 0's harness was promoted to run
the measurements (`python -m peritus.eval.headtohead`). Experts 63 and 66 were
backfilled in place (`scripts/backfill_corpus.py`: prose gate, 1M-char tails —
1,127 and 813 chunks — loci, 330 sections each); the database went 308 → 352 MB.

**After, one run** (`beating-closed-book/results-after-2026-09-19.json`): on the
original twelve, Peritus 5 – closed-book 6 – split 1 (was 4–6–2). Death and the
genetic-evidence question flipped to Peritus; natural law flipped away (judge:
the closed-book answer gave the eternal/natural/human law schema). Sources in
context rose on every Thomism and Anglo-Saxon question (king: 2 → 6, 6 → 27
passages) and the persona leaks and heading openings mostly went (heading first
line 4/12 → 2/17, persona overlap 5/12 → 1/17). Over all seventeen: 6–10–1;
every `how_to` (beekeeping, corpus not rebuilt — 3.5 needs a rebuild) and both
`broad` questions still lost. Not moved: quotations (0/17 — the clause is
ignored), loci in prose (1/17), directness (3.79 v 4.79). One run, a model
judge: read it as direction, not a rate. The chat-only run (phases 1–2 before the
backfill) was skipped to save spend.

| # | Where it landed | Notes |
|---|---|---|
| 0.1–0.4 | `eval/headtohead.py`, `eval/golden/headtohead/set-2026-09.json` (17 questions, classed), `eval/metrics.answer_form` | The form checks reproduce §3.8's baseline counts on the stored answers (4 heading openings, 5 persona overlaps, 0 quotations, 0 loci). |
| 0.5 / 1.9 | migration 035 `answer_audits.reranker`; `reranker.rerank_with_provider`, `fallback_count` + a warning per fallback turn | The paid Cohere key is still owed (ops). |
| 1.1 | `_plan_tool` requires all six fields; `_plan_call` retries once | |
| 1.2 | `relevance_threshold`, `min_kept`; `RELEVANCE_FLOOR=0.04`, `RELEVANCE_RELATIVE=0.5` | Re-derived from the 20 audited answers: 90% of cited passages ≥ 0.55× their answer's top; cited p10 = 0.098 absolute. |
| 1.3 | `retrieval_is_weak`: top < 0.25 or < 5 near it | |
| 1.4 | anchors by rank; neighbours prose-gated, best anchor first | |
| 1.5 | `search/service.rerank_document`, `rerank_query` | **Measured** (`eval/retrieval.py`, k=5): the note raised MRR 0.718→0.777 (Thomism) and 0.800→0.822 (Anglo-Saxon) at equal recall — on. The topic prefix gained nothing on Thomism and cost Anglo-Saxon 0.867→0.800 recall — `RERANK_TOPIC_PREFIX=false`. |
| 1.6 | `search/labels.py` (`citation_label`) | Title chrome stripped; a heading only when it looks like one; `chunk_meta.locus` leads. |
| 1.7 | persona above the answer rules; `PERSONA_MAX_CHARS=1500`; `strip_scripted` + `condense_persona`; `scripts/condense_personas.py` | Applied to all six stored personas (3.0–4.0k → 1.5–1.7k chars). |
| 1.8 | `uncovered_subquery_seats`; `SearchResponse.per_query/candidates` | Reranker now scores every candidate; each query's two best always reach it. |
| 2.1 | `evidence_strength`, `_EVIDENCE_NOTES` in the per-turn message | strong / partial (top < 0.45, few near it, or a seated subquery) / thin (top < 0.2). |
| 2.2–2.5 | `ANSWER_SHAPE`, `ANSWER_FORMAT` | frame first; quote; locus from the label only; sources against each other. |
| 2.6 | `CHAT_BROAD_EFFORT` (empty = off) | Unmeasured, off. |
| 3.1 | `ingestion/structural.py`; fetchers carry `RawSource.full_text` + `close_spans` | **Changed from the plan**: not the whole work — a per-tier budget (`_STRUCTURAL_TAIL_CHARS`), spent round-robin across key concepts. The database is on a 500 MB plan (308 MB used) and a chunk costs ~29 KB; the whole *Summa* (~10M chars) would not fit. |
| 3.2 | `ingestion/quality.py`, `pipeline.prepare_chunks` | Calibrated by hand: under 0.12 function-word share, 40/40 sampled were junk; 0.13–0.16 still holds real prose. Drops 0.3% of 63, 13% of 66, 13–24% of 41–43. |
| 3.3 | `dedup.deduplicate_editions` (excerpt / foreign edition), `_unique_chunks` near-duplicate suppression | Edition check is within a round, not across rounds. |
| 3.4 | `scripts/backfill_corpus.py` (prose gate, tails, loci, summaries) | |
| 3.5 | `sources/subject.py`; planning, triage, coverage, composition, feedback | Year comes only from fetchers that record one; Exa's date is dropped by its fetcher. Expert 41 not rebuilt. |
| 3.6 | `RERANK_CANDIDATES=75` | Checked: the filtered HNSW scan returns all 300 candidates on 41, 63, 66. |
| 4.1 | migration 036 `corpus_sections`; `ingestion/summaries.py`; builder `_section_index_stage` | |
| 4.2 | `ChatAgent._route_sections`, `SearchService.best_in_spans` for comparison / orientation / open_ended | |
| 4.3 | `diversify` | The best passage's own run is protected — §6 says neighbour expansion is why `held` wins. |
| 4.4, 4.5 | not built | Gated on measurement by the plan itself. |

### What is left to do

Ordered by what the after-run says would move the most. Items marked **$** need
API spend; the rest are free.

- [ ] **Rebuild expert 41 (Beekeeping)** **$** — the test 3.5 names. All three
  `how_to` questions still lose, on a corpus that is two virology papers and an
  1853 manual; subject kind, the recency weight and the paper-share cap only act
  on a build. Then re-run `--class how_to`.
- [ ] **Quotations and loci in prose** — 0/17 answers quote a passage and 1/17
  names a locus, although the labels now carry "I, q. 94, a. 2". The 2.3/2.4
  clauses are being ignored; make them concrete (e.g. "at least one blockquote
  when a passage states the point") and re-measure **$** on five answers first.
- [ ] **Directness** (3.79 v 4.79, unchanged) — 10/17 answers now carry a "my
  sources…" aside, mostly honest gap-marking under the `partial` note, which
  fires on 13/17 answers (any seated subquery makes evidence `partial`). Try
  letting a seat alone not downgrade `strong`, and moving gap notes to one
  closing line; re-measure **$**.
- [ ] **Natural law flipped from a win to a loss** — the closed-book answer gave
  the eternal / natural / human law schema; the tail now holds I-II qq. 90–97,
  so check whether they reached the prompt (`results-after-2026-09-19.json`).
- [ ] **Broad questions still lose (0/2)** — section routing is live on 63/66
  but untested in isolation; compare a run with `SECTION_INDEX_ENABLED=false` **$**.
- [ ] **The chat-only measurement was skipped** (phases 1–2 before the backfill)
  to save spend, so the gain cannot be split between prompt/retrieval and
  corpus.
- [ ] **2.6 `CHAT_BROAD_EFFORT`** — unmeasured, off.
- [ ] **4.4 graph entry / 4.5 agentic second look** — only if the items above
  leave `broad` and `multi_part` losing.
- [ ] **Paid Cohere key** in Fly secrets (ops, 1.9) — production still reranks on
  the 10/min trial key; the fallback is now logged per turn and recorded in
  `answer_audits.reranker`.
- [ ] **Backfill the other experts** — 41, 42, 43 (prose gate would drop 13–24%
  of their chunks; the user approved deletions for 63 and 66 only) and their
  section indexes **$**. `scripts/backfill_corpus.py N --backup-dir … --apply`
  with `CHUNK_SIZE_CHARS=1000`.
- [ ] **Knowledge page**: say what is read closely and what is held
  (`chunk_meta.ingest = "structural"`, build summary `structural`) — not built.
- [ ] **One edition per work across rounds** — `deduplicate_editions` only
  compares sources fetched in the same discovery round.
- [ ] **Exa dates** — the Exa fetcher drops the published date, so 3.5 treats
  Exa pages as undated.
- [ ] **Storage** — the database is at 352 MB of the free plan's 500 MB; every
  standard build now adds ~30 MB of held tail. Upgrade the plan or lower
  `_STRUCTURAL_TAIL_CHARS` before many more builds.
- [ ] **Deploy** — this branch is pushed, not merged. Migrations 035/036 and the
  backfill and persona rewrite are already live in the production database; the
  running API ignores them until this code deploys.

---

## 1. The verdict

The complaint is right, and it is right for a specific reason. Blind, over twelve
questions, the same model with no corpus was preferred on **6**, Peritus on **4**, and
2 split (§2).

**Peritus wins on depth where it holds the text, and loses on completeness, directness
and accuracy everywhere else.** Asked for the best proof of God, the Thomism expert had
Aquinas's article in front of it and walked the First Way step by step, with the *per se
/ per accidens* distinction the closed-book model never reached — the judge preferred it
in both orders. Asked what happens at the moment of death, the same expert wrote 4,750
characters from three passages about happiness, never mentioned judgment, purgatory or
the resurrection, and lost in both orders. The closed-book model has read the whole
*Summa*. The expert holds the first tenth of it.

So the pipeline is not uniformly weak. It has four holes, and real questions fall into
them often — 7 of the 20 audited production answers failed the relevance gate, and 3 of
the 12 here:

1. **The corpus is not what it says it is.** Every long work is cut at 200,000
   characters, from the front (§3.1); a practical subject is answered from a manual of
   1853 (§3.12); 11–41% of the older experts' chunks are not prose (§3.9).
2. **When retrieval is weak the answer gets the *least* context**, and the pass meant to
   recover from that often does not run and does not help when it does (§3.2, §3.3).
3. **Anything but a lookup has no retrieval path.** "Who was the most impactful king?"
   is answered from whichever annals scored highest; a two-part question gets evidence
   for one part (§3.5). The graph — 2,300 nodes per expert, paid for on every build —
   retrieves nothing (§3.4).
4. **The answer does not use what only a corpus can give** — in twelve answers not one
   displayed quotation and not one named locus ("I, q. 2, a. 3"), from one or two
   sources — and when evidence is thin it writes to full length anyway, so it reads like
   a narrower GPT. The persona's routines still leak into a quarter of openings, and
   lost a question outright (§3.6–§3.8).

Only the last of these is a prompt problem. Two earlier rounds
([answer-quality.md](answer-quality.md), [retrieval-quality.md](retrieval-quality.md))
fixed how answers read and how passages are found; what is left is *what the expert
holds* and *what reaches the model when the question is not a lookup*.

---

## 2. The head-to-head

**Setup.** Peritus arm: the production code path on HEAD (`ChatAgent.gather_context`,
then the same compose call `stream_expert_answer` makes), read-only against the
production database. Closed-book arm: the same model (`claude-sonnet-5`), same effort,
same token limit, a one-line system prompt, no corpus. `[n]` markers stripped from the
Peritus answer so the arms cannot be told apart. Judge: `claude-opus-5`, as "a demanding
specialist judging for a curious non-specialist", five axes scored 1–5 plus a preference,
**run in both orders**. Seven of the questions are ones real users asked; five were added
to cover the material each corpus is strongest on.

| # | Expert | Question | Top score | Passages / sources | Gate | Peritus → closed-book (completeness / depth / accuracy) | Verdict (two orders) |
|---|---|---|---|---|---|---|---|
| 1 | Thomism | What is the most tangible proof for God for a modern atheist? | 0.28 | 14 / 3 | pass | 4→3 / 5→3 / 5→3.5 | **Peritus** 2–0 |
| 2 | Thomism | What will happen at the moment of death? | 0.14 | 3 / 2 | fail, no 2nd pass | 2→5 / 3→4 / 3→5 | **closed-book** 2–0 |
| 3 | Thomism | Will we have bodies in the beatific vision? | 0.21 | 7 / 1 | pass | 3.5→4.5 / 5→3.5 / 4.5→3.5 | split |
| 4 | Thomism | What is natural law and how do we come to know it? | 0.79 | 18 / 3 | pass | 5→4 / 5→3.5 / 4→5 | **Peritus** 2–0 |
| 5 | Thomism | Why does Aquinas say God is simple, and what is the strongest objection? | 0.81 | 20 / 4 | pass | 3.5→5 / 4→4 / 3→4 | **closed-book** 2–0 |
| 6 | Anglo-Saxon | Who was the most impactful king during this period and why? | 0.15 | 6 / 2 | fail, 2nd pass ran | 2.5→3.5 / 4→3.5 / 3.5→4 | **closed-book** 2–0 |
| 7 | Anglo-Saxon | What does the genetic evidence say about how many Anglo-Saxons migrated? | 0.83 | 18 / 4 | pass | 3.5→4 / 4→3.5 / 3.5→3.5 | split |
| 8 | Anglo-Saxon | Was the Anglo-Saxon arrival an invasion or a gradual migration? | 0.70 | 22 / 6 | pass | 3.5→4 / 4.5→2.5 / 4→4 | **Peritus** 2–0 |
| 9 | Beekeeping | Why do bees swarm, and how do I stop my hive from swarming? | 0.63 | 10 / 1 | pass | 2→4 / 3→4 / 3→4 | **closed-book** 2–0 |
| 10 | Beekeeping | How do I get a colony through its first winter? | 0.15 | 3 / 2 | fail, 2nd pass ran | 2→5 / 2→4.5 / 3.5→5 | **closed-book** 2–0 |
| 11 | Arist. logic | What is a perfect syllogism and why did Aristotle care? | 0.82 | 16 / 5 | pass | 5→4 / 5→3 / 4→4 | **Peritus** 2–0 |
| 12 | Arist. logic | What is the square of opposition? | 0.87 | 18 / 6 | pass | 4→4 / 4→4 / 4→5 | **closed-book** 2–0 |

**Closed-book 6, Peritus 4, split 2.**

| Axis (mean of 24 verdicts) | Peritus | Closed-book |
|---|---|---|
| Depth and specificity | **4.04** | 3.58 |
| Completeness | 3.38 | **4.17** |
| Directness | 3.88 | **4.75** |
| Accuracy | 3.75 | **4.21** |
| Usefulness | 3.75 | **4.42** |

Peritus leads on one axis — the one retrieval is for — and it is a real lead: on the four
wins the judge's reasons are all the same reason ("actually does the philosophy rather
than describing it"; "gives the argument itself with its defences and limits"; depth 4.5
against 2.5 on the invasion question). Where the text is in hand and reaches the model
in order, the product works and the closed-book model cannot match it.

Every loss has a cause that can be named, and none of them is "the model wrote badly":

| Lost | Why | § |
|---|---|---|
| 2 death | The text is past the 200k cut; three passages in the prompt; 4,751 characters written from them anyway | 3.1, 3.2, 3.6 |
| 5 simplicity | Best retrieval of the run, every seat given to half the question; Plantinga and modal collapse in the corpus and not in the prompt; "the Stanford Encyclopedia article flags it" in the prose; no locus named | 3.5, 3.7 |
| 6 king | An evaluative question answered from six passages of two chronicles; the second pass ran and the floor still starved it; drifted to the ninth century | 3.2, 3.4 |
| 9 swarming | One source, from 1853. The judge: "a period summary of Langstroth rather than current practice" — no supering, no queen cells, no Demaree. (The planner call also failed with a provider 500, so this ran on the one-query fallback plan, as a user's would have.) | 3.12 |
| 10 first winter | Same corpus; gate failed; three passages; varroa "a one-sentence caveat at the end" | 3.12, 3.2 |
| 12 square of opposition | Strong retrieval, lost on precision — and on a paragraph the judge called "a response to an absent interlocutor": *"Working the middle term outward, as with a syllogism, isn't quite the move here"* is the persona's routine, leaking | 3.8 |

The script and every answer, plan, score and judge's note from this run are in
[beating-closed-book/](beating-closed-book/) (`head_to_head.py`,
`results-2026-09-19.json`) — that file is the baseline phase 0 compares against.

**Caveats.** Twelve questions, one run, a model judge. The judge cannot open a citation,
and verifiability — the thing Peritus has and the closed-book arm never will — was
deliberately not scored, because the complaint is about content. Read the table as a
map of where the losses are, not as a precise win rate. Retrieval took 4.4–8.4 s per
question before the first token could be written; nothing in §4 may add a serial model
call to that.

---

## 3. Findings

Ranked by how much of the gap each explains.

### 3.1 The expert holds the first tenth of its own canon

`_MAX_CHARS = 200_000` in `sources/fetchers/gutenberg.py:39`, `sources/canonical.py:137`
and `sources/fetchers/pdf.py:35`; `_PRIMARY_TEXT_CHARS` in
`experts/build/constants.py:281` sets the same ceiling for STANDARD. Read from
`sources.text_chars` and the last chunk of each source, expert 63 (Thomistic Philosophy):

| Work | Held | Stops at | The work |
|---|---|---|---|
| Summa Theologica, Part I | 200,002 chars | q. 10 (eternity), mid-sentence | 119 questions |
| Summa Theologica, I-II | 200,002 | q. 12 (intention), mid-objection | 114 questions — law (qq. 90–108), virtue, sin, grace all absent from this volume |
| Summa Theologica, III | 200,000 | q. 6 | 90 questions |
| Summa Theologica, II-II and Supplement | — | not held | justice, faith, hope, charity; death, resurrection, the last things |
| Summa contra Gentiles | 200,000 | Book I, ch. 34 | four books |
| Nicomachean Ethics | 200,000 | Book IV, mid-sentence, *after* an editor's introduction | ten books — justice, prudence, friendship, contemplation absent |

`sources/sections.py` exists to keep the sections a plan asked for instead of a prefix.
On this build it selected nothing: all five volumes are prefixes. The same cut is on
expert 66 (the Anglo-Saxon Chronicle stops at A.D. 945, Bede in Book II).

This is the largest single cause of "no better than GPT". In the head-to-head the judge
listed what the closed-book answer had that Peritus lacked on the beatific-vision
question: "ST Suppl. qq. 75–86 and ScG IV.79" — both inside works the expert nominally
holds and both past the cut. A frontier model has the canon of most subjects in memory.
An expert that holds a tenth of one book of it cannot out-answer that model on the other
nine tenths, and no retrieval change will help.

**The ceiling is priced on a false assumption.** The comment beside it says ingest costs
about $0.27 per 100,000 characters. Embedding is about $0.003 of that
(text-embedding-3-large, ~25k tokens). Nearly all the rest is per-chunk model work: the
contextual note (`ingestion/contextualizer.py`, one fast-model call per five chunks with
a 3,000-character window) and graph extraction, which `GRAPH_MAX_CHUNKS_PER_SOURCE = 80`
already caps per source. A canonical work is exactly the text that least needs a
model-written note, because its structure *is* its context: "Summa Theologica › Part I ›
Question 2 › Article 3" says more than a generated sentence, and `chunk_meta.section`
already carries the heading on 100% of chunks.

### 3.2 Weak retrieval gets the least context

`RELEVANCE_FLOOR = 0.15` (`core/config.py:260`) is an absolute Cohere score.
`apply_relevance_floor` (`chat/agent.py:645`) drops everything under it, keeping at least
`RELEVANCE_MIN_PASSAGES = 3`. Neighbour anchors are also drawn only from passages above
the floor (`agent.py:817`). So the weaker the retrieval, the smaller the prompt:

| Audited answer | Top score | Retrieved | In context | Sources | Answer |
|---|---|---|---|---|---|
| What will happen at the moment of death? | 0.14 | 10 | **3** | 1 | 5,001 chars |
| Who was the most impactful king…? | 0.16 | 10 | **6** (3 + 3 neighbours) | 2 | 4,012 chars |
| What is potency (three runs) | 0.10–0.12 | 15 | 3–11 | 3–7 | ~3,100 chars |
| Will we have bodies in the beatific vision? | 0.18 | 12 | 6 | 1 | 5,288 chars |

The floor was calibrated on seven answers (cited passages averaged 0.31, uncited 0.22)
and treats the score as comparable across questions. It is not. Top scores across these
20 answers run from 0.10 to 0.86, and the low ones are not all corpus gaps: an
*evaluative* question has no passage that "answers" it, so every passage scores low. For
the king question the reranker returned Æthelfrith at 0.156 and then Edward the Elder,
Egbert's conquest of Mercia, Athelstan and Edmund at 0.08–0.10. All were relevant; all
but three were dropped; and two of the three neighbours that replaced them were a page of
textual apparatus and a passage *in Old English* (§3.9). The answer names Æthelfrith and
Ethelbert as the two candidates for "most impactful king" because those are the kings in
the three annals that survived. Alfred is not mentioned.

Across all 20: 10.0 passages in context on average, 5.4 cited, from **2.5 sources, of
which 1.4 are cited** — for experts built from 18–33 sources.

### 3.3 The recovery pass mostly does not run

The second pass runs only `if coverage_satisfied is False and plan.fallback_queries`
(`agent.py:786`). `fallback_queries` is not in the plan tool's `required` list
(`agent.py:189`), and the fast model usually leaves it out: of the last 14 audited plans,
**one** carried fallback queries. Four of those 14 failed the gate; three got no second
pass — including both production answers on v21 today (the king question and the B67
one). In the head-to-head run the planner returned them on 9 of 12 calls, so it is
intermittent, which is worse than absent: the behaviour of the system on its hardest
questions depends on whether an optional field happened to be filled in.

And when the pass does run it is not enough. It ran on two of the run's three gate
failures (questions 6 and 10); both still reached the model with six and three passages,
because the same absolute floor is applied to what the second pass finds (§3.2). The
planner also has no retry: one provider 500 (question 9) and the turn runs on the
one-query fallback plan.

The earlier LLM coverage judge was removed for good reasons (retrieval-quality R6). What
replaced it is a gate that fires correctly and a remedy that is usually empty.

### 3.4 Broad questions have no retrieval path, and the graph retrieves nothing

Every question, whatever its type, gets the same thing: the top-k chunks by hybrid search
and rerank, plus neighbours. That is the right shape for "what does Aquinas say about X"
and the wrong one for "who mattered most", "how did this change over the period", "what
are the main positions on Y". Those need the *corpus seen from above*, and nothing in the
system holds that view:

- There are no summaries at any level — section, source or concept.
- `GraphRetriever.expand` (`graph/retriever.py:93`) adds `About:` labels and dispute
  points to passages already retrieved. It never brings a passage in. The file's own
  comment says "no eval has shown the list changes an answer". Expert 63 carries 2,345
  nodes, 1,467 claims and 3,334 edges that play no part in finding evidence.
- The graph could not do much yet if asked. On expert 66, of 1,008 concepts only 67 touch
  two or more sources and 10 touch three; "Anglo-Saxon settlement of Britain",
  "Anglo-Saxon settlement", "Saxon settlement of Britain" and "Anglo-Saxon migration" are
  four separate nodes. It mostly mirrors chunk locality.
- The planner already classifies the question (`question_type`), and the label is used
  only to shape prose. Retrieval never sees it.

### 3.5 One or two sources per answer

Nothing in `batch_search` or the context assembly asks for breadth. RRF-sum rewards a
chunk several subqueries found; rerank scores chunks independently; neighbour expansion
then adds up to 12 more chunks *from the sources already winning*. The measured result is
§3.2's 1.4 cited sources per answer. The modern scholarship in expert 66 — the genome
papers, the isotope studies, the Cambridge chapter on early settlement — did not appear in
the king answer at all; the keyword arm matches "king" in every annal of the Chronicle.

**A two-part question gets evidence for one part.** The head-to-head asked "Why does
Aquinas say God is simple, and what is the strongest objection to that?" Retrieval was
the strongest of the run — top score 0.81, 20 passages, 4 sources — and Peritus lost in
both orders. The judge's reasons: no Plantinga, no modal collapse, no analogical
predication, no named critic. The corpus holds all of them (13 chunks naming Plantinga,
3 on modal collapse, 18 on analogy). None reached the prompt. The planner wrote two
subqueries for the objection, but fusion and a single rerank against the whole question
gave every seat to the first half, in four contiguous runs — ten of the twenty seats were
neighbours of passages already winning. A subquery has no seat of its own, so the part of
a question that scores second gets nothing.

The corpus also holds the same text several times, which spends context slots on
repeats: for expert 63, *De ente et essentia* twice (two hosts), Summa I q. 3 four times
(the Gutenberg volume, newadvent, archive.org, and quoted through SEP), I-II q. 93 twice;
for expert 66, Bede twice, one of them an Old English edition.

### 3.6 Thin evidence produces a long, narrow answer

The contract has two settings: answer from the passages, or — if they "hold nothing
relevant" — say so in one sentence and stop (`grounding.py:76`). Most weak retrievals are
neither. Three tangential passages are not nothing, so the model answers, and nothing
tells it the evidence is thin, so it writes to the usual length. The death answer is
5,001 characters from three passages of one article about whether the body is needed for
happiness; the judge's notes on it: "drifts into a general treatise on happiness",
"omits judgment and the four last things altogether", and an inversion of Aquinas's
position on the separated soul that came from stretching a passage past what it says.

Length does not scale with evidence, and breadth is forbidden where the corpus is
silent. The closed-book model has neither constraint — so on exactly the questions where
the corpus is thin, Peritus is the *narrower* of the two, and the only thing marking it
out as grounded is a bracketed number.

This is not an argument for relaxing the tiered grounding model decided in
answer-quality.md. It is that the model needs to be told how much evidence it has, and
that "what a full answer to this question covers" is already on the list of things that
are its to supply (`grounding.py:49`).

### 3.7 The answer doesn't show what only a corpus can

What a reader cannot get from a closed-book model is *the text*: the sentence Aquinas
wrote, where it is, and a link to check it. Today:

- `SearchResult.citation` is the source title and nothing else
  (`search/domain.py:25`). Every passage of the Prima Pars is labelled "Summa Theologica,
  Part I (Prima Pars) — From the Complete American Edition". The section heading is in
  `chunk_meta.section` and the article number is in the contextual note; neither reaches
  the label, so the model cannot write "I, q. 2, a. 3" with confidence and the reader's
  citation panel cannot show it. In the head-to-head the judge marked Peritus down for
  "no citations given (ST I-II q.4 aa.5-6…) though the material is clearly drawn from
  them" — with markers stripped for blinding, nothing in the prose located the claim.
- Across the twelve head-to-head answers Peritus named a locus in its prose **zero**
  times. The closed-book arm did eight times ("ST I-II, q. 94, a. 2") — from memory,
  unverifiable, and it still reads as the better-sourced answer.
- `ANSWER_FORMAT` permits a blockquote "only for a direct quotation" and nothing asks for
  one: 0 of 12 answers display a passage. Short inline quotations do appear, in four of
  the twelve.
- Nothing encourages setting sources against each other, which is the thing a
  multi-source expert exists to do — and see §3.5, there is usually one source to hand.

### 3.8 The persona still writes the opening

`build_system_prompt` puts the persona last, 3,300–3,400 characters of it, after the
contract, the shape and the format — the position that weighs most. Expert 66's stored
persona says: *You open almost every explanation the same way: "Let's see what the
chronicler says, then what the ground says, then what the genome says"*. The production
answer to the king question, on v21 with the "never announce it" guard in place, opens:
"Let's see what the chronicler says, then weigh the candidates…". Expert 63 on HEAD
today: "Let me walk it up the same ladder Aquinas builds it on, rung by rung".

A guard sentence does not beat three thousand characters of instruction placed after it.
The same answers break other format rules the prompt states plainly: two of four recent
stored answers open with a `##` heading, one ends on a summary section ("The Whole
Movement, in One Line"), paragraphs run to eight sentences.

Counted over the twelve head-to-head answers, on HEAD:

| Check | Answers |
|---|---|
| First line is a `##` heading (the prompt: "never a heading") | 4 of 12 |
| Persona routine in the opening ("Let's see what the genome says…", "rung by rung") | 3 of 12, and mid-answer in two more |
| Talks about its sources ("in these sources", "the passages here don't give…", "the Stanford Encyclopedia article flags…") | 4 of 12 |
| "My sources don't cover…" aside | 3 of 12 |
| A displayed quotation from a passage | **0 of 12** |
| A locus named in the prose | **0 of 12** (closed-book: 3 of 12) |

This costs verdicts, not just polish: directness is the widest gap in §2 (3.88 against
4.75), and question 12 was lost on a leaked routine.

### 3.9 What is in the chunks

A function-word count over every chunk (share of tokens that are common English words;
under 15% is almost never prose — 12 of 15 sampled were junk, the rest dense technical
text) flags:

| Expert | Built | Chunks | Flagged |
|---|---|---|---|
| 41 Beekeeping | 23 Aug | 525 | 41% — archive.org navigation ("Software Internet Arcade Console Living Room"), reference lists |
| 42 Production ML | 23 Aug | 560 | 31% — GitHub repo metadata, bibliographies |
| 43 Aristotelian logic | 23 Aug | 830 | 11% |
| 66 Anglo-Saxon settlement | 19 Sep | 1,868 | 16% — 230 chunks of Old English and Latin from two editions of Bede, OCR'd apparatus, genome sample-ID lists |
| 63 Thomism | 18 Sep | 1,954 | 0.5% |

Experts 41–43 predate the chunk hygiene of retrieval-quality R3 and were never rebuilt.
Expert 66 shows the gap R3 left: nothing checks that a chunk is in the language the
expert answers in, and an OCR'd scholarly edition interleaves original, translation and
apparatus. These chunks are embedded, keyword-indexed, contextualised (paid for), and
retrieved — the neighbour of the top hit on the king question was one.

### 3.10 The reranker sees the least it could

`batch_search` calls `rerank(question, [r.text for r in merged])`
(`search/service.py:132`): the bare chunk, cut at 1,500 characters, against the bare
question. The contextual note — paid for per chunk, embedded, keyword-indexed, shown to
the answering model — is withheld from the one component that decides what the answering
model sees. A chunk from the middle of an article carries no heading; "What will happen at
the moment of death?" carries no hint that the corpus is Aquinas.

And production reranks on a Cohere **trial** key (10 calls a minute; not licensed for
production). Past the limit `rerank` falls back silently to windowed fast-model scoring,
whose scores are on a different scale, and the 0.15 floor is applied to both. Nothing
records which reranker scored an answer, so the audit data the floor is calibrated from
may already mix the two.

### 3.11 Nothing measures the complaint

`eval/retrieval.py` measures recall on questions *generated from chunk text* — saturated
(1.000 on expert 63) and blind to §3.1 by construction: a question can only be generated
from text the expert holds. `eval/helpfulness.py` scored the old source-tour answers
0.83–0.90. No harness asks the only question the user is asking: is this better than the
model alone? §2 is the first time it has been measured.

### 3.12 For a practical subject, the corpus is a century old

Expert 41 (Beekeeping, LITE, built 23 August) by share of chunks: two virology papers on
deformed wing virus, **61%**; Langstroth's manual of 1853, 12%; three copies of the
*ABC and XYZ of Bee Culture* (1877 onward), 11%. There is no modern practical guide in
it. Both how-to questions in §2 were answered from Langstroth and lost 0–2, on
completeness 2 against 4 and 5: no brood-nest congestion, no supering, no queen-cell
inspection, no varroa thresholds, no moisture control — and a section on why fixed-comb
hives are bad, for a reader who already owns a hive.

This build predates the source-selection work, so treat it as a lead rather than a
measurement of today's discovery. But the bias behind it is structural and still there:
what can be fetched whole and free is public-domain books (before 1927) and open-access
research papers, and both rank as `primary`. For a canon — Aquinas, Aristotle, Bede —
that is the right corpus. For a craft or a fast-moving technical field it is the wrong
one, and the closed-book model, trained on the modern web, wins by default. What counts
as authoritative depends on the kind of subject, and nothing in planning, triage or the
coverage targets asks what kind this one is.

---

## 4. The plan

Five phases. Phase 0 makes the complaint a number. Phase 1 is bugs and calibration — days,
no rebuild. Phases 2 and 3 are where most of the gap closes. Phase 4 is the structural
piece and is sized by what phases 1–3 leave behind.

### Phase 0 — Make "better than closed-book" a number · 1 day

| # | Change | Where |
|---|---|---|
| 0.1 | Promote the head-to-head script to `python -m peritus.eval.headtohead <expert> [--set …]`. Same model and effort both arms, `[n]` stripped for blinding, judge on a stronger model, **both orders**, a verdict counts only when the two orders agree. Read-only (`gather_context` + compose; no conversation or audit rows). | new `eval/headtohead.py` |
| 0.2 | A question set per expert, **labelled by class**: `held` (the corpus certainly holds it), `edge` (the named work holds it, past the cut), `broad` (synthesis, evaluation, overview), `multi_part`, `how_to`, `fact`, `out_of_scope`. Write them from the subject, never from chunk text. 12–15 per expert; seed with the real questions in `answer_audits`. | `eval/golden/headtohead/<slug>.json` |
| 0.3 | Report win rate per class, per-axis deltas, and each question's retrieval diagnostics beside its verdict (gate, top score, passages, sources, second pass) — the join is what makes a loss diagnosable. | same |
| 0.4 | Deterministic answer checks, free and CI-able, in `eval/metrics.py`: first line is a heading; persona-script overlap (longest n-gram shared with `persona_style`); summary/conclusion final section; "my sources" asides; quotation count; locus count; distinct sources cited. | `eval/metrics.py` |
| 0.5 | Record which reranker scored each answer. | `answer_audits.reranker` (migration), `SearchResponse`, `chat/audit_trail.py` |

**Gate for every later phase:** before/after on this set. About $3 and 20 minutes a run.
The target is not "win everything": it is **win `held`; at least tie `edge`, `broad`,
`multi_part` and `how_to`; never lose on accuracy**. Today: `held` 4 wins of 6,
everything else 0 of 6.

### Phase 1 — Bugs and calibration · 1–2 days, no rebuild

| # | Change | Where | Fixes |
|---|---|---|---|
| 1.1 | `fallback_queries` and `standalone_question` into the plan tool's `required`. One retry of the planner on a 5xx or timeout before falling back to the one-query plan. | `chat/agent.py:189`, `ChatAgent._plan` | §3.3 |
| 1.2 | Relevance floor relative to the question: keep a passage when `score ≥ max(0.04, 0.5 × top_score)`; minimum kept scales with the tier (`max(3, max_context_passages // 2)`), not a flat 3. Re-derive both constants from `answer_audit_passages` (cited vs uncited, per answer, normalised by that answer's top score). | `apply_relevance_floor`, `core/config.py` | §3.2 |
| 1.3 | Separate "is retrieval weak" from "what to keep". Second pass when `top_score < 0.25` or fewer than 5 passages clear the relative floor. | `ChatAgent.retrieve` step 4 | §3.2, §3.3 |
| 1.4 | Neighbour anchors by rank, not by floor: the top `NEIGHBOUR_ANCHORS` retrieved passages always bring their neighbours. Drop a neighbour that fails the chunk-quality check (3.2). | `agent.py:817` | §3.2 |
| 1.5 | Rerank on `context_text + "\n" + text`, and on the standalone question prefixed with the expert's topic. Measure with `eval/retrieval.py run` before and after — it is one line each and either could lose. | `search/service.py:82,132` | §3.10 |
| 1.6 | Citation label = cleaned title + section when `chunk_meta.section` is a real heading (not empty, not "Full Text"): `Summa Theologica, Part I — The Existence of God`. Same string to the model, the SSE event, and the citation panel. Clean the title on the way (`PDFAQUINAS ON DIVINE SIMPLICITY - Archive.org` is a label the model was shown 11 times in question 5). Stored sections are headings, not numbers; the numbered locus (`q. 2, a. 3`) comes with the heading path in 3.1 (`chunk_meta.locus`), so existing experts get the heading and rebuilt ones the number. | `search/domain.py:25`, `ingestion/chunker.py` | §3.7 |
| 1.7 | Persona: move the WHO YOU ARE block **above** `ANSWER_SHAPE`/`ANSWER_FORMAT` so the rules about how an answer opens come last; cap at ~1,500 characters; one-off script over stored personas that removes sentences scripting an opening or a routine ("You open…", "You always begin…", quoted catchphrases) — regenerate where that leaves too little. The cached prefix re-primes once per expert. | `chat/grounding.py:227`, `experts/build/persona.py`, `scripts/` | §3.8 |
| 1.8 | **A seat for every part of the question.** `batch_search` keeps each subquery's own hit list; after the global rerank, any subquery with no passage in the result gets its best two seated, exempt from the floor. Neighbours fill what is left of the cap *after* those seats, not before. | `search/service.batch_search`, `ChatAgent.retrieve` | §3.5 |
| 1.9 | A paid Cohere key in Fly secrets; a warning-level log and a counter when the fallback reranker scores a chat turn. | ops, `infrastructure/reranker.py` | §3.10 |

Expected: `multi_part` stops losing, and `broad` and `edge` stop losing on *narrowness
caused by a starved prompt*. They will still lose where the corpus is absent (phase 3)
or the question needs a view from above (phase 4).

One dependency: 1.2 hands the model *more weak passages* on a question like the death
one (nine tangential passages instead of three). On its own that invites more drift, not
less. Ship it with 2.1, so a prompt that is fuller is also told it is thin.

### Phase 2 — Answers that use the evidence they have · 2–3 days, prompt and a little code

| # | Change | Where |
|---|---|---|
| 2.1 | **Tell the model how strong the evidence is.** Compute `strong / partial / thin` from the rerank scores and passage count, and say it in the per-turn message (after the cache breakpoint, so nothing cached changes). `strong`: as today. `partial`: answer what the passages establish; name, in one marked sentence each, the parts of a full answer they do not reach. `thin`: a short answer — what little the sources say, cited; then a brief, plainly marked general-background paragraph so the asker is not left with less than a search would give. Length follows evidence. | `build_user_message`, `RetrievedContext` |
| 2.2 | **The frame comes from the expert, the claims from the passages.** One clause in `ANSWER_SHAPE`: decide what a complete answer to *this* question covers before looking at what was retrieved; then fill each part from the passages or mark it as not covered. This is already "yours to supply" under the tiered contract; today nothing asks for it, and the retrieval set silently becomes the outline. | `chat/grounding.py` |
| 2.3 | **Quote.** Where a passage states the point exactly or memorably, quote it — a sentence or two, in a blockquote, cited. At most two or three per answer. This is the single most visible thing a closed-book model cannot do honestly. | `ANSWER_FORMAT` |
| 2.4 | **Name the locus in the prose** when the label carries one (1.6): "in the question on the existence of God" today, "I, q. 2, a. 3" once 3.1 stores numbered loci. Only from the label — a locus recalled from memory is an invented attribution under the contract. | `ANSWER_SHAPE` |
| 2.5 | **Set sources against each other** when the context holds more than one on the point — agreement across kinds of evidence is worth a clause; so is a primary text against its modern reading. Organised by subject still; this is not source narration. | `ANSWER_SHAPE` |
| 2.6 | Experiment, measured on the `broad` class only: `CHAT_EFFORT=medium` for `comparison`, `orientation` and `open_ended` questions. It was measured as no help on an explanation question; synthesis is a different job and is unmeasured. | `composition_params` |

Every prompt clause added here gets echoed if it is quotable (the last round found "the
objection a thoughtful person would raise" coming back as a heading). Write them as
conditions, test on five answers by hand before the harness.

### Phase 3 — Whole works and a clean corpus · 3–5 days plus rebuilds

| # | Change | Where |
|---|---|---|
| 3.1 | **Two-tier ingestion for long canonical works.** The sections the plan asked for (or, failing a match, the opening) are ingested as today — notes, graph — up to the existing ceiling. **The rest of the work is ingested embed-only**: chunked, a deterministic structural note built from the heading path (`work › part › question › article`), embedded, keyword-indexed, no contextualiser call, no graph extraction. At ~$0.003 per 100k characters the whole *Summa* (~10M characters, ~12k chunks) costs well under a dollar. Mark these chunks (`chunk_meta.ingest = "structural"`) so the build summary and the Knowledge page can say what was read closely and what is merely held. | `sources/fetchers/gutenberg.py`, `sources/canonical.py`, `sources/sections.py`, `ingestion/`, `experts/build/constants.py` |
| 3.2 | **Chunk quality gate at ingest**, before anything is paid for: function-word share (the §3.9 measure, threshold calibrated on a labelled sample), language check against the expert's language, reference-list and navigation patterns. Dropped chunks counted in the build summary by reason. | `ingestion/chunker.clean_text` |
| 3.3 | **One edition per work.** At triage, candidates that resolve to the same work (the canonical resolver already identifies works) keep the best edition: prefer a plain translation over an OCR'd scholarly edition, a complete text over an excerpt of a text already held. At retrieval, suppress near-duplicate chunks before the context cap (the 5-shingle containment in `eval/retrieval.py` already exists). | `sources/triage.py`, `sources/canonical.py`, `chat/agent._unique_chunks` |
| 3.4 | Re-run hygiene over experts 41–43 from stored chunks, or rebuild them. | `scripts/` |
| 3.5 | **Ask what kind of subject this is, and let it set what "authoritative" means.** The research brief names the subject's kind — a *canon* (texts are the subject), a *practice* (a craft, a how-to field), a *research front* — once, on the plan model. For a practice or a research front: a coverage target for current practitioner material (extension services, professional bodies, standard handbooks, recent reviews), a recency weight in triage, and a cap on the share of chunks any one narrow paper may take (two virology papers are 61% of the beekeeping expert). A pre-1927 manual stays welcome as history; it may not be the only thing that answers "how do I". Rebuild expert 41 as the test. | `experts/build/` planning, `sources/triage.py`, `experts/coverage.py`, `experts/composition.py` |
| 3.6 | With a corpus several times larger, raise `RERANK_CANDIDATES` 50 → 75 and re-measure; check the HNSW iterative-scan settings still return `candidate_k` rows per expert. | `core/config.py`, `search/service.py` |

Rebuild expert 63 after 3.1–3.3 and expert 41 after 3.5. **This is the phase that should
flip the `edge` and `how_to` classes** — the death and wintering questions lose today
because the text that answers them is not in the corpus.

### Phase 4 — A retrieval path for broad questions · 1–2 weeks, sized by what is left

The principle: **summaries find, passages prove.** Generated text never becomes a
citable passage; it routes to the real ones.

| # | Change | Notes |
|---|---|---|
| 4.1 | **Section summaries as a routing index.** At build, one fast-model call (batched) per section — a run of chunks sharing `chunk_meta.section` within a source — writing ~120 words on what the section establishes: the names, dates, positions and arguments in it. Stored with an embedding in a new `corpus_sections` table (`source_id`, `section`, `seq_start`, `seq_end`, `summary`, `embedding`). Expert 63 has roughly 300 sections: well under a dollar on the Batch API. Embed-only tails (3.1) get summaries too — this is how a question finds its way into a work nobody contextualised. | new migration, `ingestion/`, `experts/build/` |
| 4.2 | **Route by question type.** The planner's `question_type` finally reaches retrieval. `specific_fact`: today's path, tighter k. `explanation`: today's path. `comparison`, `orientation`, `open_ended`: search `corpus_sections` with the question and subqueries, take the top sections **across distinct sources**, pull each one's best two or three chunks by similarity to the question, and merge them into the candidate set with a guaranteed seat each — the reranker orders them but cannot drop a whole section. | `ChatAgent.retrieve`, `SearchService` |
| 4.3 | **Source diversity in the context.** No source takes more than half the seats while another source has a passage above the relative floor; neighbours count toward their source's share. | `chat/agent.py` step 5–6 |
| 4.4 | **Concept entry through the graph — gated on a measurement.** Node embeddings already exist (`expert_nodes.embedding`). For a broad question, match the question to concept nodes, take the claims `about` them with the most cross-source `supports`, and seat their chunks as in 4.2. Do this only if 4.1–4.3 leave `broad` losing *and* entity resolution is tightened first (the optional 0.85–0.90 merge step from retrieval-quality R5 was never built; §3.4 shows four spellings of the expert's own topic as four nodes). Otherwise this adds a second router over a fragmented index. | `graph/retriever.py`, `graph/resolution.py` |
| 4.5 | **A second look, by the answering model — last, and only if needed.** One `search_corpus` tool call the model may make when it finds, mid-frame, a part of the answer with no passage. It is how current agentic retrieval works and it is the most robust fix for multi-part questions; it also adds a round trip before the first token. Try it only on `partial` evidence (2.1), and only after the cheaper routes are measured. | `chat/streaming.py`, `chat/agent.py` |

### Phase 5 — Thin answers grow the corpus · small, after phase 2

Every `thin` or `partial` answer (2.1) is a statement that the corpus lacks something a
user wanted. Record the question and the uncovered parts; surface them as gaps on the
Knowledge page, where a gap is already the place an addition starts
([expert-brain-interactive.md](expert-brain-interactive.md)). The losing case becomes the
expert's to-do list instead of a worse answer.

---

## 5. Order, cost, and what each phase should move

| Phase | Work | Rebuild | Per-turn cost / latency | Class it should move |
|---|---|---|---|---|
| 0 | 1 day | no | — | makes the rest measurable |
| 1 | 1–2 days | no | ≈ 0; second pass runs more often (+1 embedding batch, +1 rerank on weak turns) | `multi_part`; `broad`, `edge`: fewer starved prompts; openings and directness everywhere |
| 2 | 2–3 days | no | ≈ 0 (a few hundred prompt tokens, re-primed cache) | all: quotes and loci; `edge`/`broad`: honest, shorter, framed |
| 3 | 3–5 days | yes | retrieval over a larger index, no new calls | `edge` → `held`; `how_to` |
| 4.1–4.3 | ~1 week | yes (summaries) | +1 vector query on broad questions | `broad` |
| 4.4–4.5 | only if measured need | — | 4.5 adds a round trip | `broad`, multi-part |

Do 0 → 1 → 2 in that order and re-run the head-to-head after each; 3 can start beside 2
since it is build-side. Decide phase 4's scope from the numbers, not from this document.

## 6. What not to change

- **Numbered passages and `[n]`.** Citations, the passage reader, the audit trail and the
  SSE `sources` event all resolve a marker to one chunk. Summaries route; they are never
  numbered. Neighbours stay separate passages.
- **The tiered grounding model.** Phase 2 works inside it. The fix for narrow answers is
  telling the model how much evidence it has and giving it more, not letting it assert
  from memory uncited.
- **The prompt-cache layout.** Everything per-turn (evidence strength, the plan) stays in
  the final message. 1.7 changes the system prompt once.
- **The scannable Markdown format** and the absence of a grounding-percentage display.
- **`CHAT_EFFORT=low` for explanation questions** — measured. 2.6 tests a different class.
- **Neighbour expansion.** It is why the `held` class wins: the judge's praise for the
  First Way answer is praise for seven consecutive chunks arriving in order.
- **The `retrieval.py` golden sets** stay useful as a regression check on recall. They
  cannot see a missing corpus, so they are not the measure of this plan.
