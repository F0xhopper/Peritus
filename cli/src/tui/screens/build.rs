use std::collections::VecDeque;
use std::sync::Arc;
use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    style::Modifier,
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
pub enum FetcherState { Waiting, Fetching, Done(u64), Skipped }

pub struct BuildCardInfo {
    pub topic: String,
    pub stage: u8,
    pub stage_label: String,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq)]
enum LogLevel { Stage, Success, Info, Error }

struct LogEntry { msg: String, level: LogLevel }

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
    stage: u8,
    stage_name: String,
    // Discovery
    fetchers: indexmap::IndexMap<String, FetcherState>,
    // Plan
    key_concepts: Vec<String>,
    // Validation
    validate_passed: u64,
    validate_dropped: u64,
    validate_total: u64,
    // Ingestion
    ingest_recent: VecDeque<(String, u64)>, // (title, chunks), newest at back
    ingest_count: u64,
    ingest_total: u64,
    // Graph
    graph_batches: u64,
    graph_total_batches: u64,
    graph_total_nodes: usize,
    graph_total_edges: u64,
    // Persona
    persona_name: Option<String>,
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
            stage: 0,
            stage_name: String::new(),
            fetchers: indexmap::IndexMap::new(),
            key_concepts: vec![],
            validate_passed: 0,
            validate_dropped: 0,
            validate_total: 0,
            ingest_recent: VecDeque::with_capacity(20),
            ingest_count: 0,
            ingest_total: 0,
            graph_batches: 0,
            graph_total_batches: 0,
            graph_total_nodes: 0,
            graph_total_edges: 0,
            persona_name: None,
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
        self.log_lines.push_back(LogEntry { msg: msg.into(), level });
    }

    /// Reset per-attempt progress. A retry re-runs the whole pipeline, so stale
    /// counters from the failed attempt would double-count. The activity log is
    /// kept — it is the user's record of what happened.
    fn reset_progress(&mut self) {
        self.stage = 0;
        self.stage_name.clear();
        self.fetchers.clear();
        self.key_concepts.clear();
        self.validate_passed = 0;
        self.validate_dropped = 0;
        self.validate_total = 0;
        self.ingest_recent.clear();
        self.ingest_count = 0;
        self.ingest_total = 0;
        self.graph_batches = 0;
        self.graph_total_batches = 0;
        self.graph_total_nodes = 0;
        self.graph_total_edges = 0;
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
                    for f in fetchers { self.fetchers.insert(f.clone(), FetcherState::Waiting); }
                    for f in active   { self.fetchers.insert(f.clone(), FetcherState::Fetching); }
                    self.log(format!("Starting {} source fetchers", fetchers.len()), LogLevel::Info);
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
                    self.log(
                        format!("Triage: {} candidates → {} ranked (budget {})", candidates, ranked, budget),
                        LogLevel::Success,
                    );
                }
                BuildEvent::FetchDone { fetched, budget } => {
                    self.log(format!("Fetched {} of {} budgeted sources", fetched, budget), LogLevel::Success);
                }
                BuildEvent::SnowballDone { added } => {
                    self.log(format!("Snowball: +{} sources", added), LogLevel::Success);
                }
                BuildEvent::SourceValidated { title, passed, q, r } => {
                    let short = trunc(title, 44);
                    // q/r are the validator's 0–10 quality/relevance scores.
                    if *passed {
                        self.validate_passed += 1;
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
                    self.log(format!("★ Graph ready — {} concepts, {} edges", nodes, edges), LogLevel::Success);
                }
                BuildEvent::StageDegraded { stage, message } => {
                    self.log(format!("⚠ {} stage degraded: {}", stage, trunc(message, 100)), LogLevel::Error);
                }
                BuildEvent::ResolveProgress { merged } => {
                    self.log(format!("Resolving duplicates… {} merged", merged), LogLevel::Info);
                }
                BuildEvent::SourceIngested { title, chunks } => {
                    let short = trunc(title, 44);
                    self.ingest_count += 1;
                    if self.ingest_recent.len() >= 20 { self.ingest_recent.pop_front(); }
                    self.ingest_recent.push_back((short.clone(), *chunks));
                    self.log(format!("{} ({} chunks)", short, chunks), LogLevel::Success);
                }
                BuildEvent::GraphBatchDone { labels, edges } => {
                    self.graph_batches += 1;
                    self.graph_total_nodes += labels.len();
                    self.graph_total_edges += edges;
                    self.log(format!("Batch {}: {} concepts, {} edges", self.graph_batches, labels.len(), edges), LogLevel::Success);
                }
                BuildEvent::EntitiesResolved { merged } => {
                    self.log(format!("Resolved: {} concepts merged", merged), LogLevel::Success);
                }
                BuildEvent::PersonaReady { name } => {
                    self.persona_name = Some(name.clone());
                    self.log(format!("Persona: {}", name), LogLevel::Success);
                }
                BuildEvent::Done { source_count, chunk_count, node_count, edge_count, persona_name } => {
                    self.done = true;
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

        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(2),  // pipeline header
                Constraint::Min(6),     // stage-specific content
                Constraint::Length(10), // activity log
                Constraint::Length(1),  // footer
            ])
            .split(inner);

        self.render_pipeline(f, chunks[0]);
        self.render_stage_content(f, chunks[1], tick);
        self.render_log(f, chunks[2]);
        self.render_footer(f, chunks[3], tick);
    }

    fn render_pipeline(&self, f: &mut Frame, area: Rect) {
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
            if i > 0 { spans.push(Span::styled("  ──  ", Theme::dim())); }
            spans.push(Span::styled(format!("{} {}", icon, label), style));
        }
        f.render_widget(
            Paragraph::new(Line::from(spans))
                .block(Block::default().borders(Borders::BOTTOM).border_style(Theme::normal_border())),
            area,
        );
    }

    fn render_stage_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        match self.stage {
            0 => self.render_plan_content(f, area, tick),
            1 => self.render_discovery_content(f, area, tick),
            2 => self.render_validate_content(f, area, tick),
            3 => self.render_ingest_content(f, area),
            // 4 graph, 5 persona — the graph panel surfaces the persona once ready.
            _ => self.render_graph_content(f, area, tick),
        }
    }

    fn render_plan_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let block = content_block("Planning");
        let inner = block.inner(area);
        f.render_widget(block, area);

        if self.key_concepts.is_empty() {
            f.render_widget(
                Paragraph::new(vec![
                    Line::from(Span::styled(
                        "Studying your topic to decide which sources will teach the expert the most.",
                        Theme::dim().add_modifier(Modifier::ITALIC),
                    )),
                    Line::from(""),
                    Line::from(vec![
                        Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                        Span::styled("Identifying key concepts…", Theme::dim()),
                    ]),
                ]),
                inner,
            );
        } else {
            let mut concept_spans: Vec<Span> = vec![Span::styled("Concepts:  ", Theme::dim())];
            for (i, c) in self.key_concepts.iter().enumerate() {
                if i > 0 { concept_spans.push(Span::styled("  ·  ", Theme::dim())); }
                concept_spans.push(Span::styled(c.as_str(), Theme::normal()));
            }
            f.render_widget(
                Paragraph::new(vec![
                    Line::from(Span::styled("Plan ready", Theme::success().add_modifier(Modifier::BOLD))),
                    Line::from(""),
                    Line::from(concept_spans),
                ]).wrap(Wrap { trim: true }),
                inner,
            );
        }
    }

    fn render_discovery_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let done_count = self.fetchers.values().filter(|s| matches!(s, FetcherState::Done(_) | FetcherState::Skipped)).count();
        let total_count = self.fetchers.len();
        let block = Block::default()
            .title(format!(" Source Discovery  ·  {}/{} done ", done_count, total_count))
            .title_style(Theme::dim())
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::normal_border());
        let inner = block.inner(area);
        f.render_widget(block, area);

        let split = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(2), Constraint::Min(1)])
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
                FetcherState::Waiting => Line::from(vec![
                    Span::styled("○  ", Theme::dim()),
                    Span::styled(name.as_str(), Theme::dim()),
                ]),
                FetcherState::Fetching => Line::from(vec![
                    Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent().add_modifier(Modifier::BOLD)),
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
    }

    fn render_validate_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let block = content_block("Quality Validation");
        let inner = block.inner(area);
        f.render_widget(block, area);

        let total = self.validate_passed + self.validate_dropped;
        let bar_line = if total > 0 {
            let bar_w = 24usize;
            let filled = ((self.validate_passed as f64 / total as f64) * bar_w as f64).round() as usize;
            let empty  = bar_w.saturating_sub(filled);
            Line::from(vec![
                Span::styled("▓".repeat(filled), Theme::success()),
                Span::styled("░".repeat(empty),  Theme::dim()),
                Span::styled(format!("  {}/{} kept", self.validate_passed, total), Theme::dim()),
            ])
        } else {
            Line::from(Span::styled("Waiting for sources…", Theme::dim()))
        };

        f.render_widget(
            Paragraph::new(vec![
                Line::from(Span::styled(
                    "Reading each source and scoring how well it covers your topic.",
                    Theme::dim().add_modifier(Modifier::ITALIC),
                )),
                Line::from(""),
                Line::from(vec![
                    Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                    Span::styled("Scoring relevance and quality…", Theme::dim()),
                ]),
                Line::from(""),
                bar_line,
                Line::from(""),
                Line::from(vec![
                    Span::styled("✓ ", Theme::success()),
                    Span::styled(format!("{}", self.validate_passed), Theme::success().add_modifier(Modifier::BOLD)),
                    Span::styled(" accepted    ", Theme::dim()),
                    Span::styled("✗ ", Theme::dim()),
                    Span::styled(format!("{}", self.validate_dropped), Theme::normal()),
                    Span::styled(" dropped", Theme::dim()),
                ]),
            ]),
            inner,
        );
    }

    fn render_ingest_content(&self, f: &mut Frame, area: Rect) {
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

        let split = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(2), Constraint::Min(1)])
            .split(inner);

        f.render_widget(
            Paragraph::new(vec![
                Line::from(Span::styled(
                    "Breaking approved sources into chunks and encoding them as embeddings.",
                    Theme::dim().add_modifier(Modifier::ITALIC),
                )),
                Line::from(""),
            ]),
            split[0],
        );

        let h = split[1].height as usize;
        let items: Vec<ListItem> = self.ingest_recent.iter()
            .rev()
            .take(h)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .map(|(title, chunks)| {
                ListItem::new(Line::from(vec![
                    Span::styled("✓  ", Theme::success()),
                    Span::styled(title.as_str(), Theme::normal()),
                    Span::styled(format!("  {} chunks", chunks), Theme::dim()),
                ]))
            })
            .collect();
        f.render_widget(List::new(items), split[1]);
    }

    fn render_graph_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let block = content_block("Knowledge Graph");
        let inner = block.inner(area);
        f.render_widget(block, area);

        let mut lines = vec![
            Line::from(Span::styled(
                "Extracting concepts and relationships to wire up your expert's knowledge map.",
                Theme::dim().add_modifier(Modifier::ITALIC),
            )),
            Line::from(""),
            Line::from(vec![
                Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                Span::styled("Building graph…", Theme::dim()),
            ]),
            Line::from(""),
            Line::from(vec![
                Span::styled(
                    if self.graph_total_batches > 0 {
                        format!("{}/{}", self.graph_batches, self.graph_total_batches)
                    } else {
                        format!("{}", self.graph_batches)
                    },
                    Theme::accent().add_modifier(Modifier::BOLD),
                ),
                Span::styled(" batches  ·  ", Theme::dim()),
                Span::styled(format!("{}", self.graph_total_nodes), Theme::normal().add_modifier(Modifier::BOLD)),
                Span::styled(" concepts  ·  ", Theme::dim()),
                Span::styled(format!("{}", self.graph_total_edges), Theme::normal().add_modifier(Modifier::BOLD)),
                Span::styled(" edges", Theme::dim()),
            ]),
        ];
        if let Some(name) = &self.persona_name {
            lines.push(Line::from(""));
            lines.push(Line::from(vec![
                Span::styled("✓  Persona created: ", Theme::success()),
                Span::styled(name.as_str(), Theme::normal().add_modifier(Modifier::BOLD)),
            ]));
        }
        f.render_widget(Paragraph::new(lines), inner);
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
                ListItem::new(Span::styled(entry.msg.as_str(), style))
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
            let chat_hint = if self.chat_ready { "  ·  ★ chat-ready — [Esc] then Enter to chat now" } else { "" };
            Paragraph::new(format!(
                "{}  {}  ·  {}{}  ·  [Esc] Home (build keeps running)  ·  [x] Cancel build",
                spin, stage_description_for(self.stage), elapsed, chat_hint,
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

fn fmt_elapsed(secs: u64) -> String {
    if secs < 60 { format!("{}s", secs) }
    else { format!("{}m {:02}s", secs / 60, secs % 60) }
}

fn trunc(s: &str, max: usize) -> String {
    if s.chars().count() <= max { s.to_string() }
    else { format!("{}…", s.chars().take(max - 1).collect::<String>()) }
}
