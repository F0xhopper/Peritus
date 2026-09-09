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

/// One source in an expert's corpus. Mirrors `SourceOut` in
/// api/src/peritus/api/schemas/sources.py. As with ExpertSummary, the whole
/// payload is deserialized even though the overlay renders only part of it.
#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct SourceOut {
    pub id: i64,
    pub source_type: String,
    pub url: Option<String>,
    pub title: String,
    pub author: Option<String>,
    pub quality_score: Option<f64>,
    pub content_type: Option<String>,
    /// How the source entered the corpus. "upload" means the owner supplied it;
    /// anything else is a fetcher name or a `gapfill:<concept>` marker.
    pub discovered_via: Option<String>,
    pub source_tier: Option<String>,
    pub chunk_count: i64,
}

impl SourceOut {
    pub fn is_user_supplied(&self) -> bool {
        self.discovered_via.as_deref() == Some("upload")
    }
}

/// One key concept measured against the tier's coverage target. `shortfall` is
/// 0 when the target is met and grows with the distance from it, which is how
/// the loop ranks what to search for next.
#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct ConceptCoverage {
    pub concept: String,
    #[serde(default)]
    pub sources: u64,
    #[serde(default)]
    pub source_types: Vec<String>,
    #[serde(default)]
    pub met: bool,
    #[serde(default)]
    pub shortfall: i64,
}

/// Why discovery stopped searching, in the words a person watching a build
/// needs. Mirrors the STOP_* constants in api/src/peritus/experts/builder.py;
/// an unrecognised reason is returned verbatim rather than hidden.
pub fn stop_reason_text(reason: &str) -> String {
    match reason {
        "targets_met" => "every key concept reached its coverage target".into(),
        "max_rounds" => "the round limit for this tier was reached".into(),
        "budget_exhausted" => "the discovery budget was spent".into(),
        "source_limit" => "the source limit for this tier was reached".into(),
        "no_new_candidates" => "the last round found nothing new".into(),
        "acceptance_collapsed" => "new results stopped passing validation".into(),
        "loop_disabled" => "this build ran a single search pass".into(),
        other => other.to_string(),
    }
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
    /// Discovery iterates: round 0 searches the research plan, later rounds
    /// target the concepts furthest from their coverage target. Every per-round
    /// event carries `round`, and it defaults to 0 so a build from before the
    /// loop shipped still parses.
    RoundStarted {
        #[serde(default)] round: u64,
        #[serde(default)] budget: u64,
        #[serde(default)] budget_usd: f64,
        #[serde(default)] weakest: Vec<String>,
    },
    FeedbackQueries {
        #[serde(default)] round: u64,
        #[serde(default)] concepts: Vec<String>,
        #[serde(default)] queries: Vec<String>,
    },
    /// Candidates removed as duplicates before anything was downloaded.
    DedupDone {
        #[serde(default)] round: u64,
        #[serde(default)] candidates: u64,
        #[serde(default)] identity_merged: u64,
        #[serde(default)] url_merged: u64,
        #[serde(default)] seen_skipped: u64,
        #[serde(default)] kept: u64,
    },
    FetcherDone {
        name: String,
        count: u64,
        skipped: bool,
        #[serde(default)] reason: String,
        #[serde(default)] round: u64,
    },
    TriageDone { candidates: u64, ranked: u64, budget: u64, #[serde(default)] round: u64 },
    /// One per fetch wave. `attempted` counts candidates tried (failures
    /// included); `fetched` counts those that yielded a source.
    FetchProgress { fetched: u64, attempted: u64, budget: u64, #[serde(default)] round: u64 },
    FetchDone {
        fetched: u64,
        budget: u64,
        #[serde(default)] round: u64,
        #[serde(default)] content_duplicates: u64,
    },
    SnowballDone {
        added: u64,
        #[serde(default)] round: u64,
        #[serde(default)] backward: u64,
        #[serde(default)] forward: u64,
    },
    // Validator scores are 0–10 (see validator.py's rubric).
    SourceValidated { title: String, passed: bool, #[serde(default)] q: f64, #[serde(default)] r: f64 },
    /// A borderline first-pass verdict re-examined by a stronger model, whose
    /// score replaces it. `first_q`/`first_r` are null when the first pass
    /// errored rather than scored.
    SourceReviewed {
        title: String,
        passed: bool,
        #[serde(default)] q: f64,
        #[serde(default)] r: f64,
        #[serde(default)] first_q: Option<f64>,
        #[serde(default)] first_r: Option<f64>,
        #[serde(default)] reversed: bool,
    },
    ValidateDone { passed: u64, dropped: u64, #[serde(default)] round: u64 },
    /// The corpus measured against this tier's per-concept coverage targets,
    /// once per round.
    CoverageReport {
        #[serde(default)] round: u64,
        #[serde(default)] met: bool,
        #[serde(default)] concepts: Vec<ConceptCoverage>,
        #[serde(default)] spent_usd: f64,
        #[serde(default)] budget_usd: f64,
    },
    /// Terminal for discovery, not for the build. `stop_reason` says whether
    /// the search finished or gave up, and why.
    DiscoveryDone {
        #[serde(default)] rounds: u64,
        #[serde(default)] stop_reason: String,
        #[serde(default)] accepted: u64,
        #[serde(default)] rejected: u64,
        #[serde(default)] spent_usd: f64,
        #[serde(default)] budget_usd: f64,
    },
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

    // The discovery loop's events, pinned to the payloads builder.py writes.
    // The TUI's funnel sums across rounds, so `round` has to survive parsing —
    // a build whose later rounds silently defaulted to 0 would report only its
    // last round's numbers.
    #[test]
    fn discovery_loop_events_parse_with_their_round() {
        let started = r#"{"type":"round_started","round":1,"budget":15,"budget_usd":3.0,
            "targets":{"min_sources":2,"min_source_types":2,"require_non_tertiary":true,"max_rounds":2},
            "weakest":["apatheia"]}"#;
        assert!(matches!(
            serde_json::from_str::<BuildEvent>(started).unwrap(),
            BuildEvent::RoundStarted { round: 1, budget: 15, .. }
        ));

        let dedup = r#"{"type":"dedup_done","round":1,"candidates":40,"identity_merged":3,
            "url_merged":2,"seen_skipped":9,"kept":26}"#;
        assert!(matches!(
            serde_json::from_str::<BuildEvent>(dedup).unwrap(),
            BuildEvent::DedupDone { round: 1, identity_merged: 3, seen_skipped: 9, .. }
        ));

        let validate = r#"{"type":"validate_done","round":2,"passed":7,"dropped":4}"#;
        assert!(matches!(
            serde_json::from_str::<BuildEvent>(validate).unwrap(),
            BuildEvent::ValidateDone { round: 2, passed: 7, dropped: 4 }
        ));

        let done = r#"{"type":"discovery_done","rounds":2,"stop_reason":"targets_met",
            "accepted":21,"rejected":13,"spent_usd":1.2,"estimated_ingest_usd":0.9,
            "budget_usd":3.0,"rubric_version":"v5-structured-q5r6","coverage":{}}"#;
        match serde_json::from_str::<BuildEvent>(done).unwrap() {
            BuildEvent::DiscoveryDone { rounds, stop_reason, accepted, .. } => {
                assert_eq!(rounds, 2);
                assert_eq!(accepted, 21);
                assert_eq!(stop_reason_text(&stop_reason), "every key concept reached its coverage target");
            }
            other => panic!("expected DiscoveryDone, got {:?}", other),
        }
    }

    // Builds from before the loop emit these without a `round`, and must keep
    // parsing — the funnel treats a missing round as round 0.
    #[test]
    fn pre_loop_events_still_parse_without_round() {
        let triage = r#"{"type":"triage_done","candidates":50,"ranked":30,"budget":30}"#;
        assert!(matches!(
            serde_json::from_str::<BuildEvent>(triage).unwrap(),
            BuildEvent::TriageDone { round: 0, candidates: 50, .. }
        ));
        let snowball = r#"{"type":"snowball_done","added":3}"#;
        assert!(matches!(
            serde_json::from_str::<BuildEvent>(snowball).unwrap(),
            BuildEvent::SnowballDone { added: 3, round: 0, backward: 0, forward: 0 }
        ));
    }

    #[test]
    fn source_reviewed_carries_both_verdicts() {
        let raw = r#"{"type":"source_reviewed","title":"On Being and Essence","source_type":"web",
            "first_q":5.5,"first_r":5.5,"q":7.0,"r":8.0,"passed":true,"reversed":true,
            "review_model":"claude-sonnet-5"}"#;
        match serde_json::from_str::<BuildEvent>(raw).unwrap() {
            BuildEvent::SourceReviewed { first_q, q, reversed, passed, .. } => {
                assert_eq!(first_q, Some(5.5));
                assert_eq!(q, 7.0);
                assert!(reversed && passed);
            }
            other => panic!("expected SourceReviewed, got {:?}", other),
        }
    }

    // An errored first pass has no scores to report; null must not become 0.0,
    // which would read as "the model scored it zero".
    #[test]
    fn source_reviewed_tolerates_a_first_pass_that_never_scored() {
        let raw = r#"{"type":"source_reviewed","title":"x","source_type":"web",
            "first_q":null,"first_r":null,"q":6.0,"r":7.0,"passed":true,"reversed":false,
            "review_model":"claude-sonnet-5"}"#;
        assert!(matches!(
            serde_json::from_str::<BuildEvent>(raw).unwrap(),
            BuildEvent::SourceReviewed { first_q: None, first_r: None, .. }
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
