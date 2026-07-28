# Peritus — Positioning

**Status:** strategy proposal, July 2026. Written to be argued with, not agreed with.
**Author's note on method:** every claim about Peritus below was checked against the code in this
repository. Every claim about a competitor came from research done for this document (sources at the
end), not from memory. Where the research contradicts the thesis I was given, I say so.

---

## 0. The headline finding, first

I was asked to position Peritus as **auditable evidence synthesis**: lead with the screening ledger,
the rejected-sources record, and contradiction detection, aimed at researchers doing systematic
literature review.

**The research does not support that positioning as stated.** The specific differentiators in the
brief are, as of mid-2026, *table stakes in this category*:

- **Elicit** already records an exclusion reason **and a supporting quote** for every screening
  decision, exports a PRISMA flow diagram alongside search strategies and included-study
  characteristics, screens up to 40,000 records per review, and publishes accuracy figures
  (97% sensitivity / 93% specificity on abstract screening; 96% extraction accuracy at a 1.0%
  hallucination rate). It is explicitly sold as "reproducible, traceable, and auditable at every
  step," positions its AI as a second reviewer alongside two humans, and costs $49/month.
- **DistillerSR** and **Paperguide** likewise maintain audit trails that map to the PRISMA-trAIce
  checklist for disclosing AI use.
- **Covidence** — the Cochrane-endorsed incumbent — ships the EPPI-Centre RCT classifier
  (>99.5% sensitivity) and is deliberately *conservative*: auto-exclusion is off by default and
  restricted to health-and-medical reviews.
- **Scite** already does contradiction detection at citation-network scale, labelling whether later
  papers support or contrast a claim, for $12–20/month.
- **Consensus** ships a "Consensus Meter" showing agreement and disagreement across studies, at
  $8.99/month.

So: "we keep an auditable record of screening decisions and we notice when sources disagree" is not a
wedge. It is the price of entry, and Peritus is behind on it — see §7.

**There is still a real and defensible wedge in the vicinity, and it is a different one.** Every tool
above starts from a *bibliographic database export*: a RIS/CSV of records from PubMed, Embase,
Scopus, or an academic index (Elicit: OpenAlex + Semantic Scholar + PubMed, ~125M papers). None of
them searches the open web, PDFs behind organisational sites, video, or practitioner discussion.

That is precisely the material Peritus's nine fetchers were built to find. And it is precisely the
part of evidence synthesis that is still done by hand: a 2026 analysis of 100 systematic reviews
found grey-literature searching relied on hand-searching (58%), organisation and government websites
(42%), and Google Scholar (39%), concluding that "automation, structured databases, and consistent
appraisal tools are rarely used" and that there is "no universally accepted guidance for identifying
or appraising gray literature."

**The revised positioning: Peritus is a defensible search-and-appraisal record for the sources that
your database export misses.** Not a screening tool. A *discovery and appraisal* tool for grey
literature, which produces the paper trail that grey-literature searching currently has no way to
produce.

The rest of this document argues that case and states what would have to be true for it to work.

---

## 1. Who the user is, and what their week actually looks like

**Primary:** an early-career researcher, research fellow, information specialist, or policy analyst
running a **scoping review, rapid review, or evidence map** where grey literature genuinely matters.
Concretely: public health, health services research, education, social policy, environmental science,
implementation science, software-engineering research. Not a Cochrane intervention review of RCTs —
that person is already served by Covidence and should stay there.

**Their week today, for the grey-literature half of the search:**

| Step | What they actually do | How long |
|---|---|---|
| Define the search | Write a protocol; register on PROSPERO or OSF | Days |
| Database search | Structured Boolean queries against PubMed/Embase/Scopus; export RIS | Hours; well tooled |
| Screen the export | Rayyan or Covidence, two reviewers, blinded | Weeks; well tooled |
| **Grey-literature search** | **Google, Google Scholar page 1–10, a list of 15–40 organisation websites checked by hand, conference proceedings, preprint servers, sometimes YouTube for conference talks** | **Days to weeks; effectively untooled** |
| **Appraise the grey items** | **Ad-hoc. AACODS checklist if they're diligent; a judgement call if not** | **Untooled** |
| **Report the grey search** | **A paragraph in the methods that says, roughly, "we also searched Google and relevant organisational websites." Reviewers push back. There is no flow diagram for this half.** | **The pain** |
| Extract, synthesise, write | Spreadsheets, NVivo, prose | Weeks |

The last three rows are where a reviewer gets hurt. **They are the rows where nobody can show their
work.** A peer reviewer asking "how did you decide which of the 400 Google results to include?" has no
good answer available, because no tool ever produced one.

**Secondary (later, not now):** an evidence-synthesis unit inside a government agency, charity, or
consultancy — same job, budget from a grant or a contract, and an even stronger need to be defensible
because their output is used to justify spending. Reachable only after there is a published review
that used the tool.

**Explicitly not the user this year:** legal, pharma medical affairs, regulated enterprise. Bigger
budgets, procurement cycles a solo developer cannot survive, and a compliance bar Peritus does not
meet. Revisit when there is a company, not a person.

---

## 2. The job to be done

> *"I have to be able to defend how this body of evidence was assembled — including the half of it
> that didn't come out of a database — to a peer reviewer who is looking for a reason to reject."*

Note what this is **not**:

- It is not "answer my question." ChatGPT, Perplexity, Consensus and NotebookLM all do that, mostly
  free, and Peritus will never win there.
- It is not "screen my 3,000 records." Elicit and Covidence do that at a scale and accuracy Peritus
  cannot approach (see §7 — Peritus's pro tier handles ~40 sources, not 40,000).
- It is "**produce a record of a search I could not otherwise document.**"

The buying trigger is a specific, recurring humiliation: a methods section that has to say *"we also
searched relevant websites"* and a peer reviewer who circles it.

---

## 3. What Peritus actually has (verified against the code)

Facts, with file references, so nothing on the marketing site is invented:

| Capability | Where | Reality check |
|---|---|---|
| 9 heterogeneous fetchers — Wikipedia, Gutenberg, arXiv, PDF (Mistral OCR), YouTube transcripts, Exa neural search, general web, Reddit, curated thought-leaders | `sources/fetchers/` | Real. This is the asset. |
| Two-phase discovery: cheap `search()` over-fetches ~3× budget, LLM triage ranks candidates, only winners pay full retrieval | `sources/triage.py`, `sources/fetchers/base.py` | Real. Triage scores are computed but **not persisted** — see §7. |
| Per-source quality + relevance scores against a versioned rubric (`v3-concepts-q5r6`), thresholds q≥5 and r≥6 | `sources/validator.py` | Real. Single LLM pass at Haiku. No second reviewer, no agreement statistic. |
| Drop reason recorded for every rejected source | `sources` table, `drop_reason` | Real. Written on every build. |
| Validator model and rubric version stamped per source | migration `009_validation_provenance.sql` | Real. |
| Discovery provenance: `plan`, `snowball`, or `gapfill:<concept>` | migration `012_source_coverage.sql`, `experts/builder.py` | **Real and genuinely unusual.** No competitor records *why a given search was run*. |
| Concept coverage per source, matched back to a canonical concept list (invented tags are discarded) | `sources/validator.py::_match_concepts` | Real. |
| Coverage gap-fill: corpus is checked against the planned key concepts and uncovered concepts trigger a second search round | `experts/builder.py` | **Real and genuinely unusual.** This is a saturation argument, computed. |
| Citation snowballing from arXiv references via Semantic Scholar | `experts/builder.py::_snowball_citations` | Real, arXiv-only. |
| `contradicts` edges in the concept graph, prioritised during retrieval and surfaced in chat | `graph/extractor.py`, `graph/retriever.py`, `cli/src/tui/screens/chat.rs` | Real, but LLM-asserted at concept level from chunk batches at Haiku. Not claim-level, not effect-size-aware, not verified. |
| Grounded chat with numbered citations resolved down to passages actually cited | `chat/` | Real. Commodity. |
| **A way to see, export, or cite any of the above after the build finishes** | — | **Does not exist.** See §7. |

**Read that last row again.** The ledger is written to Postgres on every build and then never read
back. `ExpertDetail` (`api/src/peritus/api/schemas/experts.py`) exposes counts and `avg_quality` and
nothing else. There is no endpoint that lists sources, no endpoint that lists *dropped* sources, no
CSV, no RIS, no PRISMA-style diagram. The only place a user ever sees a screening decision is the
live SSE `source_validated` event as the build runs — it scrolls past and is gone.

**The product's entire claimed differentiator is currently invisible.** That is the single most
important fact in this document, and it makes the top build item obvious.

---

## 4. Competitive set — honest assessment

Ordered by how dangerous they are to this positioning.

### Elicit — *the direct threat*
Searches 125M+ papers (OpenAlex, Semantic Scholar, PubMed). Screens up to 40,000 records per review.
Records exclusion reasons **plus a supporting quote** per decision. Exports PRISMA flow diagram,
search strategies, and included-study characteristics. Dual-review support; positions its AI as one
of two reviewers. Published accuracy: 97%/93% abstract, 99.5%/70% full text, 96% extraction accuracy,
1.0% hallucination rate. $12/mo Plus, $49/mo Pro, $79/user/mo Team.

- **Where Peritus loses:** everything on the academic-literature path. Scale (40,000 vs ~40), accuracy
  (published vs none), export (complete vs none), credibility (well-funded, cited, used).
- **Where Peritus wins:** Elicit's coverage is "comprehensive for most systematic reviews" *of
  academic databases*, and reviewers are explicitly advised to supplement it for grey literature and
  clinical-trial reports. Elicit has no web fetcher, no PDF-OCR-from-arbitrary-URL, no YouTube, no
  practitioner discussion. It also cannot record *why* a search was run, because it does not run the
  searches — the user supplies them.
- **Honest read:** do not compete with Elicit. Be the thing a diligent Elicit user still has to do by
  hand afterwards. That framing also makes Elicit a distribution channel rather than an enemy.

### Covidence — *the incumbent workflow*
The default end-to-end screening and extraction platform; Cochrane-endorsed. Cochrane/EPPI RCT
classifier at >99.5% sensitivity, reducing manual screening volume by up to ~45%; deliberately
conservative (auto-exclude disabled by default, health-domain only). ~$339/yr single review,
~$907/yr for three; institutional tiers.

- **Where Peritus loses:** it *is* the process of record for clinical reviews. Team collaboration,
  blinded dual screening, conflict resolution, extraction forms — none of which Peritus has or should
  build.
- **Where Peritus wins:** Covidence begins at "import your RIS." Everything upstream of the RIS is
  out of scope for it.
- **Honest read:** integration target, not competitor. The most valuable single feature Peritus could
  ship is **RIS export of the accepted set with the appraisal metadata attached**, so grey items land
  in Covidence alongside database records.

### Rayyan — *the free floor*
The default free title/abstract screening tool for Cochrane and clinical teams; ML-assisted
prioritisation claimed to cut screening time by up to 90%. Free tier limited to three concurrent
projects; no PRISMA flow diagram and no automatic duplicate resolution on free; its ResearchPilot AI
is institution-only; **no published accuracy figures for any AI feature**.

- **Where Peritus loses:** free is a hard price to beat, and Rayyan owns the habit.
- **Where Peritus wins:** same as Covidence — Rayyan starts from an import.
- **Honest read:** Rayyan sets the *psychological* price ceiling for anything screening-shaped.
  Another reason not to sell screening.

### Scite — *the contradiction-detection competitor*
Smart Citations label whether a later paper supports or contrasts a cited claim, plus an assistant
and topic dashboards. $12/mo annual, $20/mo monthly; no permanent free tier.

- **Where Peritus loses badly:** Scite's contradiction signal is derived from a citation network of
  real papers citing real papers. Peritus's is an LLM asserting `contradicts` between concept nodes
  extracted from chunk batches by Haiku. Scite's is checkable; Peritus's is not.
- **Where Peritus wins:** Scite only knows about things with a DOI. A government report contradicting
  a peer-reviewed finding is invisible to it.
- **Honest read: soften every contradiction claim.** Frame it as *"the build flags where your sources
  disagree, so you can go look"* — a pointer for a human, never a finding. Do not put a number on it.

### Consensus — *the commodity Q&A layer*
200M+ papers, natural-language question answering, a "Consensus Meter" showing agreement across
studies, synthesis across papers. $8.99/mo Premium, $15/mo Pro, generous free tier.

- **Honest read:** this is what "chat with an AI about a topic" is worth: $9/month, and falling. It is
  a direct argument for abandoning the current Peritus positioning, not for competing with it.

### ResearchRabbit — *free discovery*
Citation-graph exploration, similar-work and reference expansion, Zotero sync. Free forever for the
core product; $10/mo RR+ raises seed limits.

- **Honest read:** overlaps Peritus's snowballing, does it better, and is free. Do not invest further
  in snowballing as a headline feature.

### NotebookLM — *the commoditiser*
Source-grounded RAG with inline citations over 50 sources (free) up to 600 (Ultra), 500,000 words per
source, plus audio/video overviews and mind maps. Effectively free or bundled.

- **Honest read:** NotebookLM is why the current Peritus hero copy cannot survive. "Grounded chat over
  a corpus you assembled" is a free Google feature. The only defensible ground is *how the corpus was
  assembled and whether that is documented* — which NotebookLM does not touch, because the user brings
  the sources.

### The bundled generalists — ChatGPT, Perplexity, Claude
Deep-research modes that browse, cite, and synthesise, already paid for by almost every target user.

- **Honest read:** they win on convenience and lose on defensibility — their search paths are not
  reproducible, not exportable, and not appraisable. That is the entire argument.

---

## 5. The wedge

> **Peritus documents the grey-literature search — the half of an evidence review that no tool
> documents and every peer reviewer questions.**

The positioning sentence:

> *Peritus searches the sources your database export misses — reports, preprints, standards, talks,
> practitioner writing — and produces a defensible record of every source it considered, why each was
> kept or dropped, and which searches produced it.*

Three things make this hold together, and they map onto capabilities that already exist:

1. **Heterogeneous discovery.** Nine fetchers spanning web, PDF-with-OCR, video transcripts, books,
   preprints, and practitioner discussion. No incumbent has this, and none is likely to build it —
   their whole architecture assumes a bibliographic record.
2. **Search provenance, not just screening provenance.** `discovered_via` records *which search
   produced this source*, including `gapfill:<concept>` — a search run specifically because a named
   concept was uncovered. This is the "search strategy" half of PRISMA reporting (how records were
   identified), which grey literature has no tooling for at all. Screening provenance (the drop
   reason) is table stakes; **search provenance is not, and Peritus already has it**.
3. **A computed sufficiency argument.** The gap-fill loop checks the corpus against a named concept
   list and re-searches what is uncovered. A reviewer asking "how do you know your grey search was
   adequate?" currently gets a shrug. This produces an answer with a shape.

**The honest claim, in the exact words that may be used publicly:**

> Peritus runs the first pass and shows its work. It is not a substitute for two independent human
> reviewers, and its screening decisions are not a compliance artefact — they are a defensible
> starting point that a human checks. What it turns into an afternoon is the triage, not the
> judgement.

**Forbidden claims — do not write these anywhere, ever:**

- "PRISMA compliant" / "PRISMA certified" / "meets PRISMA."
  Peritus may say its ledger *produces the data PRISMA asks you to report* (records identified,
  screened, excluded, and reasons). It may never claim compliance, which is a property of a review, not
  a tool.
- Anything implying LLM screening substitutes for, or counts as, one of two independent reviewers.
  Elicit makes a version of this claim and has the accuracy data to support it. Peritus has neither.
- Any sensitivity, specificity, recall, or precision figure. **There is no calibration set.** Publishing
  a number without one would be fabrication.
- "Detects contradictions in the literature." The graph flags where *sources in this corpus* were
  judged to disagree. Say that.
- "Systematic review software." Peritus does not do screening at scale, dual review, conflict
  resolution, or extraction. Calling it that invites a comparison it loses.

---

## 6. What to build

Ordered. Item 1 is not optional — without it there is no product, only a claim.

### Tier 0 — makes the positioning true at all

1. **Surface and export the ledger.** The data exists in `sources` and is currently unreachable.
   Needs: `GET /experts/{slug}/sources` returning every row (passed *and* dropped) with
   `quality_score`, `relevance_score`, `drop_reason`, `validator_model`, `rubric_version`,
   `discovered_via`, `covered_concepts`; a screening-ledger view in the dashboard; and **CSV + RIS
   export**. RIS is what makes the grey items importable into Covidence, Zotero, and EndNote —
   it is the integration, and it is cheap.
   *Owner note: `api/src/peritus/api/schemas/experts.py` and the dashboard are outside this
   document's file ownership; this is a request, not a change.*
2. **A search-strategy report.** One page per build: the queries actually issued per fetcher, counts
   identified → retrieved → screened → included → excluded with reasons, and the gap-fill rounds with
   the concept that triggered each. This is a methods section the user can paste, and it is assembled
   entirely from data already recorded.
3. **Persist triage scores.** Triage currently decides which candidates are worth full retrieval and
   then throws the reasoning away. Those are *screening decisions on records that were identified*,
   and PRISMA-style reporting wants them counted. Cheap to store, and it makes the "identified"
   number honest rather than an artefact of the fetch budget.

### Tier 1 — makes it worth paying for

4. **User-supplied inclusion/exclusion criteria.** Today the only "criteria" are a topic string and
   LLM-invented key concepts. A reviewer has a protocol: population, intervention, comparator,
   outcome, date range, language, study design. Until those can be entered, the appraisal is not
   *their* appraisal and cannot be defended as such.
5. **Editable, re-runnable search plans.** The plan stage writes per-fetcher queries. Let the user see
   them, edit them, save them, and re-run — that is a documented, reproducible search strategy, which
   is the actual PRISMA requirement. Also converts a black box into a tool.
6. **Human override on every decision, recorded as an override.** Let the reviewer flip include ↔
   exclude with a reason, stamped as human-adjudicated and distinguishable in the export. This is the
   feature that makes "first pass plus a human check" literally true rather than a slogan, and it is
   the strongest possible answer to "you're not two reviewers."
7. **Deduplicate against an existing library.** Upload the RIS from the database search; Peritus
   reports which grey findings are already covered and which are genuinely new. Directly answers
   "what did this actually add?"
8. **A biomedical fetcher.** Shipped with this work (`sources/fetchers/pubmed.py`, via Europe PMC —
   see the accompanying report). Closes the most conspicuous coverage hole for the target audience.

### Tier 2 — only after 1–7 are used by real reviewers

9. Living-review re-runs: re-execute a saved plan on a schedule and diff the corpus.
10. Per-source appraisal against a named grey-literature checklist (AACODS), with the checklist named
    in the export.

### What NOT to build — and why

- **Screening at database scale.** Do not chase 3,000-record RIS imports. Elicit does it better,
  Covidence owns the workflow, Rayyan does it free, and the architecture is wrong for it (see §7).
  Chasing it means losing on someone else's terms.
- **Dual-reviewer workflow, blinding, conflict resolution, inter-rater agreement.** This is Covidence's
  moat and a team-collaboration product. A solo developer will not out-build it, and every hour spent
  there is an hour not spent on the thing nobody else does.
- **Structured data extraction / meta-analysis tables.** Elicit reports 96% accuracy on this. Do not
  start from zero against that.
- **A better chatbot.** Chat should be demoted to a utility for interrogating a corpus you have already
  defended. NotebookLM is free, Consensus is $9, and the generalists are bundled. Never lead with it.
- **A citation-network contradiction engine.** Scite has 1B+ citation statements. Peritus's
  `contradicts` edges should stay a within-corpus pointer, nothing more.
- **A reference manager.** Zotero exists and is free. Export to it.
- **Enterprise/regulated verticals this year.** No procurement, no SOC 2, no sales motion, no company.
- **Mobile.** Nobody screens literature on a phone.

---

## 7. Honest limitations

These are real and must inform every claim made publicly.

1. **Scale is off by three orders of magnitude.** `_BASE_FETCH_BUDGET = 30`; the pro tier multiplier
   is 2.0, giving ~60 candidates retrieved and ~40 accepted. A systematic review screens thousands.
   Peritus is a *discovery* engine that appraises what it found, not a *screening* engine for what
   you brought. Anything implying otherwise will be found out on first use.
2. **The ledger is write-only.** Documented above; item 1 of the build list.
3. **No inclusion/exclusion criteria.** Validation scores against a topic string and LLM-generated
   concepts. A user cannot express a protocol, so the appraisal is not theirs to defend.
4. **No accuracy data of any kind.** Single Haiku pass, thresholds q≥5/r≥6, rubric `v3-concepts-q5r6`.
   No gold set, no calibration, no published sensitivity. Elicit publishes numbers; Peritus cannot
   respond, and must not pretend to.
5. **Contradiction detection is weak evidence.** LLM-asserted at concept level, extracted in chunk
   batches by Haiku, then merged by embedding similarity. It flags tension. It does not establish it.
6. **Grey literature is exactly where LLM appraisal is least reliable.** A government report and a
   Reddit thread are appraised by the same rubric with a per-type hint. That is thin. The human-override
   feature (build item 6) is the mitigation, and it should ship before this is sold hard.
7. **Reproducibility is not guaranteed.** The pipeline is LLM-driven end to end — planning, triage,
   validation, extraction. Two runs of the same topic will not produce the same corpus. For a field
   whose core value is reproducibility, this is the deepest structural problem in the strategy.
   Editable, saved, re-runnable search plans (build item 5) narrow the gap; they do not close it.
8. **Coverage is uneven.** The `web` fetcher scrapes DuckDuckGo HTML. Exa needs a key. Reddit and
   YouTube are noise for many topics. Gutenberg is irrelevant to most. The nine-fetcher count flatters
   the reality.
9. **No dedupe against an existing library**, so "what did this add?" is currently unanswerable.
10. **Cost and latency are real.** A pro build makes hundreds of LLM calls. Batch API halves the price
    and roughly doubles the wall-clock time. This is not an interactive product.
11. **Solo developer, no institutional credibility.** Research tools spread through citation and
    departmental adoption. Peritus has neither, and the first published review that used it is worth
    more than any feature on this list.

---

## 8. Pricing hypothesis

**Grounding: a build costs real money.** Derived from the code — `CHUNK_SIZE_CHARS=1500`,
`GRAPH_BATCH_SIZE=10`, contextualiser batches of 5 with a 3,000-char window, validation batches of 5
with a 2,400-char preview — at published rates (Claude Haiku 4.5 $1/$5 per MTok; Claude Sonnet 5
$3/$15; Message Batches API −50%, on by default via `ANTHROPIC_BATCH_ENABLED`):

| Stage | Model | Est. cost per pro build (batched) |
|---|---|---|
| Plan | Sonnet 5 | ~$0.01 |
| Triage (~60 candidates) | Haiku 4.5 | ~$0.02 |
| Validation (~60 sources) | Haiku 4.5 | ~$0.09 |
| Contextualisation (~1,000 chunks) | Haiku 4.5 | ~$0.65 |
| Graph extraction (~100 batches) | Haiku 4.5 | ~$0.69 |
| Persona | Sonnet 5 | ~$0.05 |
| Embeddings (~1,000 chunks) | OpenAI `text-embedding-3-large` | ~$0.07 |
| **Total** | | **~$1.50–3.00** |

Plus Mistral OCR on PDFs (variable) and Exa/Cohere if configured. A chat turn at pro tier is roughly
$0.10–0.15. **These are estimates from constants in the code, not measurements. Instrument a real
build before quoting anything.**

**Implication: unlimited builds cannot be offered at a consumer price point.** Consensus is $9/mo and
Elicit Pro is $49/mo, but both amortise a fixed corpus across all users. Peritus pays per build.

**Proposed structure:**

| Tier | Price | Includes | Rationale |
|---|---|---|---|
| Free | $0 | 2 lite builds, ledger visible, **export watermarked or withheld** | Enough to see the ledger; not enough to finish a review. The export is the product. |
| Researcher | **$29/mo** or **$240/yr** | 20 standard builds/mo, unlimited chat, full CSV + RIS export, search-strategy report | Below Elicit Pro ($49) — Peritus is a complement, not a replacement, and must not price like one. Above Consensus ($9) — this is a work tool, not a search box. ~$0.50–1.00 COGS per build leaves room. |
| Review | **$99** one-off, 90 days | 100 builds, everything above, all exports | **The important one.** A review is a project, not a subscription; researchers think in projects and grants. Covidence's ~$339/yr single-review price sets the reference. Grant-expensable without a conversation. |
| Institutional | Contact | Seats, shared workspaces, invoicing | Only after a library or evidence unit asks. Do not build ahead of demand. |

**Rejected alternatives, and why:**
- *Per-build credits.* Correct COGS alignment, wrong psychology — meters make researchers ration
  searches, which is exactly the behaviour a search tool must not encourage.
- *Free with API keys (BYOK).* Preserves margin, but concedes the market to anyone with a UI, and the
  target user does not want to manage an Anthropic account.
- *Free forever, monetise institutions.* Rayyan's model. Requires a funded organisation behind it.

**Test first:** whether the $99 project price is even the right *shape* is assumption 3 in §9. Do not
build billing before that test returns.

---

## 9. The three riskiest assumptions, and a cheap test for each

### Risk 1 — Nobody actually needs the grey-literature record enough to pay
The whole thesis rests on a peer-reviewer pain that may simply be tolerated. Reviewers have written
"we also searched relevant websites" for twenty years and got published anyway.

- **Cheap test (2 weeks, ~$0).** Take 30 recently published scoping reviews that state a grey-literature
  search. Email the corresponding author one question: *"When you reported the grey-literature search,
  did a reviewer ask you to justify it — and how long did documenting that search take?"* Cold email to
  corresponding authors on this kind of methods question typically returns 10–20%.
- **Kill signal:** fewer than 5 of 30 report having been challenged on it, or the median time spent is
  under half a day. If it isn't painful, it isn't a wedge.
- **Go signal:** multiple unprompted mentions of reviewer pushback, or a median of several days.

### Risk 2 — LLM appraisal of grey literature is not good enough to be defensible
This is the technical risk, and §7.6 says it is where the model should be weakest. If the appraisal is
bad, the ledger documents a bad process in high resolution, which is worse than no ledger.

- **Cheap test (1 week, ~$50 of API credit).** Pick one published scoping review with a documented grey
  search and a stated included/excluded set. Run Peritus on the same topic. Measure two things: (a) what
  fraction of the review's included grey items Peritus's discovery found at all, and (b) of the items
  Peritus discovered that the review also assessed, how often the accept/reject decision agrees. This
  is the beginning of the calibration set the product currently lacks — which is worth building
  regardless of the outcome.
- **Kill signal:** recall of the known included set below ~50%, or decision agreement near chance. At
  that point the honest move is to reposition as *discovery only* and drop appraisal from the pitch.
- **Go signal:** high recall on discovery. Note that discovery recall matters far more than decision
  agreement — a human can fix a wrong call in seconds but cannot recover a source that was never found.

### Risk 3 — Researchers will not pay individually, or will not pay at this shape
Assumes an individual with grant money buys a $99 project licence without procurement.

- **Cheap test (1 week, ~$0).** A landing page with the §5 positioning and a live pricing table
  including "Review — $99, 90 days." Route the button to a waitlist form asking one question: *"Would
  this come out of a grant, a departmental budget, or your own pocket?"* Drive traffic from 3–4
  targeted places — an evidence-synthesis Slack, the r/systematicreview and academic-Twitter/Bluesky
  methods communities, and one methods-focused mailing list. **Fake-door test the price, not the
  product.**
- **Kill signal:** high landing-page interest with near-zero clicks on the paid tiers, or "own pocket"
  dominating the answers. Both mean this is an institutional sale, which a solo developer cannot run
  this year.
- **Go signal:** "grant" or "departmental budget" majority, and ≥5% of visitors clicking a paid tier.

**Run Risk 1 and Risk 3 in parallel — neither requires any code.** Run Risk 2 only if either returns
a go signal.

---

## 10. What would make me abandon this positioning

Stated up front so it is not rationalised away later:

- Elicit or Covidence ships open-web / grey-literature search. Either could; Elicit has the funding and
  the motive. This would remove the wedge in a single release. **This is the most likely way the
  strategy dies.**
- Risk-2 testing shows discovery recall on grey literature is poor. Then Peritus is not a search tool,
  and there is no story left.
- Interviews reveal that reviewers who care about grey-literature rigour do not trust *any* automation
  for it — a real possibility given Covidence's decision to ship AI screening off by default in the
  more forgiving academic-literature domain.

If two of the three land, the fallback is narrower and smaller but still honest: **a grey-literature
discovery tool that produces a search-strategy report**, no appraisal claims, priced at $10–15/mo. A
utility, not a platform. Worth building; not worth a company.

---

## Sources

Competitive research conducted July 2026.

- [Elicit — Systematic Review, built for PRISMA 2020](https://elicit.com/blog/systematic-review-for-prisma-2020)
- [Elicit — source for papers](https://support.elicit.com/en/articles/553025)
- [Elicit AI review 2026: pricing and accuracy](https://fast.io/resources/elicit-ai-review-2026/)
- [Covidence — AI feature: tagging references reporting on RCTs](https://support.covidence.org/help/ai-feature-tagging-references-reporting-on-rcts)
- [Covidence — how it decides what AI to release](https://www.covidence.org/blog/ai-screening-automation-systematic-reviews/)
- [Covidence — planning and reporting the use of automation (AI)](https://support.covidence.org/help/should-i-use-automation-ai-in-my-review)
- [Rayyan review 2026: features and pricing](https://aichief.com/ai-search-engine/rayyan/)
- [A review of Rayyan — Doody's Collection Development Monthly](https://dcdm.doody.com/2026/01/a-review-of-rayyan/)
- [Consensus pricing 2026](https://top50aitools.com/pricing/consensus)
- [Research Rabbit vs scite.ai comparison 2026](https://pointofai.com/compare-ai-tools/research-rabbit-vs-scite-ai)
- [NotebookLM source limits by plan (2026)](https://www.notebooktools.com/blog/notebooklm-source-limits)
- [Guidance to including gray literature in systematic reviews — Journal of Clinical Epidemiology, 2026](https://www.jclinepi.com/article/S0895-4356(26)00097-1/fulltext)
- [PRISMA-trAIce checklist for transparent reporting of AI in systematic reviews — JMIR AI](https://ai.jmir.org/2025/1/e80247)
- [Best AI tools for systematic review 2026](https://paperguide.ai/blog/ai-tools-for-systematic-review/)
- [PRISMA 2020 statement](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8008539/)
