use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize)]
pub struct ExpertSummary {
    pub id: u64,
    pub name: String,
    pub topic: String,
    pub status: String,
    pub persona_name: Option<String>,
    pub source_count: u64,
    pub chunk_count: u64,
    pub node_count: u64,
    pub edge_count: u64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ExpertDetail {
    #[serde(flatten)]
    pub summary: ExpertSummary,
    pub persona_bio: Option<String>,
    pub persona_style: Option<String>,
    pub avg_quality: Option<f64>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct BuildRequest {
    pub topic: String,
    pub depth: String,
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

#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum BuildEvent {
    Stage { stage: u8, name: String, #[serde(default)] total: u64, #[serde(default)] total_batches: u64 },
    PlanReady { key_concepts: Vec<String> },
    DiscoveryStarted { fetchers: Vec<String>, active: Vec<String> },
    FetcherDone { name: String, count: u64, skipped: bool },
    SnowballDone { added: u64 },
    SourceValidated { title: String, passed: bool, #[serde(default)] score: f64 },
    ValidateDone { passed: u64, dropped: u64 },
    SourceIngested { title: String, chunks: u64, total_chunks: u64 },
    GraphBatchDone { labels: Vec<String>, edges: u64 },
    EntitiesResolved { merged: u64 },
    PersonaReady { name: String },
    Done { expert_id: u64, source_count: u64, chunk_count: u64, node_count: u64, edge_count: u64 },
    Error { message: String },
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ChatEvent {
    Token { text: String },
    Sources { citations: Vec<String> },
    Done,
    Error { message: String },
    #[serde(other)]
    Unknown,
}
