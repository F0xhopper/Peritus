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
    // Activity log
    log_lines: VecDeque<LogEntry>,
    pub done: bool,
    pub error: Option<String>,
    rx: mpsc::Receiver<BuildEvent>,
    cancel: Arc<Notify>,
}

impl BuildScreen {
    pub fn new(topic: String, tier: String, api: Arc<ApiClient>) -> Self {
        let cancel = Arc::new(Notify::new());
        let (tx, rx) = mpsc::channel::<BuildEvent>(256);
        let api_clone = api.clone();
        let topic_clone = topic.clone();
        let tier_clone = tier.clone();
        let cancel_clone = cancel.clone();
        tokio::spawn(async move {
            tokio::select! {
                _ = cancel_clone.notified() => {}
                _ = async {
                    match api_clone.build_stream(topic_clone, tier_clone).await {
                        Ok(mut stream) => {
                            while let Some(result) = stream.next().await {
                                match result {
                                    Ok(event) => { let _ = tx.send(event).await; }
                                    Err(e)    => {
                                        let _ = tx.send(BuildEvent::Error { message: e.to_string() }).await;
                                        break;
                                    }
                                }
                            }
                        }
                        Err(e) => { let _ = tx.send(BuildEvent::Error { message: e.to_string() }).await; }
                    }
                } => {}
            }
        });
        Self {
            topic,
            tier,
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
            log_lines: VecDeque::with_capacity(500),
            done: false,
            error: None,
            rx,
            cancel,
        }
    }

    pub fn cancel(&self) { self.cancel.notify_one(); }
    pub fn topic(&self) -> &str { &self.topic }

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

    pub async fn tick(&mut self) -> bool {
        while let Ok(event) = self.rx.try_recv() {
            match &event {
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
                BuildEvent::FetcherDone { name, count, skipped } => {
                    let state = if *skipped { FetcherState::Skipped } else { FetcherState::Done(*count) };
                    self.fetchers.insert(name.clone(), state);
                    if *skipped {
                        self.log(format!("{}: skipped", name), LogLevel::Info);
                    } else {
                        self.log(format!("{}: {} sources", name, count), LogLevel::Success);
                    }
                }
                BuildEvent::SnowballDone { added } => {
                    self.log(format!("Snowball: +{} sources", added), LogLevel::Success);
                }
                BuildEvent::SourceValidated { title, passed, score } => {
                    let short = trunc(title, 44);
                    if *passed {
                        self.validate_passed += 1;
                        self.log(format!("✓ {} ({:.0}%)", short, score * 100.0), LogLevel::Success);
                    } else {
                        self.validate_dropped += 1;
                        self.log(format!("✗ {} ({:.0}%)", short, score * 100.0), LogLevel::Info);
                    }
                }
                BuildEvent::ValidateDone { passed, dropped } => {
                    self.validate_passed = *passed;
                    self.validate_dropped = *dropped;
                    self.log(format!("{} accepted, {} dropped", passed, dropped), LogLevel::Success);
                }
                BuildEvent::SourceIngested { title, chunks, .. } => {
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
                BuildEvent::Done { source_count, chunk_count, node_count, .. } => {
                    self.done = true;
                    self.log(
                        format!("Done — {} sources · {} chunks · {} concepts", source_count, chunk_count, node_count),
                        LogLevel::Success,
                    );
                    return true;
                }
                BuildEvent::Error { message } => {
                    // Keep the build screen up so the error is readable. tick() only
                    // returns true on success (Done), which is what drives the
                    // "Ready to chat" navigation in the app loop.
                    self.error = Some(message.clone());
                    self.log(format!("Error: {}", message), LogLevel::Error);
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
            let stage_num = (i + 1) as u8;
            let (icon, style) = if stage_num < self.stage {
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
            Paragraph::new(format!("✗  {}  ·  {}", err, elapsed)).style(Theme::error())
        } else if self.done {
            Paragraph::new(format!("✓  Build complete!  ·  {}  ·  [Esc] Home", elapsed)).style(Theme::success())
        } else {
            let spin = spinner::braille(tick);
            Paragraph::new(format!(
                "{}  {}  ·  {}  ·  [Esc] Back to home — build keeps running",
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

fn fmt_elapsed(secs: u64) -> String {
    if secs < 60 { format!("{}s", secs) }
    else { format!("{}m {:02}s", secs / 60, secs % 60) }
}

fn trunc(s: &str, max: usize) -> String {
    if s.chars().count() <= max { s.to_string() }
    else { format!("{}…", s.chars().take(max - 1).collect::<String>()) }
}
