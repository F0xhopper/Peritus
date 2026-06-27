use std::collections::VecDeque;
use std::sync::Arc;
use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    widgets::{Block, Borders, List, ListItem, Paragraph},
};
use tokio::sync::mpsc;
use futures_util::StreamExt;

use crate::api::client::ApiClient;
use crate::api::types::BuildEvent;
use crate::tui::theme::Theme;

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
}

impl BuildScreen {
    pub fn new(topic: String, api: Arc<ApiClient>) -> Self {
        let (tx, rx) = mpsc::channel::<BuildEvent>(256);
        let api_clone = api.clone();
        let topic_clone = topic.clone();
        tokio::spawn(async move {
            match api_clone.build_stream(topic_clone).await {
                Ok(mut stream) => {
                    while let Some(result) = stream.next().await {
                        match result {
                            Ok(event) => {
                                let _ = tx.send(event).await;
                            }
                            Err(e) => {
                                let _ = tx.send(BuildEvent::Error { message: e.to_string() }).await;
                                break;
                            }
                        }
                    }
                }
                Err(e) => {
                    let _ = tx.send(BuildEvent::Error { message: e.to_string() }).await;
                }
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
        }
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
                BuildEvent::DiscoveryStarted { fetchers, .. } => {
                    for f in fetchers {
                        self.fetchers.insert(f.clone(), FetcherState::Waiting);
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

    pub fn render(&mut self, f: &mut Frame, area: Rect) {
        let block = Block::default()
            .title(format!(" Building: \"{}\" ", self.topic))
            .borders(Borders::ALL)
            .border_style(Theme::accent());
        let inner = block.inner(area);
        f.render_widget(block, area);

        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(3), Constraint::Min(4), Constraint::Length(12), Constraint::Length(1)])
            .split(inner);

        // Stage bar
        let total_stages = 5u8;
        let fill = (self.stage as u16 * chunks[0].width) / total_stages as u16;
        let bar: String = "■".repeat(fill as usize) + &"░".repeat((chunks[0].width.saturating_sub(fill)) as usize);
        let stage_text = format!("Stage {}/{} {} {}", self.stage, total_stages, bar, self.stage_name.to_uppercase());
        f.render_widget(Paragraph::new(stage_text).style(Theme::accent()), chunks[0]);

        // Fetcher list
        let fetcher_items: Vec<ListItem> = self.fetchers.iter().map(|(name, state)| {
            let (icon, style) = match state {
                FetcherState::Waiting => ("○", Theme::dim()),
                FetcherState::Fetching => ("●", Theme::warning()),
                FetcherState::Done(_) => ("✓", Theme::success()),
                FetcherState::Skipped => ("✗", Theme::dim()),
            };
            let label = match state {
                FetcherState::Done(n) => format!("{} {}   {} sources", icon, name, n),
                _ => format!("{} {}", icon, name),
            };
            ListItem::new(label).style(style)
        }).collect();
        let fetcher_list = List::new(fetcher_items)
            .block(Block::default().title(" Fetchers ").borders(Borders::ALL).border_style(Theme::dim()));
        f.render_widget(fetcher_list, chunks[1]);

        // Log panel
        let log_items: Vec<ListItem> = self.log_lines.iter().rev().take(chunks[2].height as usize).rev()
            .map(|l| ListItem::new(l.as_str()).style(Theme::dim()))
            .collect();
        let log_list = List::new(log_items)
            .block(Block::default().title(" Event Log ").borders(Borders::ALL).border_style(Theme::dim()));
        f.render_widget(log_list, chunks[2]);

        // Footer
        let footer = if let Some(err) = &self.error {
            Paragraph::new(format!("ERROR: {}", err)).style(Theme::error())
        } else {
            Paragraph::new("[Esc] Cancel").style(Theme::dim())
        };
        f.render_widget(footer, chunks[3]);
    }
}
