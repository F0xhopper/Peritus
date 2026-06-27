use std::collections::VecDeque;
use std::sync::Arc;
use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    style::Modifier,
    symbols,
    text::{Line, Span},
    widgets::{Block, BorderType, Borders, LineGauge, List, ListItem, Paragraph},
};
use tokio::sync::{mpsc, Notify};
use futures_util::StreamExt;

use crate::api::client::ApiClient;
use crate::api::types::BuildEvent;
use crate::tui::theme::Theme;
use crate::tui::widgets::spinner;

#[derive(Debug, Clone, PartialEq)]
pub enum FetcherState { Waiting, Fetching, Done(u64), Skipped }

pub struct BuildScreen {
    topic: String,
    stage: u8,
    stage_name: String,
    stage_total: u64,
    fetchers: indexmap::IndexMap<String, FetcherState>,
    log_lines: VecDeque<String>,
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
            stage_name: "plan".into(),
            stage_total: 0,
            fetchers: indexmap::IndexMap::new(),
            log_lines: VecDeque::with_capacity(500),
            done: false,
            error: None,
            rx,
            cancel,
        }
    }

    /// Signal the background stream task to stop.
    pub fn cancel(&self) {
        self.cancel.notify_one();
    }

    fn log(&mut self, msg: impl Into<String>) {
        if self.log_lines.len() >= 500 { self.log_lines.pop_front(); }
        self.log_lines.push_back(msg.into());
    }

    pub async fn tick(&mut self) -> bool {
        while let Ok(event) = self.rx.try_recv() {
            match &event {
                BuildEvent::Stage { stage, name, total, .. } => {
                    self.stage = *stage;
                    self.stage_name = name.clone();
                    self.stage_total = *total;
                    self.log(format!("Stage {}: {}", stage, name));
                }
                BuildEvent::PlanReady { key_concepts } => {
                    self.log(format!("Plan ready — concepts: {}", key_concepts.join(", ")));
                }
                BuildEvent::DiscoveryStarted { fetchers, active } => {
                    // All known fetchers start Waiting, then active ones flip to Fetching.
                    for f in fetchers {
                        self.fetchers.insert(f.clone(), FetcherState::Waiting);
                    }
                    for f in active {
                        self.fetchers.insert(f.clone(), FetcherState::Fetching);
                    }
                    self.log(format!("Discovering via {} fetchers", fetchers.len()));
                }
                BuildEvent::FetcherDone { name, count, skipped } => {
                    let state = if *skipped { FetcherState::Skipped } else { FetcherState::Done(*count) };
                    self.fetchers.insert(name.clone(), state);
                    self.log(format!("{}: {} sources", name, count));
                }
                BuildEvent::SnowballDone { added } => {
                    self.log(format!("Snowball: +{} sources", added));
                }
                BuildEvent::SourceValidated { title, passed, score } => {
                    let status = if *passed { "✓" } else { "✗" };
                    self.log(format!("{} {} ({:.2})", status, title, score));
                }
                BuildEvent::ValidateDone { passed, dropped } => {
                    self.log(format!("Validated: {} passed, {} dropped", passed, dropped));
                }
                BuildEvent::SourceIngested { title, chunks, .. } => {
                    self.log(format!("Ingested: {} ({} chunks)", title, chunks));
                }
                BuildEvent::GraphBatchDone { labels, edges } => {
                    self.log(format!("Graph batch: {} labels, {} edges", labels.len(), edges));
                }
                BuildEvent::EntitiesResolved { merged } => {
                    self.log(format!("Entities resolved: {} merged", merged));
                }
                BuildEvent::PersonaReady { name } => {
                    self.log(format!("Persona: {}", name));
                }
                BuildEvent::Done { .. } => {
                    self.done = true;
                    self.log("Build complete!");
                    return true;
                }
                BuildEvent::Error { message } => {
                    self.error = Some(message.clone());
                    self.log(format!("ERROR: {}", message));
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
                Constraint::Length(1), // LineGauge stage bar
                Constraint::Min(4),    // fetcher list
                Constraint::Length(12),// event log
                Constraint::Length(1), // footer
            ])
            .split(inner);

        // Stage progress — LineGauge renders the fill and label in one line.
        let total_stages = 5u8;
        let ratio = if total_stages == 0 { 0.0 } else { self.stage as f64 / total_stages as f64 };
        let stage_label = format!(
            " Stage {}/{} — {}",
            self.stage, total_stages,
            self.stage_name.to_uppercase(),
        );
        f.render_widget(
            LineGauge::default()
                .ratio(ratio.clamp(0.0, 1.0))
                .label(Line::from(Span::styled(stage_label, Theme::dim())))
                .line_set(symbols::line::THICK)
                .filled_style(Theme::accent())
                .unfilled_style(Theme::dim()),
            chunks[0],
        );

        // Fetcher list — braille spinner animates next to active fetchers.
        let fetcher_items: Vec<ListItem> = self.fetchers.iter().map(|(name, state)| {
            let line = match state {
                FetcherState::Waiting => Line::from(vec![
                    Span::styled("○ ", Theme::dim()),
                    Span::styled(name.as_str(), Theme::dim()),
                ]),
                FetcherState::Fetching => Line::from(vec![
                    // Braille spinner in Peritus-blue for active fetchers.
                    Span::styled(
                        format!("{} ", spinner::braille(tick)),
                        Theme::accent().add_modifier(Modifier::BOLD),
                    ),
                    Span::styled(name.as_str(), Theme::accent()),
                ]),
                FetcherState::Done(n) => Line::from(vec![
                    Span::styled("✓ ", Theme::success()),
                    Span::styled(name.as_str(), Theme::normal()),
                    Span::styled(format!("  {} sources", n), Theme::dim()),
                ]),
                FetcherState::Skipped => Line::from(vec![
                    Span::styled("– ", Theme::dim()),
                    Span::styled(name.as_str(), Theme::dim()),
                    Span::styled("  skipped", Theme::dim().add_modifier(Modifier::ITALIC)),
                ]),
            };
            ListItem::new(line)
        }).collect();

        let fetcher_list = List::new(fetcher_items)
            .block(Block::default()
                .title(" Fetchers ")
                .borders(Borders::ALL)
                .border_style(Theme::normal_border()));
        f.render_widget(fetcher_list, chunks[1]);

        // Event log — most recent events at the bottom.
        let log_height = chunks[2].height as usize;
        let log_items: Vec<ListItem> = self.log_lines.iter()
            .rev()
            .take(log_height)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .map(|l| ListItem::new(Span::styled(l.as_str(), Theme::dim())))
            .collect();
        let log_list = List::new(log_items)
            .block(Block::default()
                .title(" Event Log ")
                .borders(Borders::ALL)
                .border_style(Theme::normal_border()));
        f.render_widget(log_list, chunks[2]);

        // Footer — error or keybind hint with an animated Peritus-blue spinner.
        let footer = if let Some(err) = &self.error {
            Paragraph::new(format!("✗ {}", err)).style(Theme::error())
        } else {
            let spin = spinner::braille(tick);
            Paragraph::new(format!("{} Building… [Esc] Cancel", spin))
                .style(Theme::dim())
        };
        f.render_widget(footer, chunks[3]);
    }
}
