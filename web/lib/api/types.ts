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
