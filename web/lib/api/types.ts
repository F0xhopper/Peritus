// Mirrors api/src/peritus/api/schemas/auth.py::MeResponse.
export interface User {
  id: string;
  email: string | null;
  is_admin: boolean;
}

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
  | {
      type: "sources";
      citations: Citation[];
      has_contradiction: boolean;
      /** Inline `[n]` markers in the answer that point at no retrieved passage —
       * the model invented a reference. They cannot be removed from the prose
       * (tokens are already streamed), so the renderer must not present them as
       * citations. Empty on a well-grounded answer. */
      dangling_citations: number[];
    }
  // The answer's retrieval trail: how many passages were retrieved, how many
  // reached the prompt, and how many the answer actually cited. A trail, never
  // a score — do not render it as a percentage.
  | {
      type: "retrieval_audit";
      audit_id: string | null;
      persisted: boolean;
      passages: {
        retrieved: number;
        duplicate_hits: number;
        unique: number;
        in_context: number;
        cited: number;
        not_in_context: number;
        context_cap: number | null;
      };
      sources: { in_context: number; cited: number };
      [key: string]: unknown;
    }
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
  "pubmed",
  "openalex",
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
  // Corpus composition, emitted after validation when the passing set is
  // overwhelmingly tertiary (summaries/reviews rather than primary material).
  // A warning, not a failure — the build continues; see builder.py.
  | {
      type: "corpus_warning";
      reason: string;
      message: string;
      primary: number;
      secondary: number;
      tertiary: number;
      unclassified: number;
      classified: number;
    }
  | { type: "gapfill_done"; added: number; still_uncovered: string[] }
  | { type: "chat_ready"; sources: number; chunks: number; graph_expanded: boolean }
  | { type: "graph_ready"; nodes: number; edges: number; graph_expanded: boolean }
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

// ── audit surface ───────────────────────────────────────────────────────────
// Shapes documented in docs/audit-api.md and assembled by
// api/src/peritus/audit/service.py. The service returns plain dicts, so these
// are hand-maintained against that document.

/** A count the system does not persist, with the reason it is absent.
 *
 * The whole point of this shape is that it is NOT zero: rendering an
 * unrecorded count as 0 would fabricate a number in an evidence record. Every
 * consumer must branch on `count === null`. */
export interface AuditCount {
  count: number | null;
  unavailable_reason?: string;
  source?: string;
  note?: string;
  [key: string]: unknown;
}

export type SourceDecision = "all" | "accepted" | "rejected";

export type SourceSort =
  | "decision"
  | "quality"
  | "relevance"
  | "title"
  | "type"
  | "discovered_via"
  | "added";

/** `plan` = planned first pass, `snowball` = followed citations out of a
 * discovered preprint, `gapfill` = a search that ran only because a named
 * concept had no accepted source. The last is the differentiating one. */
export type DiscoveryMethod = "plan" | "snowball" | "gapfill" | null;

export interface SourceRow {
  id: number;
  decision: "accepted" | "rejected";
  title: string | null;
  url: string | null;
  author: string | null;
  source_type: string | null;
  content_type: string | null;
  difficulty: number | null;
  quality_score: number | null;
  relevance_score: number | null;
  /** Populated on rejected rows only. */
  drop_reason: string | null;
  validator_model: string | null;
  rubric_version: string | null;
  discovered_via: string | null;
  discovery_method: DiscoveryMethod;
  gap_filled_for_concept: string | null;
  covered_concepts: string[];
  key_claims: string[];
  passage_count: number;
  created_at: string;
}

export interface SearchProvenanceRow {
  discovered_via: string;
  method: DiscoveryMethod;
  concept: string | null;
  considered: number;
  accepted: number;
  rejected: number;
  accepted_mean_quality: number | null;
  accepted_mean_relevance: number | null;
  source_types: string[];
}

export interface CorpusReport {
  expert: { name: string; topic: string; tier: string; [k: string]: unknown };
  method_statement: string;
  totals: {
    considered: number;
    accepted: number;
    rejected: number;
    acceptance_rate: number | null;
    accepted_with_passages: number | null;
    accepted_without_passages: number | null;
    passages_total: number | null;
  };
  scores: {
    accepted: Record<string, number | null>;
    rejected: { mean_quality: number | null; mean_relevance: number | null };
    distribution: Record<string, { accepted: number[]; rejected: number[] }>;
    bin_edges: [number, number][];
  };
  thresholds: {
    quality_min: number;
    relevance_min: number;
    current_rubric_version: string;
    note: string;
  };
  rubric_versions: {
    rubric_version: string | null;
    validator_model: string | null;
    sources: number;
    accepted: number;
    first_seen: string | null;
    last_seen: string | null;
  }[];
  provenance: {
    sources: number;
    complete: boolean;
    missing: Record<string, number>;
    note: string;
  };
  by_source_type: {
    source_type: string;
    considered: number;
    accepted: number;
    rejected: number;
    accepted_mean_quality: number | null;
    accepted_mean_relevance: number | null;
  }[];
  by_discovery_method: {
    method: string;
    considered: number;
    accepted: number;
    rejected: number;
    accepted_mean_quality: number | null;
  }[];
  by_search: {
    searches: SearchProvenanceRow[];
    distinct_searches: number;
    note: string;
  };
  exclusions: {
    by_reason: {
      reason: string | null;
      count: number;
      mean_quality: number | null;
      mean_relevance: number | null;
    }[];
    by_threshold: Record<string, number>;
    by_threshold_meanings: Record<string, string>;
  };
  page: {
    decision: SourceDecision;
    sort: SourceSort;
    limit: number;
    offset: number;
    returned: number;
    total_matching: number;
    has_more: boolean;
  };
  sources: SourceRow[];
}

export type CoverageStrength = "absent" | "thin" | "adequate" | "strong";

export interface CoverageConcept {
  concept: string;
  strength: CoverageStrength;
  needed_gap_fill: boolean;
  on_plan?: boolean;
  [key: string]: unknown;
}

export interface CoverageReport {
  expert: { name: string; topic: string; [k: string]: unknown };
  method_statement: string;
  key_concepts_planned: string[];
  key_concepts_unavailable_reason: string | null;
  classification_rule: string;
  summary: {
    concepts: number;
    absent: number;
    thin: number;
    adequate: number;
    strong: number;
    concepts_needing_gap_fill: number;
    off_plan_concepts: number;
  };
  tagging: {
    accepted_tagged_with_concepts: number;
    accepted_tagged_no_concepts: number;
    accepted_untagged_legacy: number;
    note: string;
  };
  concepts: CoverageConcept[];
}

export interface GraphNode {
  id: number;
  label: string;
  node_type: string | null;
  degree: number;
}

export interface GraphEdge {
  id: number;
  source: number;
  target: number;
  edge_type: string;
  weight: number | null;
}

/** `computed: false` means the concept graph has not been extracted yet — an
 * empty `nodes`/`edges` in that state means "not built", not "empty graph". */
export interface ExpertGraph {
  expert: { name: string; topic: string; [k: string]: unknown };
  computed: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_nodes: number;
  total_edges: number;
  truncated: boolean;
}

/** `computed: false` means the concept graph has not been extracted yet.
 *
 * An empty `contradictions` list in that state means "not analysed yet", NOT
 * "none found" — see the note in docs/audit-api.md. Never collapse the two. */
export interface ContradictionsReport {
  expert: { name: string; topic: string; [k: string]: unknown };
  method_statement?: string;
  computed: boolean;
  readiness: string;
  summary?: {
    contradictions: number;
    concepts_involved: number;
    relationships_total: number;
    share_of_relationships: number | null;
    cross_source_on_page: number;
    within_source_on_page: number;
    undetermined_on_page: number;
  };
  relationship_mix?: { edge_type: string; count: number; mean_weight: number | null }[];
  note?: string;
  unavailable_reason?: string;
  page: {
    limit: number;
    offset: number;
    returned: number;
    total_matching: number | null;
    has_more: boolean;
    passages_per_side?: number;
    excerpt_chars?: number;
  };
  contradictions: ContradictionItem[];
}

export interface ContradictionPassage {
  chunk_id: number;
  sequence_n: number | null;
  excerpt: string | null;
  truncated: boolean;
  context: string | null;
  source_id: number;
  source_title: string | null;
  source_type: string | null;
  source_url: string | null;
  source_author: string | null;
  quality_score: number | null;
  relevance_score: number | null;
  citation: string;
}

export interface ContradictionSide {
  node: {
    id: number;
    label: string | null;
    node_type: string | null;
    description: string | null;
  };
  passage_count: number;
  passages: ContradictionPassage[];
  passages_truncated: boolean;
  missing_passages: number;
}

export interface ContradictionItem {
  edge_id: number;
  weight: number | null;
  properties: Record<string, unknown> | null;
  /** `cross_source` is two different sources disagreeing — the only kind that
   * is a disagreement *between* sources. `within_source` is one source in
   * tension with itself; `undetermined` means one side had no resolvable
   * passage. Label them differently. */
  kind: "cross_source" | "within_source" | "undetermined";
  shared_source_ids: number[];
  side_a: ContradictionSide;
  side_b: ContradictionSide;
}

export interface AnswerAuditHeader {
  audit_id: string;
  conversation_id: string | null;
  question: string;
  subqueries: string[];
  followup_queries: string[];
  coverage_satisfied: boolean | null;
  second_pass: boolean | null;
  passages: {
    retrieved: number;
    duplicate_hits: number;
    unique: number;
    in_context: number;
    cited: number;
    not_in_context: number;
    context_cap: number | null;
  };
  sources: { in_context: number; cited: number };
  contradiction_traversed: boolean | null;
  answer_chars: number;
  created_at: string;
}

export interface AnswerAuditPassage {
  n: number;
  chunk_id: number;
  source_id: number;
  source_title: string | null;
  source_type: string | null;
  quality_score: number | null;
  retrieval_rank: number | null;
  retrieval_score: number | null;
  retrieved_via: string | null;
  disposition: string;
}

export interface AnswerAuditList {
  expert: { name: string; topic: string; [k: string]: unknown };
  disposition_meanings: Record<string, string>;
  page: {
    limit: number;
    offset: number;
    returned: number;
    total_matching: number;
    has_more: boolean;
  };
  audits: AnswerAuditHeader[];
}

export type AnswerAuditDetail = AnswerAuditHeader & {
  expert: { name: string; topic: string; [k: string]: unknown };
  disposition_meanings: Record<string, string>;
  passages: AnswerAuditPassage[];
};

export interface ScreeningFlow {
  expert: { name: string; topic: string; [k: string]: unknown };
  method_statement: string;
  build: {
    job_id: number | null;
    status: string | null;
    tier?: string;
    attempts?: number;
    max_attempts?: number;
    last_error?: string | null;
    started_at?: string;
    finished_at?: string;
    event_log_retained?: boolean;
    unavailable_reason?: string;
    note?: string;
  };
  search_strategy: {
    fetchers: {
      fetcher: string;
      queries_run: number | null;
      candidates_identified: number | null;
      skipped: boolean;
      skip_reason: string | null;
    }[];
    fetchers_available: string[];
    fetchers_run: string[];
    queries_issued: number | null;
    /** Permanently null — the planning stage never persists query strings. */
    query_text: null;
    query_text_unavailable_reason: string;
    searches_recorded_on_sources: number;
    note: string;
  };
  stages: {
    identified: AuditCount;
    screened_at_triage: AuditCount;
    retrieved_full_text: AuditCount;
    assessed_at_validation: AuditCount;
  };
}

// ── credits ──────────────────────────────────────────────────────────────
// See docs/catalog-and-credits.md.

export interface CreditState {
  plan: {
    name: string;
    display_name: string;
    included_credits: number;
    allowed_tiers: string[];
    description: string;
  };
  balance: number;
  granted: number;
  consumed: number;
  /** Credits reserved by an in-flight build. Already excluded from `balance`. */
  held: number;
  credits_enforced: boolean;
  tiers: {
    tier: string;
    credit_cost: number;
    spend_cap_usd: number;
    included_in_plan: boolean;
  }[];
}

export interface LedgerEntry {
  id: number;
  entry_type: string;
  delta: number;
  job_id: number | null;
  tier: string | null;
  reason: string | null;
  source: string;
  cost_usd: number | null;
  created_at: string;
}

/** One source in an expert's corpus. `discovered_via === "upload"` marks
 * material the owner supplied by hand rather than something discovery found. */
export interface CorpusSource {
  id: number;
  source_type: string;
  url: string | null;
  title: string;
  author: string | null;
  quality_score: number | null;
  content_type: string | null;
  discovered_via: string | null;
  source_tier: string | null;
  chunk_count: number;
  created_at: string;
}

/** Returned by the upload/url endpoints once the payload is durably queued.
 * `job_id` is what the client tails on the build-events stream. */
export interface UploadAccepted {
  upload_id: number;
  job_id: number;
  title: string;
  kind: "pdf" | "text" | "url";
}
