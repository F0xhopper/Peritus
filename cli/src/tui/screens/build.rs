use std::collections::VecDeque;
use std::sync::Arc;
use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Modifier, Style},
    text::{Line, Span},
    widgets::{Block, BorderType, Borders, List, ListItem, Paragraph, Wrap},
};
use tokio::sync::{mpsc, Notify};
use futures_util::StreamExt;

use crate::api::client::ApiClient;
use crate::api::types::BuildEvent;
use crate::tui::theme::Theme;
use crate::tui::widgets::spinner;

// Index == backend stage number: 0 plan, 1 discover, 2 validate, 3 chunk/ingest,
// 4 graph, 5 persona. Keep this aligned with builder.py's emitted `stage` values.
const STAGES: &[(&str, &str)] = &[
    ("plan",      "Plan"),
    ("discovery", "Discover"),
    ("validate",  "Validate"),
    ("ingest",    "Ingest"),
    ("graph",     "Graph"),
    ("persona",   "Persona"),
];

#[derive(Debug, Clone, PartialEq)]
// No `Waiting`: a fetcher is either running (`active` in discovery_started),
// finished, or was never planned for this build — and that last case is Skipped,
// not pending. Nothing sits in limbo waiting to start.
pub enum FetcherState { Fetching, Done(u64), Skipped }

pub struct BuildCardInfo {
    pub topic: String,
    pub stage: u8,
    pub stage_label: String,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq)]
enum LogLevel { Stage, Success, Info, Error }

struct LogEntry { at_secs: u64, msg: String, level: LogLevel }

pub struct BuildScreen {
    topic: String,
    tier: String,
    slug: String,
    api: Arc<ApiClient>,
    /// Armed by the first [x]; the second [x] actually cancels.
    pub confirm_cancel: bool,
    cancel_sent: bool,
    /// Written by the cancel task on failure, drained in tick() so a rejected
    /// cancel un-latches instead of showing "Cancelling…" forever.
    cancel_failed: Arc<std::sync::Mutex<Option<String>>>,
    start_time: std::time::Instant,
    /// Reset on every Stage event — drives the per-stage timer in the header.
    stage_started: std::time::Instant,
    stage: u8,
    stage_name: String,
    // Discovery
    fetchers: indexmap::IndexMap<String, FetcherState>,
    triage: Option<(u64, u64)>,  // (candidates, ranked)
    fetched: Option<(u64, u64)>, // (fetched, budget)
    snowball_added: Option<u64>,
    // Plan
    key_concepts: Vec<String>,
    // Validation
    validate_passed: u64,
    validate_dropped: u64,
    validate_total: u64,
    validate_last: Option<(String, bool, f64, f64)>, // (title, passed, q, r)
    accepted_q_sum: f64,
    accepted_r_sum: f64,
    // Ingestion
    ingest_last: Option<(String, u64)>, // (title, chunks)
    ingest_count: u64,
    ingest_total: u64,
    ingest_chunks: u64,
    // Graph
    graph_batches: u64,
    graph_total_batches: u64,
    graph_total_nodes: usize,
    graph_total_edges: u64,
    graph_merged: u64,
    graph_recent_labels: VecDeque<String>, // newest at back
    // Persona
    persona_name: Option<String>,
    // Terminal summary from the Done event: (sources, chunks, concepts, edges).
    done_stats: Option<(u64, u64, u64, u64)>,
    // Set on the server's chat_ready event — the expert answers from here on,
    // a full stage before the build finishes.
    pub chat_ready: bool,
    // Activity log
    log_lines: VecDeque<LogEntry>,
    pub done: bool,
    pub error: Option<String>,
    rx: mpsc::Receiver<BuildEvent>,
    cancel: Arc<Notify>,
}

impl BuildScreen {
    /// Start a new build (POST /experts/build) and stream its progress.
    pub fn new(topic: String, tier: String, api: Arc<ApiClient>) -> Self {
        Self::spawn(topic, tier, api, true)
    }

    /// Attach to a build already running on the server (e.g. after the TUI was
    /// restarted). Replays the durable event log from the start so the screen
    /// reconstructs full progress state.
    pub fn attach(topic: String, tier: String, api: Arc<ApiClient>) -> Self {
        Self::spawn(topic, tier, api, false)
    }

    fn spawn(topic: String, tier: String, api: Arc<ApiClient>, start_build: bool) -> Self {
        let cancel = Arc::new(Notify::new());
        let (tx, rx) = mpsc::channel::<BuildEvent>(256);
        let api_clone = api.clone();
        let topic_clone = topic.clone();
        // "auto" means "let the server pick the deepest tier the account
        // affords" — expressed on the wire by omitting the field.
        let tier_clone = if tier == "auto" { None } else { Some(tier.clone()) };
        let cancel_clone = cancel.clone();
        let slug = crate::api::client::slugify(&topic);
        let slug_clone = slug.clone();
        // The build runs durably in a worker, so a dropped SSE connection no longer
        // loses progress. Start with POST /build (or attach straight to the event
        // log), then transparently resume from the durable event log
        // (GET .../build/events?after=<seq>) after any disconnect, until a terminal
        // event (Done/Error/Cancelled) or the user cancels.
        tokio::spawn(async move {
            const BACKOFF: std::time::Duration = std::time::Duration::from_secs(2);
            const MAX_EMPTY_RECONNECTS: u32 = 5;
            // Starts as the client-side slugify guess; replaced by the server's
            // authoritative slug from the `created` event (collisions
            // auto-suffix, and Unicode topics can slugify differently here).
            let mut slug = slug_clone;
            let mut last_seq: u64 = 0;
            let mut first = start_build;
            let mut empty_reconnects: u32 = 0;

            'outer: loop {
                let stream_res = if first {
                    api_clone.build_stream(topic_clone.clone(), tier_clone.clone()).await
                } else {
                    api_clone.build_events_stream(&slug, last_seq).await
                };
                first = false;

                let mut stream = match stream_res {
                    Ok(s) => s,
                    Err(e) => {
                        empty_reconnects += 1;
                        if empty_reconnects > MAX_EMPTY_RECONNECTS {
                            let _ = tx.send(BuildEvent::Error {
                                message: format!("Lost connection to build: {}", e),
                                code: None, spent_usd: None, cap_usd: None,
                            }).await;
                            break 'outer;
                        }
                        tokio::select! {
                            _ = cancel_clone.notified() => break 'outer,
                            _ = tokio::time::sleep(BACKOFF) => continue 'outer,
                        }
                    }
                };

                let mut got_event = false;
                let mut terminal = false;
                loop {
                    tokio::select! {
                        _ = cancel_clone.notified() => break 'outer,
                        item = stream.next() => match item {
                            Some(Ok(se)) => {
                                got_event = true;
                                if let Some(s) = se.seq { last_seq = s; }
                                if let BuildEvent::Created { slug: server_slug, .. } = &se.event {
                                    slug = server_slug.clone();
                                }
                                let is_terminal = se.event.is_terminal();
                                let _ = tx.send(se.event).await;
                                if is_terminal { terminal = true; break; }
                            }
                            Some(Err(_)) => break, // transient stream error → reconnect
                            None => break,         // connection closed → reconnect if not terminal
                        }
                    }
                }

                if terminal { break 'outer; }

                // Guard against spinning forever if the build vanished (deleted) and
                // reconnects keep yielding nothing.
                if got_event {
                    empty_reconnects = 0;
                } else {
                    empty_reconnects += 1;
                    if empty_reconnects > MAX_EMPTY_RECONNECTS {
                        let _ = tx.send(BuildEvent::Error {
                            message: "Build stream ended unexpectedly.".to_string(),
                            code: None, spent_usd: None, cap_usd: None,
                        }).await;
                        break 'outer;
                    }
                }

                tokio::select! {
                    _ = cancel_clone.notified() => break 'outer,
                    _ = tokio::time::sleep(BACKOFF) => {}
                }
            }
        });
        Self {
            topic,
            tier,
            slug,
            api,
            confirm_cancel: false,
            cancel_sent: false,
            cancel_failed: Arc::new(std::sync::Mutex::new(None)),
            start_time: std::time::Instant::now(),
            stage_started: std::time::Instant::now(),
            stage: 0,
            stage_name: String::new(),
            fetchers: indexmap::IndexMap::new(),
            triage: None,
            fetched: None,
            snowball_added: None,
            key_concepts: vec![],
            validate_passed: 0,
            validate_dropped: 0,
            validate_total: 0,
            validate_last: None,
            accepted_q_sum: 0.0,
            accepted_r_sum: 0.0,
            ingest_last: None,
            ingest_count: 0,
            ingest_total: 0,
            ingest_chunks: 0,
            graph_batches: 0,
            graph_total_batches: 0,
            graph_total_nodes: 0,
            graph_total_edges: 0,
            graph_merged: 0,
            graph_recent_labels: VecDeque::with_capacity(30),
            persona_name: None,
            done_stats: None,
            chat_ready: false,
            log_lines: VecDeque::with_capacity(500),
            done: false,
            error: None,
            rx,
            cancel,
        }
    }

    /// Stop reading the event stream (client-side detach). Does not affect the
    /// build on the server; use [`request_server_cancel`] for that.
    pub fn cancel(&self) { self.cancel.notify_one(); }
    pub fn topic(&self) -> &str { &self.topic }

    /// Ask the server to cancel the build. The terminal `cancelled` event then
    /// arrives through the normal event stream and lands in the activity log.
    pub fn request_server_cancel(&mut self) {
        if self.cancel_sent { return; }
        self.cancel_sent = true;
        self.confirm_cancel = false;
        self.log("Cancelling build…", LogLevel::Info);
        let api = self.api.clone();
        let slug = self.slug.clone();
        let failed = self.cancel_failed.clone();
        tokio::spawn(async move {
            if let Err(e) = api.cancel_build(&slug).await {
                tracing::warn!("Cancel request failed for {}: {}", slug, e);
                if let Ok(mut guard) = failed.lock() {
                    *guard = Some(e.to_string());
                }
            }
        });
    }

    pub fn card_info(&self) -> BuildCardInfo {
        let detail = match self.stage {
            0 => if self.key_concepts.is_empty() {
                "Identifying key concepts…".to_string()
            } else {
                format!("{} concepts identified", self.key_concepts.len())
            },
            1 => {
                let done = self.fetchers.values()
                    .filter(|s| matches!(s, FetcherState::Done(_) | FetcherState::Skipped))
                    .count();
                format!("{}/{} fetchers done", done, self.fetchers.len())
            }
            2 => {
                let done = self.validate_passed + self.validate_dropped;
                if done == 0 { "Scoring sources…".to_string() }
                else { format!("{} accepted  ·  {} dropped", self.validate_passed, self.validate_dropped) }
            }
            3 => format!("{} sources ingested", self.ingest_count),
            4 => format!("{} concepts  ·  {} edges", self.graph_total_nodes, self.graph_total_edges),
            5 => match &self.persona_name {
                Some(name) => format!("Persona: {}", name),
                None => "Creating persona…".to_string(),
            },
            _ => "Finalising…".to_string(),
        };
        BuildCardInfo {
            topic: self.topic.clone(),
            stage: self.stage,
            stage_label: stage_short_for(self.stage).to_string(),
            detail,
        }
    }

    fn log(&mut self, msg: impl Into<String>, level: LogLevel) {
        if self.log_lines.len() >= 500 { self.log_lines.pop_front(); }
        let at_secs = self.start_time.elapsed().as_secs();
        self.log_lines.push_back(LogEntry { at_secs, msg: msg.into(), level });
    }

    /// Reset per-attempt progress. A retry re-runs the whole pipeline, so stale
    /// counters from the failed attempt would double-count. The activity log is
    /// kept — it is the user's record of what happened.
    fn reset_progress(&mut self) {
        self.stage = 0;
        self.stage_started = std::time::Instant::now();
        self.stage_name.clear();
        self.fetchers.clear();
        self.triage = None;
        self.fetched = None;
        self.snowball_added = None;
        self.key_concepts.clear();
        self.validate_passed = 0;
        self.validate_dropped = 0;
        self.validate_total = 0;
        self.validate_last = None;
        self.accepted_q_sum = 0.0;
        self.accepted_r_sum = 0.0;
        self.ingest_last = None;
        self.ingest_count = 0;
        self.ingest_total = 0;
        self.ingest_chunks = 0;
        self.graph_batches = 0;
        self.graph_total_batches = 0;
        self.graph_total_nodes = 0;
        self.graph_total_edges = 0;
        self.graph_merged = 0;
        self.graph_recent_labels.clear();
        self.persona_name = None;
        self.chat_ready = false;
    }

    pub async fn tick(&mut self) -> bool {
        // A rejected cancel (e.g. the build already finished — 409) must
        // un-latch, or the footer shows "Cancelling…" forever.
        let cancel_err = self.cancel_failed.lock().ok().and_then(|mut g| g.take());
        if let Some(e) = cancel_err {
            self.cancel_sent = false;
            self.log(format!("Cancel failed: {}", e), LogLevel::Error);
        }
        loop {
            let event = match self.rx.try_recv() {
                Ok(event) => event,
                Err(mpsc::error::TryRecvError::Empty) => break,
                Err(mpsc::error::TryRecvError::Disconnected) => {
                    // The event pump exited. It always sends a terminal event
                    // first on normal paths — if we got neither, surface it
                    // rather than spinning forever.
                    if !self.done && self.error.is_none() {
                        self.error = Some(
                            "Build stream closed — the build may still be running on the \
                             server; re-open it from Home with [b]".to_string(),
                        );
                    }
                    break;
                }
            };
            match &event {
                BuildEvent::Created { slug, tier } => {
                    // The server's slug is authoritative (collisions auto-suffix),
                    // and an auto build learns its resolved tier here.
                    self.slug = slug.clone();
                    if !tier.is_empty() && self.tier == "auto" {
                        self.tier = tier.clone();
                        self.log(format!("Tier resolved: {}", tier), LogLevel::Info);
                    }
                }
                BuildEvent::ExecutionMode { mode, batched } => {
                    if *batched {
                        self.log(
                            "Running batched (half price — stages may queue up to an hour)",
                            LogLevel::Info,
                        );
                    } else if mode == "interactive" {
                        self.log("Running live", LogLevel::Info);
                    }
                }
                BuildEvent::BuildStarted { attempt, max_attempts } => {
                    if *attempt > 1 {
                        self.reset_progress();
                        self.log(
                            format!("Restarting build — attempt {} of {}", attempt, max_attempts),
                            LogLevel::Stage,
                        );
                    }
                }
                BuildEvent::Retry { attempt, max_attempts, message } => {
                    self.log(
                        format!("Attempt {}/{} failed: {} — retrying shortly…",
                                attempt, max_attempts, trunc(message, 60)),
                        LogLevel::Error,
                    );
                }
                BuildEvent::Stage { stage, name, total, total_batches } => {
                    self.stage = *stage;
                    self.stage_started = std::time::Instant::now();
                    self.stage_name = name.clone();
                    match *stage {
                        2 => self.validate_total = *total,
                        3 => self.ingest_total = *total,
                        4 if *total_batches > 0 => self.graph_total_batches = *total_batches,
                        _ => {}
                    }
                    let title = stage_title_for(self.stage);
                    self.log(format!("── {} ──", title), LogLevel::Stage);
                }
                BuildEvent::PlanReady { key_concepts } => {
                    self.key_concepts = key_concepts.clone();
                    self.log(format!("{} concepts identified", key_concepts.len()), LogLevel::Success);
                }
                BuildEvent::DiscoveryStarted { fetchers, active } => {
                    // `fetchers` is every fetcher that exists; `active` is the
                    // subset this build's plan actually runs. The inactive ones
                    // are decided, not pending — the planner gave them weight 0
                    // (no public-domain books for the topic, say) and nothing
                    // will ever send a fetcher_done for them. Seeding those as
                    // Waiting left them spinning for the life of the build and
                    // held the header one short forever ("10/11 fetchers done").
                    for f in fetchers { self.fetchers.insert(f.clone(), FetcherState::Skipped); }
                    for f in active   { self.fetchers.insert(f.clone(), FetcherState::Fetching); }
                    self.log(format!("Starting {} source fetchers", active.len()), LogLevel::Info);
                }
                BuildEvent::FetcherDone { name, count, skipped, reason } => {
                    let state = if *skipped { FetcherState::Skipped } else { FetcherState::Done(*count) };
                    self.fetchers.insert(name.clone(), state);
                    if *skipped {
                        let why = if reason.is_empty() { String::new() } else { format!(" ({})", reason) };
                        self.log(format!("{}: skipped{}", name, why), LogLevel::Info);
                    } else {
                        self.log(format!("{}: {} sources", name, count), LogLevel::Success);
                    }
                }
                BuildEvent::TriageDone { candidates, ranked, budget } => {
                    self.triage = Some((*candidates, *ranked));
                    self.log(
                        format!("Triage: {} candidates → {} ranked (budget {})", candidates, ranked, budget),
                        LogLevel::Success,
                    );
                }
                // Fills the funnel's "of N fetched" leg while the fetch is still
                // running, so a long fetch stage is visibly moving rather than
                // indistinguishable from a dead worker.
                BuildEvent::FetchProgress { fetched, attempted, budget } => {
                    self.fetched = Some((*fetched, *budget));
                    self.log(
                        format!("Fetching: {}/{} retrieved ({} tried)", fetched, budget, attempted),
                        LogLevel::Info,
                    );
                }
                BuildEvent::FetchDone { fetched, budget } => {
                    self.fetched = Some((*fetched, *budget));
                    self.log(format!("Fetched {} of {} budgeted sources", fetched, budget), LogLevel::Success);
                }
                BuildEvent::SnowballDone { added } => {
                    self.snowball_added = Some(self.snowball_added.unwrap_or(0) + added);
                    self.log(format!("Snowball: +{} sources", added), LogLevel::Success);
                }
                BuildEvent::SourceValidated { title, passed, q, r } => {
                    let short = trunc(title, 44);
                    self.validate_last = Some((short.clone(), *passed, *q, *r));
                    // q/r are the validator's 0–10 quality/relevance scores.
                    if *passed {
                        self.validate_passed += 1;
                        self.accepted_q_sum += q;
                        self.accepted_r_sum += r;
                        self.log(format!("✓ {} (Q {:.1} · R {:.1})", short, q, r), LogLevel::Success);
                    } else {
                        self.validate_dropped += 1;
                        self.log(format!("✗ {} (Q {:.1} · R {:.1})", short, q, r), LogLevel::Info);
                    }
                }
                BuildEvent::ValidateDone { passed, dropped } => {
                    self.validate_passed = *passed;
                    self.validate_dropped = *dropped;
                    self.log(format!("{} accepted, {} dropped", passed, dropped), LogLevel::Success);
                }
                BuildEvent::CoverageGaps { gaps } => {
                    self.log(
                        format!("Coverage gaps — re-searching: {}", gaps.join(", ")),
                        LogLevel::Info,
                    );
                }
                BuildEvent::GapfillDone { added, still_uncovered } => {
                    if still_uncovered.is_empty() {
                        self.log(format!("Gap-fill: +{} sources, all concepts covered", added), LogLevel::Success);
                    } else {
                        self.log(
                            format!("Gap-fill: +{} sources; still uncovered: {}", added, still_uncovered.join(", ")),
                            LogLevel::Info,
                        );
                    }
                }
                BuildEvent::CorpusWarning { message } => {
                    self.log(format!("⚠ {}", trunc(message, 120)), LogLevel::Error);
                }
                BuildEvent::ChatReady { sources, chunks } => {
                    self.chat_ready = true;
                    self.log(
                        format!("★ Chat-ready — {} sources, {} chunks. You can already chat while the graph builds.", sources, chunks),
                        LogLevel::Success,
                    );
                }
                BuildEvent::GraphReady { nodes, edges } => {
                    // Authoritative totals — post-resolution counts can differ
                    // from the running per-batch sums.
                    self.graph_total_nodes = *nodes as usize;
                    self.graph_total_edges = *edges;
                    self.log(format!("★ Graph ready — {} concepts, {} edges", nodes, edges), LogLevel::Success);
                }
                BuildEvent::StageDegraded { stage, message } => {
                    self.log(format!("⚠ {} stage degraded: {}", stage, trunc(message, 100)), LogLevel::Error);
                }
                BuildEvent::ResolveProgress { merged } => {
                    self.graph_merged = *merged;
                    self.log(format!("Resolving duplicates… {} merged", merged), LogLevel::Info);
                }
                BuildEvent::SourceIngested { title, chunks } => {
                    let short = trunc(title, 44);
                    self.ingest_count += 1;
                    self.ingest_chunks += chunks;
                    self.ingest_last = Some((short.clone(), *chunks));
                    self.log(format!("{} ({} chunks)", short, chunks), LogLevel::Success);
                }
                BuildEvent::GraphBatchDone { labels, edges } => {
                    self.graph_batches += 1;
                    self.graph_total_nodes += labels.len();
                    self.graph_total_edges += edges;
                    for label in labels {
                        if self.graph_recent_labels.len() >= 30 { self.graph_recent_labels.pop_front(); }
                        self.graph_recent_labels.push_back(label.clone());
                    }
                    self.log(format!("Batch {}: {} concepts, {} edges", self.graph_batches, labels.len(), edges), LogLevel::Success);
                }
                BuildEvent::EntitiesResolved { merged } => {
                    self.graph_merged = *merged;
                    self.log(format!("Resolved: {} concepts merged", merged), LogLevel::Success);
                }
                BuildEvent::PersonaReady { name } => {
                    self.persona_name = Some(name.clone());
                    self.log(format!("Persona: {}", name), LogLevel::Success);
                }
                BuildEvent::Done { source_count, chunk_count, node_count, edge_count, persona_name } => {
                    self.done = true;
                    self.done_stats = Some((*source_count, *chunk_count, *node_count, *edge_count));
                    if let Some(name) = persona_name {
                        self.persona_name = Some(name.clone());
                    }
                    let voice = self.persona_name.as_deref()
                        .map(|n| format!("  ·  {}", n))
                        .unwrap_or_default();
                    self.log(
                        format!(
                            "Done — {} sources · {} chunks · {} concepts · {} edges{}",
                            source_count, chunk_count, node_count, edge_count, voice,
                        ),
                        LogLevel::Success,
                    );
                    return true;
                }
                BuildEvent::Error { message, code, spent_usd, cap_usd } => {
                    // Keep the build screen up so the error is readable. tick() only
                    // returns true on success (Done), which is what drives the
                    // "Ready to chat" navigation in the app loop.
                    let msg = if code.as_deref() == Some("spend_cap_exceeded") {
                        format!(
                            "Build stopped at its spend cap (${:.2} of ${:.2}) and was refunded",
                            spent_usd.unwrap_or(0.0), cap_usd.unwrap_or(0.0),
                        )
                    } else {
                        message.clone()
                    };
                    self.error = Some(msg.clone());
                    self.log(format!("Error: {}", msg), LogLevel::Error);
                }
                BuildEvent::Cancelled { message } => {
                    let msg = if message.is_empty() { "Build cancelled" } else { message.as_str() };
                    self.error = Some(msg.to_string());
                    self.log(msg.to_string(), LogLevel::Error);
                }
                BuildEvent::Unknown => {}
            }
        }
        false
    }

    pub fn render(&mut self, f: &mut Frame, area: Rect, tick: u64) {
        let block = Block::default()
            .title(format!(" ◈ Building: \"{}\"  [{}] ", self.topic, self.tier.to_uppercase()))
            .title_style(Theme::title())
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::selected_border())
            .style(Theme::normal());
        let inner = block.inner(area);
        f.render_widget(block, area);

        // The stage panel is a fixed-height snapshot and the activity log
        // absorbs all surplus space — the log is the info-dense region on a
        // tall terminal, while stage panels only ever need a snapshot's worth.
        let panel_h = self.stage_panel_height()
            .min(inner.height.saturating_sub(8)) // keep ≥5 log rows + header/footer
            .max(5);
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(2),       // pipeline header
                Constraint::Length(panel_h), // stage snapshot
                Constraint::Min(5),          // activity log
                Constraint::Length(1),       // footer
            ])
            .split(inner);

        self.render_pipeline(f, chunks[0]);
        self.render_stage_content(f, chunks[1], tick);
        self.render_log(f, chunks[2]);
        self.render_footer(f, chunks[3], tick);
    }

    /// Rows (incl. borders) the current stage's snapshot panel wants.
    fn stage_panel_height(&self) -> u16 {
        if self.error.is_some() { return 6; }
        if self.done { return 9; }
        match self.stage {
            0 => 8,                                       // plan: concepts may wrap
            1 => self.fetchers.len().max(4) as u16 + 5,   // discovery: fetcher board + funnel
            2 => 9,                                       // validate
            3 => 9,                                       // ingest
            4 => 12,                                      // graph: labels may wrap
            _ => 9,                                       // persona
        }
    }

    fn render_pipeline(&self, f: &mut Frame, area: Rect) {
        // Adaptive separator so all six stages stay on one line at 80 columns.
        let sep = if area.width >= 96 { "  ──  " }
                  else if area.width >= 78 { " ── " }
                  else { " · " };
        let mut spans: Vec<Span> = Vec::new();
        for (i, (_, label)) in STAGES.iter().enumerate() {
            // STAGES is indexed by the backend's 0-based stage number.
            let stage_num = i as u8;
            let (icon, style) = if stage_num < self.stage || self.done {
                ("✓", Theme::success().add_modifier(Modifier::BOLD))
            } else if stage_num == self.stage {
                ("●", Theme::accent().add_modifier(Modifier::BOLD))
            } else {
                ("○", Theme::dim())
            };
            if i > 0 { spans.push(Span::styled(sep, Theme::dim())); }
            spans.push(Span::styled(format!("{} {}", icon, label), style));
            if stage_num == self.stage && !self.done && self.error.is_none() {
                spans.push(Span::styled(
                    format!(" {}", fmt_elapsed(self.stage_started.elapsed().as_secs())),
                    Theme::dim(),
                ));
            }
        }
        if self.chat_ready && !self.done {
            spans.push(Span::styled(sep, Theme::dim()));
            spans.push(Span::styled("★ chat-ready", Theme::warning().add_modifier(Modifier::BOLD)));
        }
        f.render_widget(
            Paragraph::new(Line::from(spans))
                .block(Block::default().borders(Borders::BOTTOM).border_style(Theme::normal_border())),
            area,
        );
    }

    fn render_stage_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        // Terminal states replace the stage snapshot — a stale mid-stage view
        // under a "done"/"error" footer read as if the build were still going.
        if let Some(err) = &self.error {
            self.render_error_content(f, area, err);
            return;
        }
        if self.done {
            self.render_done_content(f, area);
            return;
        }
        match self.stage {
            0 => self.render_plan_content(f, area, tick),
            1 => self.render_discovery_content(f, area, tick),
            2 => self.render_validate_content(f, area, tick),
            3 => self.render_ingest_content(f, area, tick),
            4 => self.render_graph_content(f, area, tick),
            _ => self.render_persona_content(f, area, tick),
        }
    }

    fn render_plan_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let block = content_block("Planning");
        let inner = block.inner(area);
        f.render_widget(block, area);

        let mut lines = vec![
            Line::from(Span::styled(
                "Studying your topic to decide which sources will teach the expert the most.",
                Theme::dim().add_modifier(Modifier::ITALIC),
            )),
            Line::from(""),
        ];
        if self.key_concepts.is_empty() {
            lines.push(Line::from(vec![
                Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                Span::styled("Identifying key concepts…", Theme::dim()),
            ]));
        } else {
            lines.push(Line::from(vec![
                Span::styled("✓ ", Theme::success()),
                Span::styled(
                    format!("Plan ready — {} key concepts", self.key_concepts.len()),
                    Theme::success().add_modifier(Modifier::BOLD),
                ),
            ]));
            lines.push(Line::from(""));
            let mut concept_spans: Vec<Span> = Vec::new();
            for (i, c) in self.key_concepts.iter().enumerate() {
                if i > 0 { concept_spans.push(Span::styled("  ·  ", Theme::dim())); }
                concept_spans.push(Span::styled(c.as_str(), Theme::accent2()));
            }
            lines.push(Line::from(concept_spans));
        }
        f.render_widget(Paragraph::new(lines).wrap(Wrap { trim: true }), inner);
    }

    fn render_discovery_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let done_count = self.fetchers.values().filter(|s| matches!(s, FetcherState::Done(_) | FetcherState::Skipped)).count();
        let total_count = self.fetchers.len();
        let block = Block::default()
            .title(format!(" Source Discovery  ·  {}/{} fetchers done ", done_count, total_count))
            .title_style(Theme::dim())
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::normal_border());
        let inner = block.inner(area);
        f.render_widget(block, area);

        let split = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(2), Constraint::Min(1), Constraint::Length(1)])
            .split(inner);

        f.render_widget(
            Paragraph::new(vec![
                Line::from(Span::styled(
                    "Reaching out to encyclopaedias, papers, and the web to gather raw material.",
                    Theme::dim().add_modifier(Modifier::ITALIC),
                )),
                Line::from(""),
            ]),
            split[0],
        );

        let items: Vec<ListItem> = self.fetchers.iter().map(|(name, state)| {
            ListItem::new(match state {
                FetcherState::Fetching => Line::from(vec![
                    Span::styled(format!("{}  ", spinner::dots(tick)), Theme::accent().add_modifier(Modifier::BOLD)),
                    Span::styled(name.as_str(), Theme::accent()),
                ]),
                FetcherState::Done(n) => Line::from(vec![
                    Span::styled("✓  ", Theme::success()),
                    Span::styled(name.as_str(), Theme::normal()),
                    Span::styled(format!("  {} sources", n), Theme::dim()),
                ]),
                FetcherState::Skipped => Line::from(vec![
                    Span::styled("–  ", Theme::dim()),
                    Span::styled(name.as_str(), Theme::dim()),
                    Span::styled("  skipped", Theme::dim().add_modifier(Modifier::ITALIC)),
                ]),
            })
        }).collect();
        f.render_widget(List::new(items), split[1]);

        // Triage → fetch → snowball funnel — fills in as the sub-steps land.
        if let Some((candidates, ranked)) = self.triage {
            let mut funnel = vec![
                Span::styled("Funnel:  ", Theme::dim()),
                Span::styled(format!("{}", candidates), Theme::normal().add_modifier(Modifier::BOLD)),
                Span::styled(" found  →  ", Theme::dim()),
                Span::styled(format!("{}", ranked), Theme::normal().add_modifier(Modifier::BOLD)),
                Span::styled(" ranked", Theme::dim()),
            ];
            if let Some((fetched, budget)) = self.fetched {
                funnel.push(Span::styled("  →  ", Theme::dim()));
                funnel.push(Span::styled(format!("{}", fetched), Theme::normal().add_modifier(Modifier::BOLD)));
                funnel.push(Span::styled(format!(" of {} fetched", budget), Theme::dim()));
            }
            if let Some(added) = self.snowball_added {
                funnel.push(Span::styled(format!("  +{} snowball", added), Theme::success()));
            }
            f.render_widget(Paragraph::new(Line::from(funnel)), split[2]);
        }
    }

    fn render_validate_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let block = content_block("Quality Validation");
        let inner = block.inner(area);
        f.render_widget(block, area);

        let scored = self.validate_passed + self.validate_dropped;
        let bar_line = if self.validate_total > 0 {
            // Progress through the queue, not the kept-ratio — the bar should
            // reach full exactly when the stage ends.
            let mut spans = bar_spans(scored as f64 / self.validate_total as f64, 24, Theme::accent());
            spans.push(Span::styled(
                format!("  {}/{} scored", scored, self.validate_total),
                Theme::dim(),
            ));
            Line::from(spans)
        } else {
            Line::from(vec![
                Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                Span::styled("Waiting for sources…", Theme::dim()),
            ])
        };

        let mut verdict_spans = vec![
            Span::styled("✓ ", Theme::success()),
            Span::styled(format!("{}", self.validate_passed), Theme::success().add_modifier(Modifier::BOLD)),
            Span::styled(" accepted    ", Theme::dim()),
            Span::styled("✗ ", Theme::dim()),
            Span::styled(format!("{}", self.validate_dropped), Theme::normal()),
            Span::styled(" dropped", Theme::dim()),
        ];
        if self.validate_passed > 0 {
            verdict_spans.push(Span::styled(
                format!(
                    "    avg Q {:.1} · R {:.1}",
                    self.accepted_q_sum / self.validate_passed as f64,
                    self.accepted_r_sum / self.validate_passed as f64,
                ),
                Theme::dim(),
            ));
        }

        let last_line = if let Some((title, passed, q, r)) = &self.validate_last {
            let (mark, style) = if *passed { ("✓", Theme::success()) } else { ("✗", Theme::dim()) };
            Line::from(vec![
                Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                Span::styled("Last scored:  ", Theme::dim()),
                Span::styled(format!("{} ", mark), style),
                Span::styled(title.as_str(), Theme::normal()),
                Span::styled(format!("  (Q {:.1} · R {:.1})", q, r), Theme::dim()),
            ])
        } else {
            Line::from(vec![
                Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                Span::styled("Scoring relevance and quality…", Theme::dim()),
            ])
        };

        f.render_widget(
            Paragraph::new(vec![
                Line::from(Span::styled(
                    "Reading each source and scoring how well it covers your topic.",
                    Theme::dim().add_modifier(Modifier::ITALIC),
                )),
                Line::from(""),
                bar_line,
                Line::from(""),
                Line::from(verdict_spans),
                Line::from(""),
                last_line,
            ]),
            inner,
        );
    }

    // Summary only — the per-source feed already streams through the activity
    // log, so repeating it here just duplicated the same lines twice on screen.
    fn render_ingest_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let progress = if self.ingest_total > 0 {
            format!("{}/{} sources", self.ingest_count, self.ingest_total)
        } else {
            format!("{} ingested", self.ingest_count)
        };
        let block = Block::default()
            .title(format!(" Content Ingestion  ·  {} ", progress))
            .title_style(Theme::dim())
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::normal_border());
        let inner = block.inner(area);
        f.render_widget(block, area);

        let bar_line = if self.ingest_total > 0 {
            let mut spans = bar_spans(self.ingest_count as f64 / self.ingest_total as f64, 24, Theme::accent());
            spans.push(Span::styled(
                format!("  {}/{} sources", self.ingest_count, self.ingest_total),
                Theme::dim(),
            ));
            Line::from(spans)
        } else {
            Line::from(vec![
                Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                Span::styled(format!("{} sources ingested…", self.ingest_count), Theme::dim()),
            ])
        };

        let mut stats_spans = vec![
            Span::styled(format!("{}", self.ingest_chunks), Theme::normal().add_modifier(Modifier::BOLD)),
            Span::styled(" chunks embedded", Theme::dim()),
        ];
        if let Some(avg) = self.ingest_chunks.checked_div(self.ingest_count) {
            stats_spans.push(Span::styled(
                format!("    ~{} chunks/source", avg),
                Theme::dim(),
            ));
        }

        let last_line = if let Some((title, chunks)) = &self.ingest_last {
            Line::from(vec![
                Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                Span::styled("Last:  ", Theme::dim()),
                Span::styled("✓ ", Theme::success()),
                Span::styled(title.as_str(), Theme::normal()),
                Span::styled(format!("  {} chunks", chunks), Theme::dim()),
            ])
        } else {
            Line::from(vec![
                Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                Span::styled("Chunking first source…", Theme::dim()),
            ])
        };

        f.render_widget(
            Paragraph::new(vec![
                Line::from(Span::styled(
                    "Breaking approved sources into chunks and encoding them as embeddings.",
                    Theme::dim().add_modifier(Modifier::ITALIC),
                )),
                Line::from(""),
                bar_line,
                Line::from(""),
                Line::from(stats_spans),
                Line::from(""),
                last_line,
            ]),
            inner,
        );
    }

    fn render_graph_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let block = content_block("Knowledge Graph");
        let inner = block.inner(area);
        f.render_widget(block, area);

        let bar_line = if self.graph_total_batches > 0 {
            let mut spans = bar_spans(
                self.graph_batches as f64 / self.graph_total_batches as f64, 24, Theme::accent());
            spans.push(Span::styled(
                format!("  {}/{} batches", self.graph_batches, self.graph_total_batches),
                Theme::dim(),
            ));
            Line::from(spans)
        } else {
            Line::from(vec![
                Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                Span::styled(format!("Building graph…  {} batches done", self.graph_batches), Theme::dim()),
            ])
        };

        let mut count_spans = vec![
            Span::styled(format!("{}", self.graph_total_nodes), Theme::normal().add_modifier(Modifier::BOLD)),
            Span::styled(" concepts  ·  ", Theme::dim()),
            Span::styled(format!("{}", self.graph_total_edges), Theme::normal().add_modifier(Modifier::BOLD)),
            Span::styled(" edges", Theme::dim()),
        ];
        if self.graph_merged > 0 {
            count_spans.push(Span::styled(
                format!("  ·  {} duplicates merged", self.graph_merged),
                Theme::dim(),
            ));
        }

        let mut lines = vec![
            Line::from(Span::styled(
                "Extracting concepts and relationships to wire up your expert's knowledge map.",
                Theme::dim().add_modifier(Modifier::ITALIC),
            )),
            Line::from(""),
            bar_line,
            Line::from(""),
            Line::from(count_spans),
        ];
        // A rolling window of freshly extracted concepts — makes the longest
        // stage feel alive and shows what the expert is actually learning.
        if !self.graph_recent_labels.is_empty() {
            lines.push(Line::from(""));
            let mut label_spans = vec![Span::styled("Latest:  ", Theme::dim())];
            for (i, label) in self.graph_recent_labels.iter().rev().take(10).enumerate() {
                if i > 0 { label_spans.push(Span::styled("  ·  ", Theme::dim())); }
                label_spans.push(Span::styled(label.as_str(), Theme::accent2()));
            }
            lines.push(Line::from(label_spans));
        }
        if let Some(name) = &self.persona_name {
            lines.push(Line::from(""));
            lines.push(Line::from(vec![
                Span::styled("✓  Persona created: ", Theme::success()),
                Span::styled(name.as_str(), Theme::normal().add_modifier(Modifier::BOLD)),
            ]));
        }
        f.render_widget(Paragraph::new(lines).wrap(Wrap { trim: true }), inner);
    }

    fn render_persona_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let block = content_block("Persona");
        let inner = block.inner(area);
        f.render_widget(block, area);

        let mut lines = vec![
            Line::from(Span::styled(
                "Distilling a voice and personality from everything the expert just learned.",
                Theme::dim().add_modifier(Modifier::ITALIC),
            )),
            Line::from(""),
            Line::from(vec![
                Span::styled("✓  ", Theme::success()),
                Span::styled("Graph complete — ", Theme::dim()),
                Span::styled(format!("{}", self.graph_total_nodes), Theme::normal().add_modifier(Modifier::BOLD)),
                Span::styled(" concepts  ·  ", Theme::dim()),
                Span::styled(format!("{}", self.graph_total_edges), Theme::normal().add_modifier(Modifier::BOLD)),
                Span::styled(" edges", Theme::dim()),
            ]),
            Line::from(""),
        ];
        match &self.persona_name {
            Some(name) => lines.push(Line::from(vec![
                Span::styled("✓  Persona:  ", Theme::success()),
                Span::styled(name.as_str(), Theme::normal().add_modifier(Modifier::BOLD)),
            ])),
            None => lines.push(Line::from(vec![
                Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                Span::styled("Writing persona…", Theme::dim()),
            ])),
        }
        if self.chat_ready {
            lines.push(Line::from(""));
            lines.push(Line::from(vec![
                Span::styled("★  ", Theme::warning()),
                Span::styled("Chat-ready — [Esc] then Enter to talk to your expert now.", Theme::dim()),
            ]));
        }
        f.render_widget(Paragraph::new(lines), inner);
    }

    fn render_done_content(&self, f: &mut Frame, area: Rect) {
        let block = Block::default()
            .title(" Expert Ready ")
            .title_style(Theme::success().add_modifier(Modifier::BOLD))
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::success());
        let inner = block.inner(area);
        f.render_widget(block, area);

        let (sources, chunks, nodes, edges) = self.done_stats.unwrap_or((
            self.ingest_count, self.ingest_chunks, self.graph_total_nodes as u64, self.graph_total_edges,
        ));
        let mut lines = vec![
            Line::from(vec![
                Span::styled("✓  ", Theme::success().add_modifier(Modifier::BOLD)),
                Span::styled(self.topic.as_str(), Theme::normal().add_modifier(Modifier::BOLD)),
                Span::styled("  is ready to chat.", Theme::normal()),
            ]),
            Line::from(""),
            Line::from(vec![
                Span::styled(format!("{}", sources), Theme::normal().add_modifier(Modifier::BOLD)),
                Span::styled(" sources  ·  ", Theme::dim()),
                Span::styled(format!("{}", chunks), Theme::normal().add_modifier(Modifier::BOLD)),
                Span::styled(" chunks  ·  ", Theme::dim()),
                Span::styled(format!("{}", nodes), Theme::normal().add_modifier(Modifier::BOLD)),
                Span::styled(" concepts  ·  ", Theme::dim()),
                Span::styled(format!("{}", edges), Theme::normal().add_modifier(Modifier::BOLD)),
                Span::styled(" edges", Theme::dim()),
            ]),
        ];
        if let Some(name) = &self.persona_name {
            lines.push(Line::from(""));
            lines.push(Line::from(vec![
                Span::styled("Voice:  ", Theme::dim()),
                Span::styled(name.as_str(), Theme::accent2().add_modifier(Modifier::BOLD)),
            ]));
        }
        lines.push(Line::from(""));
        lines.push(Line::from(Span::styled(
            "[Esc] Home, then Enter to start chatting.",
            Theme::dim(),
        )));
        f.render_widget(Paragraph::new(lines).wrap(Wrap { trim: true }), inner);
    }

    fn render_error_content(&self, f: &mut Frame, area: Rect, err: &str) {
        let block = Block::default()
            .title(" Build Stopped ")
            .title_style(Theme::error().add_modifier(Modifier::BOLD))
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::error());
        let inner = block.inner(area);
        f.render_widget(block, area);

        f.render_widget(
            Paragraph::new(vec![
                Line::from(Span::styled(err, Theme::error())),
                Line::from(""),
                Line::from(Span::styled(
                    "The activity log below has the full history.  [Esc] Home",
                    Theme::dim(),
                )),
            ]).wrap(Wrap { trim: true }),
            inner,
        );
    }

    fn render_log(&self, f: &mut Frame, area: Rect) {
        let block = Block::default()
            .title(" Activity ")
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::normal_border());
        let inner = block.inner(area);
        f.render_widget(block, area);

        let items: Vec<ListItem> = self.log_lines.iter()
            .rev()
            .take(inner.height as usize)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .map(|entry| {
                let style = match entry.level {
                    LogLevel::Stage   => Theme::accent().add_modifier(Modifier::BOLD | Modifier::ITALIC),
                    LogLevel::Success => Theme::success(),
                    LogLevel::Error   => Theme::error(),
                    LogLevel::Info    => Theme::dim(),
                };
                ListItem::new(Line::from(vec![
                    Span::styled(
                        format!("{:>3}:{:02}  ", entry.at_secs / 60, entry.at_secs % 60),
                        Theme::dim(),
                    ),
                    Span::styled(entry.msg.as_str(), style),
                ]))
            })
            .collect();
        f.render_widget(List::new(items), inner);
    }

    fn render_footer(&self, f: &mut Frame, area: Rect, tick: u64) {
        let elapsed = fmt_elapsed(self.start_time.elapsed().as_secs());
        let widget = if let Some(err) = &self.error {
            Paragraph::new(format!("✗  {}  ·  {}  ·  [Esc] Home", err, elapsed)).style(Theme::error())
        } else if self.done {
            Paragraph::new(format!("✓  Build complete!  ·  {}  ·  [Esc] Home", elapsed)).style(Theme::success())
        } else if self.confirm_cancel {
            Paragraph::new("Cancel this build?  ·  [x] Confirm  ·  [Esc] Keep building").style(Theme::warning())
        } else if self.cancel_sent {
            let spin = spinner::braille(tick);
            Paragraph::new(format!("{}  Cancelling…  ·  {}", spin, elapsed)).style(Theme::warning())
        } else {
            let spin = spinner::braille(tick);
            // Chat-ready is already flagged in the header and stage panel.
            Paragraph::new(format!(
                "{}  {}  ·  {}  ·  [Esc] Home (build keeps running)  ·  [x] Cancel build",
                spin, stage_description_for(self.stage), elapsed,
            )).style(Theme::dim())
        };
        f.render_widget(widget, area);
    }
}

fn stage_short_for(stage: u8) -> &'static str {
    match stage {
        0 => "Planning",
        1 => "Discovering sources",
        2 => "Validating quality",
        3 => "Ingesting content",
        4 => "Building graph",
        5 => "Creating persona",
        _ => "Finalising",
    }
}

fn stage_title_for(stage: u8) -> &'static str {
    match stage {
        0 => "Planning",
        1 => "Source Discovery",
        2 => "Quality Validation",
        3 => "Content Ingestion",
        4 => "Knowledge Graph",
        5 => "Persona",
        _ => "Processing",
    }
}

fn stage_description_for(stage: u8) -> &'static str {
    match stage {
        0 => "Analyzing topic and planning sources",
        1 => "Fetching sources from the web",
        2 => "Scoring source relevance and quality",
        3 => "Chunking, embedding, and indexing content",
        4 => "Extracting concepts and building knowledge graph",
        5 => "Generating expert persona",
        _ => "Finalizing",
    }
}

fn content_block(title: &str) -> Block<'_> {
    Block::default()
        .title(format!(" {} ", title))
        .title_style(Theme::dim())
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Theme::normal_border())
}

/// Filled/empty progress-bar spans, `frac` clamped to [0, 1].
fn bar_spans(frac: f64, width: usize, fill_style: Style) -> Vec<Span<'static>> {
    let frac = if frac.is_finite() { frac.clamp(0.0, 1.0) } else { 0.0 };
    let filled = (frac * width as f64).round() as usize;
    vec![
        Span::styled("▓".repeat(filled), fill_style),
        Span::styled("░".repeat(width.saturating_sub(filled)), Theme::dim()),
    ]
}

fn fmt_elapsed(secs: u64) -> String {
    if secs < 60 { format!("{}s", secs) }
    else { format!("{}m {:02}s", secs / 60, secs % 60) }
}

fn trunc(s: &str, max: usize) -> String {
    if s.chars().count() <= max { s.to_string() }
    else { format!("{}…", s.chars().take(max - 1).collect::<String>()) }
}
