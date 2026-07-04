import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    DATABASE_SSL: bool = os.getenv("DATABASE_SSL", "false").lower() == "true"

    # Embeddings
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    EMBED_MODEL: str = os.getenv("EMBED_MODEL", "text-embedding-3-large")
    EMBED_DIM: int = int(os.getenv("EMBED_DIM", "3072"))

    # Anthropic — validation, graph extraction, persona, chat
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

    # Fast model for contextualisation, validation, reranking, coverage
    FAST_MODEL: str = os.getenv("FAST_MODEL", "claude-haiku-4-5-20251001")

    # Research planning — one call per build that shapes the whole corpus, so it
    # defaults to the strong model rather than FAST_MODEL.
    PLAN_MODEL: str = os.getenv("PLAN_MODEL", "") or CLAUDE_MODEL

    # Graph extraction model — Haiku is sufficient and much cheaper than Sonnet
    GRAPH_MODEL: str = os.getenv("GRAPH_MODEL", "claude-haiku-4-5-20251001")

    # ── Anthropic Message Batches ────────────────────────────────────────────
    # Build-pipeline stages (triage, validation, contextualisation, graph
    # extraction) run through the Message Batches API at 50% of standard token
    # prices. Builds are latency-insensitive background jobs, but note batches
    # can take up to ~1 hour to process, so builds run longer when enabled.
    ANTHROPIC_BATCH_ENABLED: bool = os.getenv("ANTHROPIC_BATCH_ENABLED", "true").lower() == "true"
    # Below this many requests a stage just makes live calls — batch overhead
    # and queueing latency aren't worth it for a handful of requests.
    ANTHROPIC_BATCH_MIN_REQUESTS: int = int(os.getenv("ANTHROPIC_BATCH_MIN_REQUESTS", "4"))
    # How often to poll a submitted batch for completion.
    ANTHROPIC_BATCH_POLL_INTERVAL: float = float(os.getenv("ANTHROPIC_BATCH_POLL_INTERVAL", "15"))
    # After this many seconds the batch is cancelled, finished results are
    # harvested, and the remainder falls back to live calls.
    ANTHROPIC_BATCH_TIMEOUT: float = float(os.getenv("ANTHROPIC_BATCH_TIMEOUT", "3600"))

    # ── Chat ─────────────────────────────────────────────────────────────────
    # Cap on client-supplied history messages sent to Claude per turn. Bounds
    # both cost and abuse; the prompt cache makes retained history cheap.
    CHAT_HISTORY_MAX_MESSAGES: int = int(os.getenv("CHAT_HISTORY_MAX_MESSAGES", "20"))

    # Source fetchers
    EXA_API_KEY: str = os.getenv("EXA_API_KEY", "")

    # Mistral OCR (PDF parsing)
    MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
    MISTRAL_OCR_MODEL: str = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")

    # Contextual retrieval
    CONTEXT_ENABLED: bool = os.getenv("CONTEXT_ENABLED", "true").lower() == "true"
    CONTEXT_MAX_CHARS: int = int(os.getenv("CONTEXT_MAX_CHARS", "3000"))
    CONTEXT_CONCURRENCY: int = int(os.getenv("CONTEXT_CONCURRENCY", "4"))

    # Reranking. Prefer a real cross-encoder reranker (Cohere) when a key is set;
    # otherwise fall back to scoring in small windows rather than one large, unreliable
    # LLM call over all candidates.
    RERANK_ENABLED: bool = os.getenv("RERANK_ENABLED", "true").lower() == "true"
    RERANK_CANDIDATES: int = int(os.getenv("RERANK_CANDIDATES", "50"))
    RERANK_WINDOW: int = int(os.getenv("RERANK_WINDOW", "8"))
    COHERE_API_KEY: str = os.getenv("COHERE_API_KEY", "")
    COHERE_RERANK_MODEL: str = os.getenv("COHERE_RERANK_MODEL", "rerank-v3.5")

    # Source validation concurrency limit
    VALIDATE_CONCURRENCY: int = int(os.getenv("VALIDATE_CONCURRENCY", "5"))

    # Graph extraction batch size (chunks per Claude call). Kept small because full
    # chunk text is now sent (not a 400-char preview) — large batches truncate the
    # tool_use JSON and the whole batch is lost.
    GRAPH_BATCH_SIZE: int = int(os.getenv("GRAPH_BATCH_SIZE", "15"))

    # Chunking
    CHUNK_SIZE_CHARS: int = int(os.getenv("CHUNK_SIZE_CHARS", "1500"))
    CHUNK_OVERLAP_CHARS: int = int(os.getenv("CHUNK_OVERLAP_CHARS", "200"))

    # API auth (legacy shared key — retained for backwards compatibility)
    PERITUS_API_KEY_HASH: str = os.getenv("PERITUS_API_KEY_HASH", "")

    # ── Supabase Auth ─────────────────────────────────────────────────────────
    # SUPABASE_URL, e.g. https://<project-ref>.supabase.co. When set, the API
    # verifies user access tokens (JWTs) and requires login. When unset, auth is
    # disabled (dev mode) and requests run as the bootstrap admin.
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").rstrip("/")
    # Anon / publishable key — used server-side only, to proxy GoTrue auth calls
    # (OTP request/verify/refresh). Never shipped to clients.
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
    # Legacy HS256 shared secret. Only used as a fallback when the project has not
    # migrated to asymmetric JWT signing keys (JWKS). Not recommended for prod.
    SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")
    # The audience claim Supabase issues on user access tokens.
    SUPABASE_JWT_AUD: str = os.getenv("SUPABASE_JWT_AUD", "authenticated")
    # Email that is treated as the workspace admin: sees experts with no owner
    # (those created before auth existed) and is the identity used in dev mode.
    BOOTSTRAP_ADMIN_EMAIL: str = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").lower()

    # Deployment environment. When "production", the server refuses to start with
    # auth disabled (fail-closed) so a missing SUPABASE_URL can never silently turn
    # every request into the bootstrap admin.
    PERITUS_ENV: str = os.getenv("PERITUS_ENV", "development").lower()

    # Whether email login may create brand-new accounts. When false, only users
    # who already exist in Supabase Auth (e.g. invited from the dashboard) can log
    # in — the sign-in endpoint won't provision unknown emails. Default true keeps
    # open signup; set false to run Peritus as an invite-only workspace.
    AUTH_ALLOW_SIGNUP: bool = os.getenv("AUTH_ALLOW_SIGNUP", "true").lower() == "true"

    # Per-IP rate limit for the unauthenticated /auth/otp and /auth/verify
    # endpoints: at most AUTH_RATE_LIMIT requests per AUTH_RATE_WINDOW seconds.
    # Supabase enforces its own per-project limits too; this is a first line.
    AUTH_RATE_LIMIT: int = int(os.getenv("AUTH_RATE_LIMIT", "10"))
    AUTH_RATE_WINDOW: float = float(os.getenv("AUTH_RATE_WINDOW", "60"))

    # Allowed CORS origins for browser clients, comma-separated. The TUI/CLI are
    # not browsers and ignore CORS, so this defaults to local dev origins only —
    # widen it explicitly (e.g. "https://app.example.com") for a web client.
    CORS_ALLOW_ORIGINS: str = os.getenv(
        "CORS_ALLOW_ORIGINS", "http://localhost:3000,http://localhost:8000"
    )

    # Base URL of the Peritus API server, used by the Python CLI's login command.
    PERITUS_SERVER_URL: str = os.getenv("PERITUS_SERVER_URL", "http://localhost:8000")

    # ── Background build jobs ────────────────────────────────────────────────
    # Run a build worker inside the API process (convenient for local/single-node
    # dev). In production, run `peritus-worker` as its own process instead.
    RUN_WORKER_IN_PROCESS: bool = os.getenv("RUN_WORKER_IN_PROCESS", "false").lower() == "true"
    # Concurrent builds per worker process. Global concurrency = #workers × this.
    WORKER_CONCURRENCY: int = int(os.getenv("WORKER_CONCURRENCY", "2"))
    # How often a running job writes a liveness heartbeat.
    WORKER_HEARTBEAT_INTERVAL: float = float(os.getenv("WORKER_HEARTBEAT_INTERVAL", "10"))
    # A running job whose heartbeat is older than this is considered crashed and requeued.
    WORKER_STALE_TIMEOUT: float = float(os.getenv("WORKER_STALE_TIMEOUT", "90"))
    # Retry budget for a build before it is marked permanently failed.
    WORKER_MAX_ATTEMPTS: int = int(os.getenv("WORKER_MAX_ATTEMPTS", "3"))
    # Idle poll interval when there is no work to claim.
    WORKER_POLL_INTERVAL: float = float(os.getenv("WORKER_POLL_INTERVAL", "2"))
    # Base seconds for exponential retry backoff (base × 2^(attempts-1)).
    WORKER_BACKOFF_BASE: float = float(os.getenv("WORKER_BACKOFF_BASE", "30"))
    # How often the SSE endpoint polls build_events while tailing a live build.
    JOB_EVENT_POLL_INTERVAL: float = float(os.getenv("JOB_EVENT_POLL_INTERVAL", "0.4"))

    @property
    def AUTH_ENABLED(self) -> bool:
        """Auth is enforced when a Supabase project is configured."""
        return bool(self.SUPABASE_URL or self.SUPABASE_JWT_SECRET)

    @property
    def IS_PRODUCTION(self) -> bool:
        return self.PERITUS_ENV in ("production", "prod")

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


settings = Settings()
