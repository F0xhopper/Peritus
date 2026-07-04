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
