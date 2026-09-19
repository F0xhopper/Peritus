"""Every setting the backend reads from the environment, in one place.

A ``pydantic_settings.BaseSettings`` model, which means three things the
hand-rolled ``os.getenv`` class it replaces could not do:

* **Bad values are named.** ``DB_POOL_MAX_SIZE=ten`` used to raise a bare
  ``ValueError`` from an ``int()`` call during import, before logging existed,
  with nothing in the message saying which variable was wrong. Now it names the
  field — and reports *every* invalid setting at once rather than the first.
* **The enum-valued settings are checked here rather than at their point of
  use.** ``CHAT_EFFORT``, ``BUILD_EXECUTION_DEFAULT``, ``PICTURE_RANKER``,
  ``DISCOVERY_LOOP`` and ``HNSW_ITERATIVE_SCAN`` were plain strings validated
  (or, for ``CHAT_EFFORT``, not validated) wherever they happened to be read.
  A typo surfaced hours later as a strange build, or as a warning nobody saw.
* **The types are the documentation.** What was a comment is a signature.

Assignment is deliberately *not* validated, so ``monkeypatch.setattr(settings,
…)`` still works — several tests set a deliberately invalid value to exercise
the fallback path that handles one.

``settings`` remains the public surface; nothing outside this module constructs
a ``Settings``.
"""

from typing import Literal

from dotenv import load_dotenv
from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Kept beside pydantic's own `env_file`: `billing/settings.py` and
# `migrations/apply.py` read os.environ directly, and importing this module is
# what has always made a local .env visible to them.
load_dotenv()

# Whether a build runs live, batched, or decides per build.
BuildExecutionDefault = Literal["auto", "interactive", "background"]
# How hard Claude thinks when composing an answer.
ChatEffort = Literal["low", "medium", "high", "xhigh", "max"]
# How the expert picture is chosen from the candidates Wikimedia returns.
PictureRanker = Literal["heuristic", "model"]
# Whether discovery may run more than one round.
DiscoveryLoop = Literal["auto", "true", "false"]
# pgvector's filtered-scan mode. "off" is absent on purpose: it silently
# truncates results (see infrastructure/database.iterative_scan_sql).
IterativeScan = Literal["relaxed_order", "strict_order"]

_TRUTHY = ("true", "1", "yes", "on")
_FALSEY = ("false", "0", "no", "off")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # The environment holds far more than this model: PATH, the test
        # database URL, the billing module's own PERITUS_* keys. Forbidding
        # extras would make the process refuse to start over any of them.
        extra="ignore",
        # Tests set deliberately invalid values to reach the code that handles
        # one; validating on assignment would make those unreachable.
        validate_assignment=False,
    )

    LOG_LEVEL: str = "INFO"
    # Optional path to also tee backend logs to a file. Empty (default) = stderr
    # only, which is what `just dev`/hivemind shows in the terminal. Set e.g.
    # LOG_FILE=peritus.log to keep a persistent copy across restarts.
    LOG_FILE: str = ""

    # Database
    DATABASE_URL: str = ""
    DATABASE_SSL: bool = False
    # Pool sizing. One process may serve API traffic *and* run builds
    # (RUN_WORKER_IN_PROCESS), so the ceiling has to cover both; raise it
    # alongside WORKER_CONCURRENCY rather than leaving builds to starve chat.
    DB_POOL_MIN_SIZE: int = 2
    DB_POOL_MAX_SIZE: int = 10
    # Server-side statement timeout. Without one a pathological query pins a
    # pooled connection forever, and DB_POOL_MAX_SIZE of those is an outage.
    DB_COMMAND_TIMEOUT: float = 30
    # How long a caller waits for a free connection before giving up. Bounded so
    # an exhausted pool surfaces as a fast 503 instead of an indefinite hang.
    DB_ACQUIRE_TIMEOUT: float = 10
    # How a filtered HNSW scan behaves when the expert_id filter rejects most of
    # what the index returns. Must not be "off": that silently truncates results
    # (measured 40 rows returned out of 184). See database._enable_iterative_scan.
    HNSW_ITERATIVE_SCAN: IterativeScan = "relaxed_order"

    # Embeddings
    OPENAI_API_KEY: str = ""
    EMBED_MODEL: str = "text-embedding-3-large"
    EMBED_DIM: int = 3072
    OPENAI_TIMEOUT: float = 60
    OPENAI_MAX_RETRIES: int = 3
    # Two separate concurrency budgets, deliberately. A chat turn embeds a
    # handful of subqueries and a user is waiting; a build embeds hundreds of
    # chunk batches and nobody is. Sharing one semaphore lets a build queue
    # ahead of every interactive request in the same process.
    EMBED_QUERY_CONCURRENCY: int = 8
    EMBED_BATCH_CONCURRENCY: int = 2

    # Anthropic — validation, graph extraction, persona, chat
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-5"
    # The SDK defaults to a 600s timeout. A composition call that hangs that long
    # holds an SSE connection, a DB connection and the conversation's stream
    # claim with it, so cap it far lower and let the SDK's retries do the work.
    ANTHROPIC_TIMEOUT: float = 120
    ANTHROPIC_MAX_RETRIES: int = 3

    # Fast model for contextualisation, validation, reranking, coverage
    FAST_MODEL: str = "claude-haiku-4-5-20251001"

    # Research planning — one call per build that shapes the whole corpus, so it
    # defaults to the strong model rather than FAST_MODEL.
    PLAN_MODEL: str = ""  # falls back to CLAUDE_MODEL; see _resolve_plan_model

    # Graph extraction model — Haiku is sufficient and much cheaper than Sonnet
    GRAPH_MODEL: str = "claude-haiku-4-5-20251001"

    # ── Anthropic Message Batches ────────────────────────────────────────────
    # Build-pipeline stages (triage, validation, contextualisation, graph
    # extraction) can run through the Message Batches API at 50% of standard
    # token prices, at the cost of up to ~1h of queueing per stage.
    #
    # Whether a *given build* batches is decided per build (see
    # BUILD_EXECUTION_DEFAULT and peritus.infrastructure.anthropic_batch); this
    # flag is the deployment-level kill switch above it. False = this deployment
    # never touches the Batch API, whatever a build asks for.
    ANTHROPIC_BATCH_ENABLED: bool = True
    # Policy for builds that don't state their own execution mode:
    #   auto        — first build of an expert runs live (a user is watching it);
    #                 rebuilds and scheduled refreshes batch at half price
    #   interactive — every build runs live: fastest, full price
    #   background  — every build batches: cheapest, hours of wall clock
    BUILD_EXECUTION_DEFAULT: BuildExecutionDefault = "auto"
    # Below this many requests a stage just makes live calls — batch overhead
    # and queueing latency aren't worth it for a handful of requests.
    ANTHROPIC_BATCH_MIN_REQUESTS: int = 4
    # How often to poll a submitted batch for completion.
    ANTHROPIC_BATCH_POLL_INTERVAL: float = 15
    # After this many seconds the batch is cancelled, finished results are
    # harvested, and the remainder falls back to live calls.
    ANTHROPIC_BATCH_TIMEOUT: float = 3600

    # ── Chat ─────────────────────────────────────────────────────────────────
    # Cap on client-supplied history messages sent to Claude per turn. Bounds
    # both cost and abuse; the prompt cache makes retained history cheap.
    CHAT_HISTORY_MAX_MESSAGES: int = 20

    # How many messages are dropped at once when history exceeds the cap above.
    # This exists for the prompt cache, not for the cap: trimming one message per
    # turn moves the start of the window every turn, so the cached prefix is
    # never byte-identical twice and a long conversation — the case with the most
    # to save — pays full input price on every turn. Dropping in blocks holds the
    # window's start still for BLOCK/2 turns, so those turns share a prefix.
    # Larger blocks mean better cache hit rates and a coarser history cap.
    CHAT_HISTORY_TRIM_BLOCK: int = 6

    # Per-user throttle on the two chat endpoints. Builds are gated by credits;
    # chat is free to the user but not to us — every message is a planning call,
    # a rerank, a coverage call and a composition. This is the only ceiling on
    # what one authenticated account can spend, so it is on by default.
    # Thinking for answer composition. Claude Sonnet 5 thinks by default and its
    # thinking counts against max_tokens, so an answer request states both: the
    # effort (low | medium | high | xhigh | max) and the tokens thinking may use
    # on top of the tier's answer length.
    CHAT_EFFORT: ChatEffort = "low"
    # Effort for synthesis questions — the planner's `comparison`,
    # `orientation` and `open_ended` types. Empty means CHAT_EFFORT. An
    # experiment (docs/plans/beating-closed-book.md 2.6): medium was measured
    # as no help on an explanation question, and synthesis is a different job.
    CHAT_BROAD_EFFORT: ChatEffort | Literal[""] = ""
    CHAT_THINKING_HEADROOM_TOKENS: int = 4096

    CHAT_RATE_LIMIT: int = 20
    CHAT_RATE_WINDOW: float = 60

    # Source fetchers
    EXA_API_KEY: str = ""
    # OpenAlex needs no key; an email opts requests into its faster "polite pool".
    OPENALEX_MAILTO: str = ""
    # Semantic Scholar API key (free, from semanticscholar.org). Sent as
    # `x-api-key` by the pdf fetcher and by citation snowballing. Without it
    # both share the unauthenticated pool, which rate-limits hard: the pdf
    # fetcher returned nothing on the Thomism build (job 53), almost certainly
    # to 429s. Unset still works, and a 429 is now reported as `rate_limited`.
    S2_API_KEY: str = ""
    # Project Gutenberg's catalogue CSV (~21 MB), downloaded once a week per
    # worker so identifying a public-domain book is a local lookup rather than a
    # call to Gutendex. Defaults to ~/.cache/peritus. Disable to fall back to
    # Gutendex alone.
    GUTENBERG_CATALOGUE_DIR: str = ""
    GUTENBERG_CATALOGUE_ENABLED: bool = True
    # Wall-clock cap on one full fetch of one candidate. Every fetcher already
    # sets httpx timeouts, but those are per-operation: a server that dribbles a
    # byte before each read timeout never trips one, and the fetch hangs forever
    # inside a stage that reports nothing until it finishes. This is the outer
    # bound that makes a single bad URL cost one slot instead of the build. Sized
    # above the slowest legitimate fetch — PDF OCR allows itself 120s.
    SOURCE_FETCH_TIMEOUT: float = 180

    # ── Expert picture (found on Wikimedia at build time) ────────────────────
    # A new expert gets a real picture of its subject — the lead image of the
    # Wikipedia article, with its licence and attribution — instead of only a
    # monogram. Nothing here can fail a build: the finder is the first thing a
    # build starts, runs as a background task beside it under its own deadline,
    # and emits `picture_skipped` with a reason when it comes up empty. A direct
    # search that finds nothing costs one small FAST_MODEL call, for what would
    # illustrate the subject instead. An expert still without a picture when its
    # corpus is done gets a second look then — see `PICTURE_FINAL_TIMEOUT`.
    # See experts/picture.py.
    PICTURE_ENABLED: bool = True
    # Whole-search deadline, per build. Five or six HTTP requests fit easily;
    # this is the bound that keeps a slow Wikimedia from being the build's problem.
    PICTURE_TIMEOUT: float = 20
    # The deadline for the second look, at the end of the build. Longer than the
    # first because it is the last chance this build has: a single honoured
    # `Retry-After` from a throttling Wikimedia is most of twenty seconds, and
    # the cost of waiting is a finished corpus reaching its persona a little
    # later — once, and only for an expert the first look left bare.
    PICTURE_FINAL_TIMEOUT: float = 45
    # Refuse a thumbnail larger than this. Mirrored by a CHECK on the table, so
    # raising it here alone will not let a bigger file through.
    PICTURE_MAX_BYTES: int = 400000
    # The width asked of Wikimedia's thumbnail service. There is no resizing on
    # our side (no Pillow): this is the size that gets stored and served.
    PICTURE_THUMB_WIDTH: int = 512
    # heuristic — rank by article order, format and size (free, phase 1)
    # model     — one FAST_MODEL call per build over up to six thumbnails
    PICTURE_RANKER: PictureRanker = "heuristic"
    # Phase 3 widens this to "wikipedia,commons,openverse".
    PICTURE_PROVIDERS: str = "wikipedia"

    # Wikimedia's API etiquette asks for a contact address in the User-Agent of
    # anything making real volume. An email or a URL; empty still sends a
    # descriptive agent, it just cannot be reached.
    PERITUS_CONTACT: str = ""

    # Mistral OCR (PDF parsing)
    MISTRAL_API_KEY: str = ""
    MISTRAL_OCR_MODEL: str = "mistral-ocr-latest"

    # Structural ingestion (ingestion/structural.py): the part of a long work
    # past its close-read ceiling is held embed-only — chunked, noted from its
    # headings, embedded, never contextualised or graphed — within a per-tier
    # character budget.
    STRUCTURAL_INGEST_ENABLED: bool = True
    # Section summaries (ingestion/summaries.py): a build summarises each run of
    # chunks under one heading, and broad questions — comparison, orientation,
    # open-ended — search those summaries and seat the best SECTION_ROUTE_K
    # sections' passages, each from a different source.
    SECTION_INDEX_ENABLED: bool = True
    SECTION_ROUTE_K: int = 4
    SECTION_ROUTE_PASSAGES: int = 2

    # Contextual retrieval
    CONTEXT_ENABLED: bool = True
    CONTEXT_MAX_CHARS: int = 3000
    CONTEXT_CONCURRENCY: int = 4

    # Reranking. Prefer a real cross-encoder reranker (Cohere) when a key is set;
    # otherwise fall back to scoring in small windows rather than one large, unreliable
    # LLM call over all candidates.
    RERANK_ENABLED: bool = True
    # 75 since structural ingestion made corpora larger (plan 3.6). Checked
    # 2026-09-19 that the filtered HNSW scan returns the full 4 × 75 = 300
    # vector candidates on experts 41, 63 and 66 with iterative scan on; with
    # each query's two best hits added, a rerank stays under Cohere's 100-
    # document search unit.
    RERANK_CANDIDATES: int = 75
    RERANK_WINDOW: int = 8
    COHERE_API_KEY: str = ""
    COHERE_RERANK_MODEL: str = "rerank-v3.5"
    # What the reranker reads (search/service.py): each candidate with its
    # contextual note in front, and optionally the question prefixed with the
    # expert's topic. Measured 2026-09-19 with eval/retrieval.py (k=5, 26
    # Thomism + 15 Anglo-Saxon questions): the note raised MRR 0.718 → 0.777
    # and 0.800 → 0.822 at equal recall; the topic prefix added nothing on
    # Thomism and cost Anglo-Saxon (a long topic string) recall 0.867 → 0.800,
    # MRR 0.822 → 0.700. So the note is on and the prefix off.
    RERANK_WITH_CONTEXT: bool = True
    RERANK_TOPIC_PREFIX: bool = False

    # Relevance floor on reranker scores (chat/agent.py), relative to the
    # question: a passage is kept when it scores at least RELEVANCE_RELATIVE ×
    # the best passage's score, and never below RELEVANCE_FLOOR. The old floor
    # was absolute (0.15), and top scores run 0.10–0.87 across questions — an
    # evaluative or broad question has no passage that "answers" it, so every
    # passage scores low and the prompt was cut to three. Derived from the 20
    # audited answers in `answer_audit_passages` (2026-09-19): 90% of cited
    # passages scored ≥ 0.55× their answer's top score, and the 10th percentile
    # of cited passages was 0.098 absolute. At least max(RELEVANCE_MIN_PASSAGES,
    # max_context_passages // 2) passages are kept whatever they score.
    RELEVANCE_FLOOR: float = 0.04
    RELEVANCE_RELATIVE: float = 0.5
    RELEVANCE_MIN_PASSAGES: int = 3
    # When retrieval counts as weak, which is what runs the second pass: the
    # best passage scores under RELEVANCE_WEAK_TOP, or fewer than
    # RELEVANCE_MIN_STRONG passages clear the relative floor. Separate from
    # what is kept: "is retrieval weak" and "what goes in the prompt" used to
    # be one threshold, so the weaker the retrieval the smaller the prompt.
    RELEVANCE_WEAK_TOP: float = 0.25
    RELEVANCE_MIN_STRONG: int = 5

    # Neighbour expansion (chat/neighbours.py). The best NEIGHBOUR_ANCHORS
    # retrieved passages each bring the chunks either side of them, so an
    # argument that runs across several ~1,000-character chunks reaches the model
    # as an argument and not as its first paragraph. More after than before:
    # prose states a point and then develops it. At most
    # ANCHORS × (BEFORE + AFTER) extra passages, about 250 tokens each;
    # NEIGHBOUR_ANCHORS=0 turns it off.
    NEIGHBOUR_ANCHORS: int = 4
    NEIGHBOUR_BEFORE: int = 1
    NEIGHBOUR_AFTER: int = 2

    # Source validation concurrency limit
    VALIDATE_CONCURRENCY: int = 5

    # ── Validation: second opinion at the margin ─────────────────────────────
    # Sources scored inside the borderline band (see sources/validator.py) get a
    # second, single-source call on a stronger model with a much larger preview,
    # and that verdict stands. Ships off by default: the plan this implements
    # (docs/plans/corpus-quality.md, phase 7) calls for measuring agreement with
    # and without it on the screening golden set before flipping the default,
    # and turning it on is a one-line change once those numbers exist.
    VALIDATE_SECOND_OPINION: bool = False
    # Empty = use CLAUDE_MODEL. Named separately so the reviewer can be pinned
    # while chat's model moves, since the rubric version is tied to the pair.
    VALIDATE_REVIEW_MODEL: str = ""

    # ── Discovery loop ───────────────────────────────────────────────────────
    # Whether discovery may run more than one round, searching again for the key
    # concepts its corpus covers least well until the tier's coverage targets are
    # met or the budget runs out (see experts/coverage.py). Off leaves the
    # single-round behaviour with one gap-fill-shaped round after it.
    #
    # Default on for INTERACTIVE builds and off for BACKGROUND ones: each round
    # of a batched build queues its own Message Batch for up to an hour, so a
    # three-round PRO build could take most of a day. Set explicitly to "true" or
    # "false" to override for every execution mode.
    DISCOVERY_LOOP: DiscoveryLoop = "auto"

    # The triage score a candidate must reach to be fetched at all (priority
    # candidates — must-have works, co-cited snowball finds — are exempt). The
    # count budget stays as the ceiling; this is the quality bar beside it.
    # Without it the fetch walked down the ranked tail until the count filled.
    # If fewer than max(8, budget // 4) candidates reach it in round 0, round 0
    # relaxes to FETCH_SCORE_FLOOR_RELAXED and says so (`floor_relaxed`). 6.0 is
    # a starting point, not a measurement: the triage harness
    # (eval/triage.py) is how it gets calibrated.
    FETCH_SCORE_FLOOR: float = 6.0
    # Share caps on a round's accepted sources, 0 = off (the default). The aim is
    # primary texts present for every concept, not a small share of everything
    # else; set these to cap abstract-only or tertiary sources anyway.
    COMPOSITION_ABSTRACT_SHARE_CAP: float = 0
    COMPOSITION_TERTIARY_SHARE_CAP: float = 0
    # The language the corpus is written in. A fetched source whose text is not
    # in it is dropped before validation — the validator scores what it can read
    # and a Spanish paper passed on a live rebuild. "any" turns the check off.
    CORPUS_LANGUAGE: str = "en"
    FETCH_SCORE_FLOOR_RELAXED: float = 5.0

    # Optional directory for screening captures. When set, every source that
    # reaches validation is written to <dir>/<expert_slug>/<job_id>.jsonl before
    # it is judged, which is the only way to rebuild a screening fixture later:
    # the sources table stores no text and a dropped source has no chunks.
    # Off by default — it writes whole documents to disk.
    SCREENING_CAPTURE_DIR: str = ""

    # Graph extraction batch size (chunks per Claude call). Kept small because full
    # chunk text is now sent (not a 400-char preview) — large batches truncate the
    # tool_use JSON and the whole batch is lost.
    GRAPH_BATCH_SIZE: int = 10
    # Chunks per source that graph extraction reads; the rest are embedded and
    # retrievable but not read for concepts. A primary text cut to 200,000
    # characters is ~200 chunks — a fifth of a STANDARD corpus's graph cost —
    # and its opening chunks carry the concepts its later ones repeat. 0 = all.
    GRAPH_MAX_CHUNKS_PER_SOURCE: int = 80

    # Chunking
    # ~1,000 chars: the whole chunk is shown to the model (it used to see only
    # the first 800 of 1,500, while citing all of it), and a smaller unit is
    # also the better one for a cross-encoder reranker to judge. The overlap is
    # the longest trailing sentence carried into the next chunk.
    CHUNK_SIZE_CHARS: int = 1000
    CHUNK_OVERLAP_CHARS: int = 200

    # ── Supabase Auth ─────────────────────────────────────────────────────────
    # SUPABASE_URL, e.g. https://<project-ref>.supabase.co. When set, the API
    # verifies user access tokens (JWTs) and requires login. When unset, auth is
    # disabled (dev mode) and requests run as the bootstrap admin.
    SUPABASE_URL: str = ""
    # Anon / publishable key — used server-side only, to proxy GoTrue auth calls
    # (OTP request/verify/refresh). Never shipped to clients.
    SUPABASE_ANON_KEY: str = ""
    # Legacy HS256 shared secret. Only used as a fallback when the project has not
    # migrated to asymmetric JWT signing keys (JWKS). Not recommended for prod.
    SUPABASE_JWT_SECRET: str = ""
    # The audience claim Supabase issues on user access tokens.
    SUPABASE_JWT_AUD: str = "authenticated"
    # Email that is treated as the workspace admin: sees experts with no owner
    # (those created before auth existed) and is the identity used in dev mode.
    BOOTSTRAP_ADMIN_EMAIL: str = ""

    # Deployment environment. When "production", the server refuses to start with
    # auth disabled (fail-closed) so a missing SUPABASE_URL can never silently turn
    # every request into the bootstrap admin.
    PERITUS_ENV: str = "development"

    # Whether email login may create brand-new accounts. When false, only users
    # who already exist in Supabase Auth (e.g. invited from the dashboard) can log
    # in — the sign-in endpoint won't provision unknown emails. Default true keeps
    # open signup; set false to run Peritus as an invite-only workspace.
    AUTH_ALLOW_SIGNUP: bool = True

    # Per-IP rate limit for the unauthenticated /auth/otp and /auth/verify
    # endpoints: at most AUTH_RATE_LIMIT requests per AUTH_RATE_WINDOW seconds.
    # Supabase enforces its own per-project limits too; this is a first line.
    AUTH_RATE_LIMIT: int = 10
    AUTH_RATE_WINDOW: float = 60
    # Whether to believe Fly-Client-IP / X-Forwarded-For when deciding which
    # client a request came from. A forwarded header is only as trustworthy as
    # the proxy that set it: run directly, anyone can write one and rotate it to
    # get a fresh rate-limit bucket per request. Empty means "when in
    # production", which is where the Fly proxy is in front.
    TRUST_PROXY_HEADERS: str = ""

    # Allowed CORS origins for browser clients, comma-separated. The TUI/CLI are
    # not browsers and ignore CORS, so this defaults to local dev origins only —
    # widen it explicitly (e.g. "https://app.example.com") for a web client.
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Base URL of the Peritus API server, used by the Python CLI's login command.
    PERITUS_SERVER_URL: str = "http://localhost:8000"

    # ── Background build jobs ────────────────────────────────────────────────
    # Run a build worker inside the API process (convenient for local/single-node
    # dev). In production, run `peritus-worker` as its own process instead.
    RUN_WORKER_IN_PROCESS: bool = False
    # Concurrent builds per worker process. Global concurrency = #workers × this.
    WORKER_CONCURRENCY: int = 2
    # How often a running job writes a liveness heartbeat.
    WORKER_HEARTBEAT_INTERVAL: float = 10
    # A running job whose heartbeat is older than this is considered crashed and requeued.
    WORKER_STALE_TIMEOUT: float = 90
    # Retry budget for a build before it is marked permanently failed.
    WORKER_MAX_ATTEMPTS: int = 3
    # Idle poll interval when there is no work to claim.
    WORKER_POLL_INTERVAL: float = 2
    # Base seconds for exponential retry backoff (base × 2^(attempts-1)).
    WORKER_BACKOFF_BASE: float = 30
    # How often the SSE endpoint polls build_events while tailing a live build.
    JOB_EVENT_POLL_INTERVAL: float = 0.4

    # ── normalisation ────────────────────────────────────────────────────────
    #
    # These ran inline on the old `os.getenv` expressions. They are validators
    # now so that `PICTURE_RANKER=" Heuristic "` still resolves rather than
    # failing the Literal, and so the normalising happens in one place rather
    # than at each point of use.

    @field_validator(
        "BUILD_EXECUTION_DEFAULT",
        "CHAT_EFFORT",
        "PICTURE_RANKER",
        "CORPUS_LANGUAGE",
        "HNSW_ITERATIVE_SCAN",
        "PERITUS_ENV",
        "BOOTSTRAP_ADMIN_EMAIL",
        mode="before",
    )
    @classmethod
    def _normalise_case(cls, v: object) -> object:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("DISCOVERY_LOOP", mode="before")
    @classmethod
    def _normalise_discovery_loop(cls, v: object) -> object:
        """Accept every boolean spelling the builder used to accept itself.

        `experts/builder.discovery_loop_enabled` reads 1/yes/on and 0/no/off as
        well as true/false. Mapping them here means the Literal can stay three
        values wide without narrowing what a deployment may set.
        """
        if not isinstance(v, str):
            return v
        lowered = v.strip().lower()
        if lowered in _TRUTHY:
            return "true"
        if lowered in _FALSEY:
            return "false"
        return lowered

    @field_validator("SUPABASE_URL", mode="before")
    @classmethod
    def _strip_trailing_slash(cls, v: object) -> object:
        """Every Supabase URL is built by appending to this one."""
        return v.rstrip("/") if isinstance(v, str) else v

    @model_validator(mode="after")
    def _resolve_plan_model(self) -> "Settings":
        """Empty PLAN_MODEL means CLAUDE_MODEL.

        The planner makes one call per build that shapes the whole corpus, so
        the strong model is the right default — but it stays separately nameable
        so it can be pinned while chat's model moves.
        """
        if not self.PLAN_MODEL:
            # Bypasses __setattr__ validation, which is off anyway; this is the
            # documented way to assign inside an `after` model validator.
            object.__setattr__(self, "PLAN_MODEL", self.CLAUDE_MODEL)
        return self

    @model_validator(mode="after")
    def _pool_bounds(self) -> "Settings":
        if self.DB_POOL_MAX_SIZE < self.DB_POOL_MIN_SIZE:
            raise ValueError(
                f"DB_POOL_MAX_SIZE ({self.DB_POOL_MAX_SIZE}) is below "
                f"DB_POOL_MIN_SIZE ({self.DB_POOL_MIN_SIZE}); asyncpg refuses the pool."
            )
        return self

    @model_validator(mode="after")
    def _chat_history_bounds(self) -> "Settings":
        if self.CHAT_HISTORY_TRIM_BLOCK > self.CHAT_HISTORY_MAX_MESSAGES:
            raise ValueError(
                f"CHAT_HISTORY_TRIM_BLOCK ({self.CHAT_HISTORY_TRIM_BLOCK}) exceeds "
                f"CHAT_HISTORY_MAX_MESSAGES ({self.CHAT_HISTORY_MAX_MESSAGES}); a trim "
                "would empty the whole window."
            )
        return self

    # ── derived ──────────────────────────────────────────────────────────────

    @property
    def AUTH_ENABLED(self) -> bool:
        """Auth is enforced when a Supabase project is configured."""
        return bool(self.SUPABASE_URL or self.SUPABASE_JWT_SECRET)

    @property
    def IS_PRODUCTION(self) -> bool:
        return self.PERITUS_ENV in ("production", "prod")

    @property
    def TRUST_PROXY(self) -> bool:
        """Whether forwarded client-IP headers may be believed."""
        if self.TRUST_PROXY_HEADERS:
            return self.TRUST_PROXY_HEADERS.lower() in ("1", "true", "yes")
        return self.IS_PRODUCTION

    @property
    def CORS_ORIGINS(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]

    @property
    def SUPABASE_JWKS_URL(self) -> str:
        return f"{self.SUPABASE_URL}/auth/v1/.well-known/jwks.json"

    @property
    def SUPABASE_ISSUER(self) -> str:
        return f"{self.SUPABASE_URL}/auth/v1"

    @property
    def SUPABASE_AUTH_URL(self) -> str:
        return f"{self.SUPABASE_URL}/auth/v1"

    def check_required_vars(self) -> list[str]:
        missing = []
        if not self.DATABASE_URL:
            missing.append("DATABASE_URL")
        if not self.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if not self.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        return missing


def _load() -> Settings:
    """Build the settings, or fail with a message a person can act on.

    Pydantic's own ``ValidationError`` is a traceback that echoes the whole
    input mapping — which here is the environment, secrets included. This
    catches it and reports just the field names and what was wrong with each,
    all of them at once, which is the thing the old `int()`-at-import version
    could never do: it failed on the first bad value and did not say which.
    """
    try:
        return Settings()
    except ValidationError as exc:
        lines = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "(cross-field)"
            lines.append(f"  {field}: {error['msg']}")
        raise RuntimeError(
            "Invalid configuration:\n"
            + "\n".join(lines)
            + "\n\nSee api/.env.example for every setting and its default."
        ) from None


settings = _load()
