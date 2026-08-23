use std::collections::HashMap;
use serde::{Deserialize, Serialize};

// Mirrors the API's ExpertSummary schema; some fields are deserialized but not
// (yet) rendered anywhere.
#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct ExpertSummary {
    pub id: u64,
    pub name: String,
    pub topic: String,
    pub status: String,
    // Retrieval readiness: pending | chat_ready | graph_ready. The API is
    // explicit that the chat affordance gates on THIS, not on `status` — an
    // expert answers questions a full stage before its build job finishes.
    #[serde(default = "default_readiness")]
    pub readiness: String,
    #[serde(default)]
    pub graph_expanded: bool,
    #[serde(default = "default_tier")]
    pub tier: String,
    pub persona_name: Option<String>,
    pub persona_bio: Option<String>,
    pub persona_style: Option<String>,
    pub avg_quality: Option<f64>,
    #[serde(default)]
    pub key_concepts: Vec<String>,
    pub source_count: u64,
    pub chunk_count: u64,
    pub node_count: u64,
    pub edge_count: u64,
    #[serde(default)]
    pub source_type_counts: HashMap<String, u64>,
    pub created_at: String,
}

fn default_tier() -> String { "standard".to_string() }
fn default_readiness() -> String { "pending".to_string() }

impl ExpertSummary {
    /// Whether this expert can answer questions right now — matches the
    /// server's gate (`readiness.can_chat`), with a status fallback for older
    /// servers that don't send readiness.
    pub fn can_chat(&self) -> bool {
        matches!(self.readiness.as_str(), "chat_ready" | "graph_ready")
            || self.status == "ready"
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct BuildRequest {
    pub topic: String,
    // None = let the server resolve the deepest tier the account's plan and
    // balance afford ("Auto" in the tier picker).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tier: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChatRequest {
    pub question: String,
    pub history: Vec<ChatMessage>,
}

// Field names/shapes must match the payloads written to build_events by
// builder.py and worker.py — see api/src/peritus/experts/builder.py.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum BuildEvent {
    /// First event in the durable log: which expert this stream belongs to.
    /// The server-assigned slug is authoritative (collisions auto-suffix), so
    /// clients must prefer it over their own slugified guess.
    Created { slug: String, #[serde(default)] tier: String },
    BuildStarted { attempt: u32, max_attempts: u32 },
    ExecutionMode { mode: String, #[serde(default)] batched: bool },
    Stage { stage: u8, name: String, #[serde(default)] total: u64, #[serde(default)] total_batches: u64 },
    PlanReady { key_concepts: Vec<String> },
    DiscoveryStarted { fetchers: Vec<String>, active: Vec<String> },
    FetcherDone { name: String, count: u64, skipped: bool, #[serde(default)] reason: String },
    TriageDone { candidates: u64, ranked: u64, budget: u64 },
    /// One per fetch wave. `attempted` counts candidates tried (failures
    /// included); `fetched` counts those that yielded a source.
    FetchProgress { fetched: u64, attempted: u64, budget: u64 },
    FetchDone { fetched: u64, budget: u64 },
    SnowballDone { added: u64 },
    // Validator scores are 0–10 (see validator.py's rubric).
    SourceValidated { title: String, passed: bool, #[serde(default)] q: f64, #[serde(default)] r: f64 },
    ValidateDone { passed: u64, dropped: u64 },
    CoverageGaps { gaps: Vec<String> },
    GapfillDone { added: u64, #[serde(default)] still_uncovered: Vec<String> },
    CorpusWarning { message: String },
    SourceIngested { title: String, chunks: u64 },
    /// The expert answers questions from here on — a full stage before `done`.
    ChatReady { sources: u64, chunks: u64 },
    GraphBatchDone { labels: Vec<String>, edges: u64 },
    ResolveProgress { merged: u64 },
    EntitiesResolved { merged: u64 },
    GraphReady { nodes: u64, edges: u64 },
    /// An enrichment stage (graph/persona) failed; the build continues degraded.
    StageDegraded { stage: String, message: String },
    PersonaReady { name: String },
    Retry { attempt: u32, max_attempts: u32, message: String },
    Done {
        source_count: u64,
        chunk_count: u64,
        node_count: u64,
        #[serde(default)] edge_count: u64,
        #[serde(default)] persona_name: Option<String>,
    },
    Cancelled { #[serde(default)] message: String },
    Error {
        message: String,
        #[serde(default)] code: Option<String>,
        #[serde(default)] spent_usd: Option<f64>,
        #[serde(default)] cap_usd: Option<f64>,
    },
    #[serde(other)]
    Unknown,
}

impl BuildEvent {
    /// Terminal events end the build stream; after one, no reconnect is attempted.
    pub fn is_terminal(&self) -> bool {
        matches!(self, BuildEvent::Done { .. } | BuildEvent::Error { .. } | BuildEvent::Cancelled { .. })
    }
}

// ── Auth ─────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize)]
pub struct OtpRequestBody {
    pub email: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct VerifyBody {
    pub email: String,
    pub token: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct RefreshBody {
    pub refresh_token: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SessionUser {
    #[allow(dead_code)]
    pub id: String,
    #[serde(default)]
    pub email: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Session {
    pub access_token: String,
    pub refresh_token: String,
    #[serde(default)]
    pub expires_in: i64,
    #[serde(default)]
    pub expires_at: Option<i64>,
    pub user: SessionUser,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SourceCitation {
    pub n: u32,
    pub label: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ChatEvent {
    Token { text: String },
    Status { message: String },
    // The payload also carries `has_contradiction`; serde drops unlisted
    // fields, and no client surface renders it any more (see chat.rs).
    Sources {
        citations: Vec<SourceCitation>,
        // `[n]` markers the model invented that resolve to no real passage.
        // The server flags them so clients can mark them, not render them as
        // legitimate citations.
        #[serde(default)] dangling_citations: Vec<u32>,
    },
    Done,
    Error { message: String },
    #[serde(other)]
    Unknown,
}

#[cfg(test)]
mod tests {
    use super::*;

    // Payloads below are verbatim from a real server build stream — they pin
    // the serde field names against what builder.py/worker.py actually emit.

    #[test]
    fn created_event_parses() {
        let raw = r#"{"slug": "spaced-repetition-and-memory-retention", "tier": "lite", "type": "created", "topic": "spaced repetition and memory retention", "job_id": 1, "expert_id": 1}"#;
        match serde_json::from_str::<BuildEvent>(raw).unwrap() {
            BuildEvent::Created { slug, tier } => {
                assert_eq!(slug, "spaced-repetition-and-memory-retention");
                assert_eq!(tier, "lite");
            }
            other => panic!("wrong variant: {:?}", other),
        }
    }

    #[test]
    fn chat_ready_event_parses() {
        let raw = r#"{"type": "chat_ready", "chunks": 576, "sources": 18, "graph_expanded": false}"#;
        match serde_json::from_str::<BuildEvent>(raw).unwrap() {
            BuildEvent::ChatReady { sources, chunks } => {
                assert_eq!((sources, chunks), (18, 576));
            }
            other => panic!("wrong variant: {:?}", other),
        }
    }

    #[test]
    fn spend_cap_error_parses() {
        let raw = r#"{"code": "spend_cap_exceeded", "type": "error", "cap_usd": 1.0, "message": "Build exceeded its spend cap: $1.02 of $1.00.", "spent_usd": 1.0226}"#;
        match serde_json::from_str::<BuildEvent>(raw).unwrap() {
            BuildEvent::Error { code, spent_usd, cap_usd, .. } => {
                assert_eq!(code.as_deref(), Some("spend_cap_exceeded"));
                assert!(spent_usd.unwrap() > 1.0 && cap_usd.unwrap() == 1.0);
            }
            other => panic!("wrong variant: {:?}", other),
        }
    }

    #[test]
    fn plain_error_still_parses_without_cap_fields() {
        let raw = r#"{"type": "error", "message": "boom"}"#;
        assert!(matches!(
            serde_json::from_str::<BuildEvent>(raw).unwrap(),
            BuildEvent::Error { code: None, .. }
        ));
    }

    #[test]
    fn stage_degraded_and_gapfill_parse() {
        let degraded = r#"{"type": "stage_degraded", "stage": "persona", "message": "x"}"#;
        assert!(matches!(
            serde_json::from_str::<BuildEvent>(degraded).unwrap(),
            BuildEvent::StageDegraded { .. }
        ));
        let gapfill = r#"{"type": "gapfill_done", "added": 6, "still_uncovered": []}"#;
        assert!(matches!(
            serde_json::from_str::<BuildEvent>(gapfill).unwrap(),
            BuildEvent::GapfillDone { added: 6, .. }
        ));
    }

    #[test]
    fn unknown_event_types_do_not_fail() {
        let raw = r#"{"type": "some_future_event", "whatever": 1}"#;
        assert!(matches!(
            serde_json::from_str::<BuildEvent>(raw).unwrap(),
            BuildEvent::Unknown
        ));
    }

    #[test]
    fn readiness_gates_chat_with_status_fallback() {
        let mut e: ExpertSummary = serde_json::from_str(
            r#"{"id":1,"name":"x","topic":"x","status":"building","readiness":"chat_ready",
                "persona_name":null,"persona_bio":null,"persona_style":null,"avg_quality":null,
                "source_count":1,"chunk_count":1,"node_count":0,"edge_count":0,"created_at":"now"}"#,
        ).unwrap();
        assert!(e.can_chat());
        e.readiness = "pending".into();
        assert!(!e.can_chat());
        // Older servers without readiness: fall back to status.
        e.status = "ready".into();
        assert!(e.can_chat());
    }

    #[test]
    fn build_request_omits_tier_when_auto() {
        let auto = BuildRequest { topic: "x".into(), tier: None };
        assert_eq!(serde_json::to_string(&auto).unwrap(), r#"{"topic":"x"}"#);
        let explicit = BuildRequest { topic: "x".into(), tier: Some("lite".into()) };
        assert!(serde_json::to_string(&explicit).unwrap().contains("lite"));
    }
}
