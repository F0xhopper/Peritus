// Mirrors api/src/peritus/api/schemas/experts.py + domain.py.
// `name` is the URL-safe slug (e.g. "stoic-philosophy"), not a display title —
// `topic` is the human-readable topic the expert was built from.

export type ExpertStatus = "queued" | "building" | "ready" | "failed";
export type ExpertTier = "lite" | "standard" | "pro";

export interface ExpertSummary {
  id: number;
  name: string;
  topic: string;
  status: ExpertStatus;
  tier: ExpertTier;
  persona_name: string | null;
  persona_bio: string | null;
  persona_style: string | null;
  avg_quality: number | null;
  key_concepts: string[];
  source_count: number;
  chunk_count: number;
  node_count: number;
  edge_count: number;
  source_type_counts: Record<string, number>;
  created_at: string;
}

export interface ExpertDetail extends ExpertSummary {
  error: string | null;
  updated_at: string;
}

// Mirrors api/src/peritus/api/schemas/conversations.py.

/** One cited passage. `n` matches the inline [n] marker in the answer text. */
export interface Citation {
  n: number;
  label: string;
  source_id: number | null;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  has_contradiction: boolean;
  /** The stream died before completing — the content is a partial answer. */
  interrupted: boolean;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  expert_id: number;
  /** experts.name — the URL slug, not a display title. */
  expert_slug: string;
  expert_topic: string;
  expert_persona_name: string | null;
  expert_status: ExpertStatus;
  title: string | null;
  message_count: number;
  created_at: string;
  last_message_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[];
}

// SSE protocol emitted by POST /conversations/{id}/messages. Identical to the
// stateless endpoint's, plus a leading `meta` event.
export type ChatStreamEvent =
  | { type: "meta"; conversation_id: string; title: string | null }
  | { type: "status"; message: string }
  | { type: "token"; text: string }
  | { type: "sources"; citations: Citation[]; has_contradiction: boolean }
  | { type: "done" }
  | { type: "error"; message: string };

// ── Build jobs ───────────────────────────────────────────────────────────────
// Mirrors api/src/peritus/api/schemas/experts.py:BuildRequest and the event
// vocabulary emitted by experts/builder.py + jobs/worker.py.

export interface BuildRequest {
  topic: string;
  tier: ExpertTier;
  /** Fetcher allowlist. Omit/null for "let the planner choose". */
  sources?: string[] | null;
}

/** The fetchers `_build_fetchers` knows about, in its own declaration order. */
export const FETCHERS = [
  "wikipedia",
  "gutenberg",
  "arxiv",
  "pdf",
  "youtube",
  "exa",
  "web",
  "reddit",
  "thought_leaders",
] as const;

export type Fetcher = (typeof FETCHERS)[number];

/** Pipeline stages, in the order builder.py emits them. `resolve` reuses
 * stage index 4 (it is the back half of the graph stage), so the checklist is
 * keyed by name rather than by the numeric `stage` field. */
export const BUILD_STAGES = [
  "plan",
  "discover",
  "validate",
  "chunk",
  "graph",
  "resolve",
  "persona",
] as const;

export type BuildStage = (typeof BUILD_STAGES)[number];

/** `seq` is the SSE `id:` line — the build log's cursor. Optional because it
 * is attached by the frame parser rather than sent inside the JSON payload. */
export type BuildEvent = { seq?: number } & (
  | { type: "build_started"; attempt: number; max_attempts: number }
  | { type: "stage"; stage: number; name: string; total?: number; total_batches?: number }
  | { type: "plan_ready"; key_concepts: string[] }
  | { type: "snowball_done"; added: number }
  | { type: "discovery_started"; fetchers: string[]; active: string[] }
  | { type: "fetcher_done"; name: string; count: number; skipped: boolean; reason: string; queries: number }
  | { type: "triage_done"; candidates: number; ranked: number; budget: number }
  | { type: "fetch_done"; fetched: number; budget: number }
  // `q` is quality, `r` is relevance — both 0-10, both thresholded server-side
  // in sources/validator.py, which is what sets `passed`.
  | { type: "source_validated"; title: string; source_type: string; q: number; r: number; passed: boolean; drop_reason?: string | null }
  | { type: "validate_done"; passed: number; dropped: number }
  | { type: "source_ingested"; title: string; chunks: number; total_chunks: number }
  | { type: "graph_batch_done"; labels?: number; edges?: number }
  | { type: "resolve_progress"; merged: number }
  | { type: "entities_resolved"; merged: number }
  | { type: "coverage_gaps"; gaps: string[] }
  | { type: "persona_ready"; name: string }
  | { type: "retry"; attempt: number; message?: string }
  // Terminal — see jobs/domain.py:TERMINAL_EVENT_TYPES.
  | { type: "done"; expert_id: number; source_count: number; chunk_count: number; node_count: number; edge_count: number; persona_name?: string | null; avg_quality?: number | null }
  | { type: "error"; message: string }
  | { type: "cancelled"; message: string }
);

export const TERMINAL_BUILD_EVENTS = ["done", "error", "cancelled"] as const;

export interface BuildStatus {
  job_id: number;
  expert_status: ExpertStatus;
  job_status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  updated_at: string;
}
