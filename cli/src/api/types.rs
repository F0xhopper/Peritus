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

#[derive(Debug, Clone, Serialize)]
pub struct BuildRequest {
    pub topic: String,
    pub tier: String,
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
    BuildStarted { attempt: u32, max_attempts: u32 },
    Stage { stage: u8, name: String, #[serde(default)] total: u64, #[serde(default)] total_batches: u64 },
    PlanReady { key_concepts: Vec<String> },
    DiscoveryStarted { fetchers: Vec<String>, active: Vec<String> },
    FetcherDone { name: String, count: u64, skipped: bool },
    SnowballDone { added: u64 },
    // Validator scores are 0–10 (see validator.py's rubric).
    SourceValidated { title: String, passed: bool, #[serde(default)] q: f64, #[serde(default)] r: f64 },
    ValidateDone { passed: u64, dropped: u64 },
    SourceIngested { title: String, chunks: u64 },
    GraphBatchDone { labels: Vec<String>, edges: u64 },
    EntitiesResolved { merged: u64 },
    PersonaReady { name: String },
    Retry { attempt: u32, max_attempts: u32, message: String },
    Done { source_count: u64, chunk_count: u64, node_count: u64 },
    Cancelled { #[serde(default)] message: String },
    Error { message: String },
    #[serde(other)]
    Unknown,
}

impl BuildEvent {
    /// Terminal events end the build stream; after one, no reconnect is attempted.
    pub fn is_terminal(&self) -> bool {
        matches!(self, BuildEvent::Done { .. } | BuildEvent::Error { .. } | BuildEvent::Cancelled { .. })
    }
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
    Sources { citations: Vec<SourceCitation>, #[serde(default)] has_contradiction: bool },
    Done,
    Error { message: String },
    #[serde(other)]
    Unknown,
}
