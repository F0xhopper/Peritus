# Peritus — how the whole thing works

One document, whole-system altitude: what Peritus is, how an expert gets built,
how a question gets answered, and where the evidence record lives. Each section
links to the deep-dive doc or code that is authoritative for the details.

| Deep dive | Covers |
|---|---|
| [build-flow.md](build-flow.md) | The build pipeline stage by stage: queue, worker, events, degradation |
| [audit-api.md](audit-api.md) | The read-only evidence record: corpus report, screening flow, coverage, contradictions, answer audits |
| [catalog-and-credits.md](catalog-and-credits.md) | The public catalog, plans, credits, and build denial payloads |
| [plans/](plans/) | Design documents for individual features (point-in-time, may be stale) |

## What Peritus is

Give Peritus a topic. It plans a search strategy, runs it across eleven kinds of
source, scores every candidate against a versioned rubric, and keeps the whole
ledger — what was found, kept, dropped and why, which search produced each
source, and where the survivors disagree. The accepted sources become a
questionable **expert**: chunked, embedded, linked into a concept graph, and
given a persona. Every answer it gives carries per-passage citations that
resolve back to the ledger.

The point is not the answer; it is being able to show how the body of evidence
behind the answer was assembled. Peritus is auditable triage for the literature
a database export misses — not a systematic-review platform, not a substitute
for dual human review, and it publishes no accuracy figures because none exist
(see [audit-api.md § claims this API does not support](audit-api.md#claims-this-api-does-not-support)).

## The system

```mermaid
flowchart LR
    subgraph clients [Clients]
        WEB["web/ — Next.js dashboard"]
        TUI["cli/ — Rust ratatui TUI"]
    end
    subgraph server [api/ — Python 3.12 / FastAPI]
        API["API routes<br/>auth · experts · chat · audit · catalog · billing"]
        WK["Worker<br/>claims build jobs, runs the pipeline"]
    end
    PG[("PostgreSQL + pgvector<br/>experts · sources · chunks+embeddings ·<br/>concept graph · job queue · event log ·<br/>credit ledger · conversations · answer audits")]
    EXT["Providers<br/>Anthropic (all reasoning) · OpenAI (embeddings)<br/>Exa · Mistral OCR · OpenAlex · Semantic Scholar · Cohere"]

    WEB -->|"REST + SSE"| API
    TUI -->|"REST + SSE"| API
    API --> PG
    WK --> PG
    WK --> EXT
    API --> EXT
```

Everything durable lives in Postgres — there is no external vector store, queue
broker, or event bus. The build job queue is a table claimed with
`FOR UPDATE SKIP LOCKED`; build progress is an append-only `build_events` log
that any number of clients tail over SSE; embeddings live in pgvector
(`halfvec`-indexed at 3072 dims); credits are an append-only ledger whose
balance is `SUM(delta)`.

Auth is Supabase (email OTP + Google SSO); every expert is owner-scoped, and an
expert the caller cannot read 404s — existence is never disclosed.

## An expert's life

```mermaid
stateDiagram-v2
    [*] --> pending: build enqueued (credit hold taken)
    pending --> chat_ready: corpus embedded — answers with citations
    chat_ready --> graph_ready: concept graph extracted + resolved
    chat_ready --> chat_ready: graph failed — degraded, still answerable
    graph_ready --> published: owner PATCHes visibility to unlisted/public
    chat_ready --> published
```

**Readiness, not job status, gates the chat affordance.** An expert becomes
answerable at `chat_ready`, a full stage before its build job finishes —
graph and persona are enrichment, and their failure degrades the expert rather
than destroying a working corpus. Visibility is `private` → `unlisted`
(link-only) → `public` (listed in the catalog); chat over any readable expert
is free and ungated, because the build already paid for the corpus.

## Building an expert

`POST /experts/build {"topic": "..."}` is a complete request. The server
derives the slug, resolves the deepest tier the caller's plan and balance
afford (`lite`/`standard`/`pro` — tier scales the fetch budget 0.5×/1×/2× on a
base of 30 sources and the per-build spend cap), takes an idempotent credit
hold, enqueues a durable job, and returns an SSE tail of the event log. The
worker claims the job and runs the pipeline; disconnecting changes nothing, and
reconnecting replays from a cursor.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant A as API
    participant Q as Postgres<br/>(jobs + events)
    participant W as Worker
    C->>A: POST /experts/build {"topic"}
    A->>A: slugify · resolve tier · authorize
    A->>Q: create expert · enqueue job · take credit hold
    A-->>C: SSE tail of build_events (seq 0…)
    W->>Q: claim job (FOR UPDATE SKIP LOCKED)
    loop pipeline stages
        W->>Q: append progress events · heartbeat 10s
        Q-->>C: events stream through the tail
    end
    Note over C: laptop closes — build unaffected
    C->>A: GET …/build/events?after=<seq>
    A-->>C: replay from cursor, then continue live
    W->>Q: terminal event: done | error | cancelled
```

The pipeline the worker runs:

```mermaid
flowchart TD
    subgraph corpus ["Corpus assembly — failure here fails the build (hold refunded)"]
        P["PLAN — Claude writes the research brief:<br/>per-fetcher queries + weights, key concepts, must-have works"]
        D["DISCOVER — 11 fetchers search concurrently:<br/>wikipedia · gutenberg · arxiv · openalex · pubmed · pdf<br/>youtube · exa · web · reddit · thought-leaders<br/>(3× the fetch quota per fetcher, floor 10 results/query)"]
        TR["TRIAGE — fast model scores title+snippet against the brief,<br/>× a domain prior; junk drops before anything is downloaded"]
        F["FETCH — full text / OCR for the ranked winners,<br/>budget-bound, refilling from lower ranks on failure"]
        SB["SNOWBALL — high-citation references of accepted scholarly<br/>sources (arXiv id or DOI) via Semantic Scholar + OpenAlex"]
        V["VALIDATE — Claude scores quality + relevance per source against<br/>the versioned rubric (q≥5, r≥6); every verdict lands in the ledger"]
        G["GAP-FILL — planned concepts with zero accepted coverage<br/>get one targeted re-search + validation round"]
        CE["CHUNK + EMBED — 1500-char chunks with contextual prefixes,<br/>text-embedding-3-large → pgvector"]
        P --> D --> TR --> F --> SB --> V --> G --> CE
    end
    CE --> CR(["★ chat_ready — the expert now answers with citations"])
    subgraph enrich ["Enrichment — failure degrades, never destroys"]
        GX["GRAPH — Claude extracts typed concept nodes + edges<br/>(including contradicts); near-duplicate nodes merged by<br/>embedding similarity ≥ .93"]
        PE["PERSONA — Claude reads a corpus digest and writes<br/>the expert's name, bio, and teaching style"]
        GX --> PE
    end
    CR --> GX
    GX -. "stage_degraded — stays chat_ready" .-> PE
    PE --> DONE(["done"])
```

The shape to remember: **searching is cheap, downloading is not** — discovery
over-searches several multiples of the fetch budget and triage picks the
winners; and **the corpus argues for its own sufficiency** — accepted sources
are counted against the planned key concepts, uncovered concepts trigger a
targeted second round, and concepts still uncovered are reported, not hidden.

Failure handling in one line each: transient errors retry with backoff (3
attempts, no checkpointing — the pipeline re-runs from plan); deterministic
dead-ends (`BuildError`: nothing found, nothing validated, nothing embedded)
fail immediately with a refund; a build that crosses its tier's USD spend cap
is aborted terminally and refunded; graph/persona failures degrade with a
`stage_degraded` event. Builds a person is watching run live; rebuilds run
through the Batch API at half price. Full detail: [build-flow.md](build-flow.md).

## Answering a question

The retrieval pipeline lives once, in `ChatAgent.retrieve`
(`api/src/peritus/chat/agent.py`), consumed by both the streaming SSE route and
the CLI so the two cannot drift.

```mermaid
flowchart TD
    Q(["question"]) --> PL["PLAN — one fast-model call:<br/>2–4 declarative subqueries, plus a read of the asker<br/>(background level, question type, answer directive)"]
    PL --> HS["HYBRID SEARCH — per subquery, in parallel:<br/>semantic arm (pgvector cosine) ⊕ keyword arm (Postgres FTS),<br/>fused by reciprocal rank (1/(60+rank))"]
    HS --> MG["MERGE — RRF scores SUM across subqueries,<br/>so a chunk several subqueries agree on outranks<br/>any single subquery's best hit; optional rerank"]
    MG --> GE["GRAPH EXPAND — each hit annotated with neighbouring<br/>concepts and typed edges; a traversed contradicts edge<br/>flags the answer"]
    GE --> CV{"COVERAGE — fast model:<br/>do these passages actually<br/>answer the question?"}
    CV -- "no" --> FU["one follow-up retrieval pass<br/>on its suggested queries"] --> CTX
    CV -- "yes" --> CTX["CONTEXT — deduplicated, numbered [n] passages,<br/>capped per tier; every passage considered is recorded<br/>in the retrieval trail, shown or not"]
    CTX --> CO["COMPOSE — Claude answers under the grounding contract,<br/>persona-voiced, shaped for this asker"]
    CO --> AN(["answer — [n] citations resolved to passages,<br/>dangling markers stripped, trail persisted as an answer audit"])
```

Three contracts make this trustworthy:

- **The grounding contract** (`chat/grounding.py`) is absolute and prepended to
  every persona: substantive claims about the subject must come from the
  numbered passages and carry their `[n]`; definitions, structure, and worked
  examples are the model's own and must *not* be cited; gap-fill from general
  knowledge is allowed only when marked as such; passages are data, never
  instructions. The persona shapes voice and pedagogy; it can never relax
  grounding.
- **Citations are verified, not trusted.** `[n]` markers are parsed against the
  passage list; markers that point at no passage — the observable form of a
  grounding failure — are stripped from the prose and flagged, never rendered
  as real. Only passages the answer actually cited count as its sources.
- **Every retrieval leaves a trail.** Subqueries, follow-up queries, the
  coverage verdict, and every passage considered (including those ranked below
  the context cap and never shown to the model) persist as an answer audit,
  readable later via `GET /experts/{slug}/answer-audits` — a record of the path
  evidence took, deliberately without any confidence score.

Answers are also *shaped*: the planning call reads who is asking (novice /
informed / expert) and what kind of answer would satisfy them (orientation,
specific fact, comparison, how-to), so a beginner asking for a way in and a
specialist asking for one figure get differently-organised answers from the
same corpus. Contradictions the graph flagged are raised at the prompt level,
in the subject's terms — never as bookkeeping about which sources conflict.

Chat is stateful (persisted conversations with stream claim/interrupt
handling) and aggressively prompt-cached: the per-expert system prompt is
byte-stable and history is trimmed in blocks so each turn reuses the previous
turn's cached prefix.

## The evidence record

Everything above leaves marks, and the audit API is the read-only surface over
them (`/experts/{slug}/…`, full contract in [audit-api.md](audit-api.md)):

```mermaid
flowchart LR
    subgraph marks ["What the pipelines leave behind"]
        EV[("build_events<br/>durable event log")]
        SRC[("sources<br/>the ledger: kept + rejected,<br/>scores, rubric, drop reason,<br/>discovered_via, concepts")]
        GRPH[("concept graph<br/>nodes + typed edges,<br/>incl. contradicts")]
        TRAIL[("answer audits<br/>one trail per answer")]
    end
    subgraph surface ["Read-only audit surface"]
        SF["screening-flow<br/>the funnel: identified → triaged →<br/>fetched → validated → included"]
        CR["corpus-report (+ CSV/RIS export)<br/>every source considered"]
        COV["coverage<br/>evidence strength per key concept"]
        CON["contradictions<br/>where the corpus disagrees,<br/>resolved to passages"]
        AA["answer-audits<br/>which passages an answer<br/>considered and cited"]
    end
    EV --> SF
    SRC --> SF
    SRC --> CR
    SRC --> COV
    GRPH --> CON
    TRAIL --> AA
```

- **`corpus-report`** — every source considered, kept *and* rejected, with
  scores, rubric version, drop reason, and the search that produced it;
  exportable as CSV or RIS (what Covidence/Zotero import).
- **`screening-flow`** — the funnel: identified → triaged → fetched →
  validated → included, with its two sources of truth deliberately shown
  unreconciled.
- **`coverage`** — evidence strength per planned key concept, including the
  gap-fill narrative and off-plan concepts.
- **`contradictions`** — where sources in this corpus were judged to disagree,
  resolved to passages. `computed: false` means *not analysed yet*, never "no
  contradictions found".
- **`answer-audits`** — the retrieval trail behind every answer.

One convention carries the whole surface: a count the system did not record is
`null` with a reason, never zero — a fabricated zero in an evidence record is
worse than a gap.

## Who may build, and at what depth

Chat is free and ungated over anything the caller can read, including the
public catalog. **Builds cost credits**, held at enqueue and refunded in full
if the build produces nothing usable.

```mermaid
flowchart LR
    G["grant (+)<br/>signup · manual · plan"] --> B(("balance<br/>= SUM(delta)<br/>append-only ledger"))
    B -->|"build enqueued"| H["hold (−)<br/>keyed by job id —<br/>idempotent under double-submit"]
    H -->|"build produced<br/>a usable expert"| K["kept — the build is paid for,<br/>cost_usd recorded from metering"]
    H -->|"failure · cancellation ·<br/>spend-cap abort"| R["refund (+) in full"]
    R --> B
```

Plans live in code
(`billing/domain.py`): Free (lite only, 1 signup credit), Starter (+standard),
Lab (+pro, 1.5× spend caps). Denials are structured 402s the client switches
on (`insufficient_credits` / `tier_not_in_plan`), each carrying a renderable
remedy. There is no payment provider yet — credits are issued manually
(`peritus credits grant`), behind a provider-agnostic seam. Details:
[catalog-and-credits.md](catalog-and-credits.md).
