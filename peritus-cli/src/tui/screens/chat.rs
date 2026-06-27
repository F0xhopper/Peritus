use std::sync::Arc;
use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    widgets::{Block, Borders, List, ListItem, Paragraph},
};
use tokio::sync::mpsc;
use futures_util::StreamExt;

use crate::api::client::ApiClient;
use crate::api::types::{ChatEvent, ChatMessage, ChatRequest, ExpertSummary};
use crate::events::AppAction;
use crate::tui::theme::Theme;

#[derive(Debug, Clone)]
pub struct Message {
    pub role: String,
    pub content: String,
}

pub struct ChatScreen {
    expert: ExpertSummary,
    api: Arc<ApiClient>,
    pub messages: Vec<Message>,
    current_stream: Option<String>,
    input_buf: String,
    sources: Vec<String>,
    rx: Option<mpsc::Receiver<ChatEvent>>,
}

impl ChatScreen {
    pub fn new(expert: ExpertSummary, api: Arc<ApiClient>) -> Self {
        Self {
            expert,
            api,
            messages: vec![],
            current_stream: None,
            input_buf: String::new(),
            sources: vec![],
            rx: None,
        }
    }

    pub async fn handle(&mut self, action: AppAction) -> bool {
        match action {
            AppAction::Back => { return true; }
            AppAction::Char(c) => { self.input_buf.push(c); }
            AppAction::Backspace => { self.input_buf.pop(); }
            AppAction::Submit => {
                let question = self.input_buf.trim().to_string();
                if !question.is_empty() && self.rx.is_none() {
                    self.messages.push(Message { role: "user".into(), content: question.clone() });
                    self.input_buf.clear();
                    self.sources.clear();
                    self.current_stream = Some(String::new());
                    let history: Vec<ChatMessage> = self.messages.iter().map(|m| ChatMessage {
                        role: m.role.clone(), content: m.content.clone()
                    }).collect();
                    let req = ChatRequest { question, history };
                    let (tx, rx) = mpsc::channel::<ChatEvent>(256);
                    self.rx = Some(rx);
                    let api = self.api.clone();
                    let slug = self.expert.name.clone();
                    tokio::spawn(async move {
                        match api.chat_stream(&slug, req).await {
                            Ok(mut stream) => {
                                while let Some(result) = stream.next().await {
                                    match result {
                                        Ok(event) => { let _ = tx.send(event).await; }
                                        Err(e) => { let _ = tx.send(ChatEvent::Error { message: e.to_string() }).await; break; }
                                    }
                                }
                            }
                            Err(e) => { let _ = tx.send(ChatEvent::Error { message: e.to_string() }).await; }
                        }
                    });
                }
            }
            AppAction::CtrlU => { self.input_buf.clear(); }
            AppAction::CtrlW => {
                let trimmed = self.input_buf.trim_end();
                let new_end = trimmed.rfind(|c: char| c.is_whitespace()).map(|i| i + 1).unwrap_or(0);
                self.input_buf.truncate(new_end);
            }
            _ => {}
        }
        false
    }

    pub async fn tick(&mut self) {
        // Collect events without holding a borrow on self.rx inside the loop body
        let events: Vec<ChatEvent> = if let Some(rx) = &mut self.rx {
            let mut buf = Vec::new();
            while let Ok(ev) = rx.try_recv() {
                buf.push(ev);
            }
            buf
        } else {
            return;
        };

        let mut close_rx = false;
        for event in events {
            match event {
                ChatEvent::Token { text } => {
                    if let Some(buf) = &mut self.current_stream { buf.push_str(&text); }
                }
                ChatEvent::Sources { citations } => { self.sources = citations; }
                ChatEvent::Done => {
                    if let Some(text) = self.current_stream.take() {
                        self.messages.push(Message { role: "assistant".into(), content: text });
                    }
                    close_rx = true;
                }
                ChatEvent::Error { message } => {
                    if let Some(_text) = self.current_stream.take() {
                        self.messages.push(Message { role: "assistant".into(), content: format!("Error: {}", message) });
                    }
                    close_rx = true;
                }
                ChatEvent::Unknown => {}
            }
        }
        if close_rx {
            self.rx = None;
        }
    }

    pub fn render(&mut self, f: &mut Frame, area: Rect) {
        let expert_name = self.expert.persona_name.as_deref().unwrap_or(&self.expert.name);
        let block = Block::default()
            .title(format!(" {} — {} ", expert_name, self.expert.topic))
            .borders(Borders::ALL)
            .border_style(Theme::accent());
        let inner = block.inner(area);
        f.render_widget(block, area);

        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(5), Constraint::Length(3), Constraint::Length(1)])
            .split(inner);

        // Chat history
        let mut lines: Vec<ListItem> = vec![];
        for msg in &self.messages {
            let prefix = if msg.role == "user" { "You: ".to_string() } else { format!("{}: ", expert_name) };
            let style = if msg.role == "user" { Theme::accent() } else { Theme::normal() };
            lines.push(ListItem::new(format!("{}{}", prefix, msg.content)).style(style));
            lines.push(ListItem::new("").style(Theme::dim()));
        }
        if let Some(buf) = &self.current_stream {
            let prefix = format!("{}: ", expert_name);
            lines.push(ListItem::new(format!("{}{}▌", prefix, buf)).style(Theme::normal()));
        }

        // Show most recent lines that fit
        let history_height = chunks[0].height as usize;
        let start = lines.len().saturating_sub(history_height);
        let visible: Vec<ListItem> = lines.into_iter().skip(start).collect();
        let history_list = List::new(visible)
            .block(Block::default().borders(Borders::BOTTOM).border_style(Theme::dim()));
        f.render_widget(history_list, chunks[0]);

        // Input
        let input_display = format!("> {}█", self.input_buf);
        let input = Paragraph::new(input_display)
            .block(Block::default().borders(Borders::NONE))
            .style(Theme::normal());
        f.render_widget(input, chunks[1]);

        // Footer
        let footer = Paragraph::new("[Enter] Send  [Esc] Back  [Ctrl+U] Clear").style(Theme::dim());
        f.render_widget(footer, chunks[2]);
    }
}
