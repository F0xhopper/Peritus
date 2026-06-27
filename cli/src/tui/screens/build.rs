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

const STAGES: &[(&str, &str)] = &[
    ("plan",      "Plan"),
    ("discovery", "Discover"),
    ("validate",  "Validate"),
    ("ingest",    "Ingest"),
    ("graph",     "Graph"),
];

#[derive(Debug, Clone, PartialEq)]
pub enum FetcherState { Waiting, Fetching, Done(u64), Skipped }

#[derive(Debug, Clone, PartialEq)]
enum LogLevel { Stage, Success, Info, Error }

struct LogEntry { msg: String, level: LogLevel }

pub struct BuildScreen {
    topic: String,
    stage: u8,
    stage_name: String,
    // Discovery
    fetchers: indexmap::IndexMap<String, FetcherState>,
    // Plan
    key_concepts: Vec<String>,
    // Validation
    validate_passed: u64,
    validate_dropped: u64,
    // Ingestion
    ingest_recent: VecDeque<(String, u64)>, // (title, chunks), newest at back
    ingest_count: u64,
    // Graph
    graph_batches: u64,
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
    pub fn new(topic: String, api: Arc<ApiClient>) -> Self {
        let cancel = Arc::new(Notify::new());
        let (tx, rx) = mpsc::channel::<BuildEvent>(256);
        let api_clone = api.clone();
        let topic_clone = topic.clone();
        let cancel_clone = cancel.clone();
        tokio::spawn(async move {
            tokio::select! {
                _ = cancel_clone.notified() => {}
                _ = async {
                    match api_clone.build_stream(topic_clone).await {
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
            stage: 0,
            stage_name: String::new(),
            fetchers: indexmap::IndexMap::new(),
            key_concepts: vec![],
            validate_passed: 0,
            validate_dropped: 0,
            ingest_recent: VecDeque::with_capacity(20),
            ingest_count: 0,
            graph_batches: 0,
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

    fn log(&mut self, msg: impl Into<String>, level: LogLevel) {
        if self.log_lines.len() >= 500 { self.log_lines.pop_front(); }
        self.log_lines.push_back(LogEntry { msg: msg.into(), level });
    }

    pub async fn tick(&mut self) -> bool {
        while let Ok(event) = self.rx.try_recv() {
            match &event {
                BuildEvent::Stage { stage, name, .. } => {
                    self.stage = *stage;
                    self.stage_name = name.clone();
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
                    self.error = Some(message.clone());
                    self.log(format!("Error: {}", message), LogLevel::Error);
                    return true;
                }
                BuildEvent::Unknown => {}
            }
        }
        false
    }

    pub fn render(&mut self, f: &mut Frame, area: Rect, tick: u64) {
        let block = Block::default()
            .title(format!(" ◈ Building: \"{}\" ", self.topic))
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
            0 | 1 => self.render_plan_content(f, area, tick),
            2      => self.render_discovery_content(f, area, tick),
            3      => self.render_validate_content(f, area, tick),
            4      => self.render_ingest_content(f, area),
            _      => self.render_graph_content(f, area, tick),
        }
    }

    fn render_plan_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let block = content_block("Planning");
        let inner = block.inner(area);
        f.render_widget(block, area);

        if self.key_concepts.is_empty() {
            f.render_widget(
                Paragraph::new(Line::from(vec![
                    Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                    Span::styled("Analyzing topic and planning sources…", Theme::dim()),
                ])),
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
        let block = content_block("Source Discovery");
        let inner = block.inner(area);
        f.render_widget(block, area);

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
        f.render_widget(List::new(items), inner);
    }

    fn render_validate_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let block = content_block("Quality Validation");
        let inner = block.inner(area);
        f.render_widget(block, area);

        f.render_widget(
            Paragraph::new(vec![
                Line::from(vec![
                    Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                    Span::styled("Scoring source relevance and quality…", Theme::dim()),
                ]),
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
        let block = Block::default()
            .title(format!(" Content Ingestion  ·  {} ingested ", self.ingest_count))
            .title_style(Theme::dim())
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::normal_border());
        let inner = block.inner(area);
        f.render_widget(block, area);

        let h = inner.height as usize;
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
        f.render_widget(List::new(items), inner);
    }

    fn render_graph_content(&self, f: &mut Frame, area: Rect, tick: u64) {
        let block = content_block("Knowledge Graph");
        let inner = block.inner(area);
        f.render_widget(block, area);

        let mut lines = vec![
            Line::from(vec![
                Span::styled(format!("{}  ", spinner::braille(tick)), Theme::accent()),
                Span::styled("Extracting concepts and relationships…", Theme::dim()),
            ]),
            Line::from(""),
            Line::from(vec![
                Span::styled(format!("{}", self.graph_batches), Theme::accent().add_modifier(Modifier::BOLD)),
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
                Span::styled("✓  Persona: ", Theme::success()),
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
        let widget = if let Some(err) = &self.error {
            Paragraph::new(format!("✗  {}", err)).style(Theme::error())
        } else if self.done {
            Paragraph::new("✓  Build complete!").style(Theme::success())
        } else {
            let spin = spinner::braille(tick);
            Paragraph::new(format!("{}  {}  ·  [Esc] Cancel", spin, stage_description_for(self.stage)))
                .style(Theme::dim())
        };
        f.render_widget(widget, area);
    }
}

fn stage_title_for(stage: u8) -> &'static str {
    match stage {
        1 => "Planning",
        2 => "Source Discovery",
        3 => "Quality Validation",
        4 => "Content Ingestion",
        5 => "Knowledge Graph",
        _ => "Processing",
    }
}

fn stage_description_for(stage: u8) -> &'static str {
    match stage {
        0 | 1 => "Analyzing topic and planning sources",
        2      => "Fetching sources from the web",
        3      => "Scoring source relevance and quality",
        4      => "Chunking, embedding, and indexing content",
        5      => "Extracting concepts and building knowledge graph",
        _      => "Finalizing",
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

fn trunc(s: &str, max: usize) -> String {
    if s.chars().count() <= max { s.to_string() }
    else { format!("{}…", s.chars().take(max - 1).collect::<String>()) }
}
