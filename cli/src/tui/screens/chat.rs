use std::sync::Arc;
use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    style::Modifier,
    text::{Line, Span, Text},
    widgets::{
        Block, BorderType, Borders, Paragraph, Scrollbar, ScrollbarOrientation, ScrollbarState, Wrap,
    },
};
use crate::tui::markdown;
use tokio::sync::mpsc;
use futures_util::StreamExt;

use crate::api::client::ApiClient;
use crate::api::types::{ChatEvent, ChatMessage, ChatRequest, ExpertSummary, SourceCitation};
use crate::tui::theme::Theme;
use crate::tui::widgets::input_box::TextInput;
use crate::tui::widgets::spinner;

/// What the app loop should do after a key reaches the chat screen.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ChatExit { Stay, Back, Quit }

#[derive(Debug, Clone)]
pub struct Message {
    pub role: String,
    pub content: String,
    pub sources: Vec<SourceCitation>,
    /// The retrieval traversed a `contradicts` edge — sources disagree.
    pub has_contradiction: bool,
}

pub struct ChatScreen {
    expert: ExpertSummary,
    api: Arc<ApiClient>,
    pub messages: Vec<Message>,
    current_stream: Option<String>,
    current_status: Option<String>,
    pending_sources: Vec<SourceCitation>,
    pending_contradiction: bool,
    input: TextInput,
    rx: Option<mpsc::Receiver<ChatEvent>>,
    scroll_offset: usize, // lines scrolled up from the bottom (0 = pinned to bottom)
}

impl ChatScreen {
    pub fn new(expert: ExpertSummary, api: Arc<ApiClient>) -> Self {
        Self {
            expert,
            api,
            messages: vec![],
            current_stream: None,
            current_status: None,
            pending_sources: vec![],
            pending_contradiction: false,
            input: TextInput::new(),
            rx: None,
            scroll_offset: 0,
        }
    }

    /// Slug of the expert this screen is chatting with — used to decide whether an
    /// existing chat can be resumed rather than discarded.
    pub fn expert_slug(&self) -> &str {
        &self.expert.name
    }

    // Chat owns its own key mapping so ALL printable chars reach the input buffer.
    pub async fn handle_raw(&mut self, key: KeyEvent) -> ChatExit {
        const CTRL: KeyModifiers = KeyModifiers::CONTROL;
        const ALT: KeyModifiers = KeyModifiers::ALT;
        match (key.code, key.modifiers) {
            (KeyCode::Esc, _) => return ChatExit::Back,
            (KeyCode::Char('c'), CTRL) => return ChatExit::Quit,

            (KeyCode::Enter, _) => self.submit().await,

            // Readline-style editing.
            (KeyCode::Char('u'), CTRL) => self.input.kill_to_start(),
            (KeyCode::Char('k'), CTRL) => self.input.kill_to_end(),
            (KeyCode::Char('w'), CTRL) | (KeyCode::Backspace, ALT) => self.input.delete_word_back(),
            (KeyCode::Char('a'), CTRL) => self.input.home(),
            (KeyCode::Char('e'), CTRL) => self.input.end(),
            (KeyCode::Left, CTRL) | (KeyCode::Left, ALT) | (KeyCode::Char('b'), ALT) => {
                self.input.word_left()
            }
            (KeyCode::Right, CTRL) | (KeyCode::Right, ALT) | (KeyCode::Char('f'), ALT) => {
                self.input.word_right()
            }
            (KeyCode::Left, _)  => self.input.left(),
            (KeyCode::Right, _) => self.input.right(),
            (KeyCode::Home, _)  => self.input.home(),

            // Scrolling. End moves the cursor while typing, snaps to bottom otherwise.
            (KeyCode::Up, _)     => self.scroll_offset = self.scroll_offset.saturating_add(1),
            (KeyCode::Down, _)   => self.scroll_offset = self.scroll_offset.saturating_sub(1),
            (KeyCode::PageUp, _) => self.scroll_offset = self.scroll_offset.saturating_add(10),
            (KeyCode::PageDown, _) => self.scroll_offset = self.scroll_offset.saturating_sub(10),
            (KeyCode::End, _) => {
                if self.input.is_empty() { self.scroll_offset = 0; } else { self.input.end(); }
            }

            (KeyCode::Backspace, _) => self.input.backspace(),
            (KeyCode::Delete, _)    => self.input.delete(),

            // Every printable char — j, k, q, n, d, etc. — goes to the input buffer.
            // Other Ctrl-chords are deliberately ignored rather than inserted.
            (KeyCode::Char(c), KeyModifiers::NONE) | (KeyCode::Char(c), KeyModifiers::SHIFT) => {
                self.input.insert(c)
            }

            _ => {}
        }
        ChatExit::Stay
    }

    async fn submit(&mut self) {
        let question = self.input.text().trim().to_string();
        if question.is_empty() || self.rx.is_some() { return; }

        // History is the conversation BEFORE this question — the server appends the
        // question itself, so including it here would send it twice.
        let history: Vec<ChatMessage> = self.messages.iter()
            .filter(|m| !m.content.is_empty())
            .map(|m| ChatMessage { role: m.role.clone(), content: m.content.clone() })
            .collect();

        self.messages.push(Message {
            role: "user".into(),
            content: question.clone(),
            sources: vec![],
            has_contradiction: false,
        });
        self.input.clear();
        self.pending_sources.clear();
        self.pending_contradiction = false;
        self.current_stream = Some(String::new());
        self.current_status = None;
        self.scroll_offset = 0; // snap to bottom on send

        let (tx, rx) = mpsc::channel::<ChatEvent>(256);
        self.rx = Some(rx);
        let api = self.api.clone();
        let slug = self.expert.name.clone();
        let req = ChatRequest { question, history };
        tokio::spawn(async move {
            match api.chat_stream(&slug, req).await {
                Ok(mut stream) => {
                    while let Some(result) = stream.next().await {
                        match result {
                            Ok(ev)  => { let _ = tx.send(ev).await; }
                            Err(e)  => { let _ = tx.send(ChatEvent::Error { message: e.to_string() }).await; break; }
                        }
                    }
                }
                Err(e) => { let _ = tx.send(ChatEvent::Error { message: e.to_string() }).await; }
            }
        });
    }

    pub async fn tick(&mut self) {
        let events: Vec<ChatEvent> = match &mut self.rx {
            Some(rx) => { let mut b = Vec::new(); while let Ok(ev) = rx.try_recv() { b.push(ev); } b }
            None     => return,
        };
        let mut close_rx = false;
        for event in events {
            match event {
                ChatEvent::Status { message } => {
                    // Only show status while no tokens have arrived yet.
                    if self.current_stream.as_deref() == Some("") {
                        self.current_status = Some(message);
                    }
                }
                ChatEvent::Token { text } => {
                    self.current_status = None; // status replaced by actual text
                    if let Some(b) = &mut self.current_stream { b.push_str(&text); }
                }
                ChatEvent::Sources { citations, has_contradiction } => {
                    self.pending_sources = citations;
                    self.pending_contradiction = has_contradiction;
                }
                ChatEvent::Done => {
                    if let Some(text) = self.current_stream.take() {
                        self.messages.push(Message {
                            role: "assistant".into(),
                            content: text,
                            sources: std::mem::take(&mut self.pending_sources),
                            has_contradiction: std::mem::take(&mut self.pending_contradiction),
                        });
                    }
                    self.current_status = None;
                    close_rx = true;
                }
                ChatEvent::Error { message } => {
                    // Preserve any text streamed before the error rather than dropping it.
                    let partial = self.current_stream.take().unwrap_or_default();
                    let content = if partial.trim().is_empty() {
                        format!("Error: {}", message)
                    } else {
                        format!("{partial}\n\n_[interrupted: {message}]_")
                    };
                    self.current_status = None;
                    self.messages.push(Message {
                        role: "assistant".into(),
                        content,
                        sources: std::mem::take(&mut self.pending_sources),
                        has_contradiction: std::mem::take(&mut self.pending_contradiction),
                    });
                    close_rx = true;
                }
                ChatEvent::Unknown => {}
            }
        }
        if close_rx { self.rx = None; }
    }

    pub fn render(&mut self, f: &mut Frame, area: Rect, tick: u64) {
        let expert_name = self.expert.persona_name.as_deref().unwrap_or(&self.expert.name);

        let block = Block::default()
            .title(format!(" ◈ {} — {} ", expert_name, self.expert.topic))
            .title_style(Theme::title())
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::selected_border())
            .style(Theme::normal());
        let inner = block.inner(area);
        f.render_widget(block, area);

        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(5), Constraint::Length(3), Constraint::Length(1)])
            .split(inner);

        // -1 width so the Scrollbar can occupy the rightmost column of chunks[0].
        let para_width = chunks[0].width.saturating_sub(1);
        let view_height = chunks[0].height as usize;

        // Build the full chat Text — Paragraph handles wrapping natively so each
        // message is just a Vec<Line> of pre-wrap logical lines (split on newlines
        // from the LLM).  Long lines are wrapped by Paragraph::wrap at render time.
        let mut lines: Vec<Line> = Vec::new();

        for msg in &self.messages {
            if msg.role == "user" {
                lines.push(Line::from(vec![
                    Span::styled("You  ", Theme::accent().add_modifier(Modifier::BOLD)),
                    Span::styled(msg.content.as_str(), Theme::normal()),
                ]));
            } else {
                lines.push(Line::from(Span::styled(
                    expert_name,
                    Theme::accent2().add_modifier(Modifier::BOLD),
                )));
                lines.extend(markdown::render(&msg.content));
                if msg.has_contradiction {
                    lines.push(Line::from(Span::styled(
                        "⚠ The sources disagree on parts of this — note the tensions above",
                        Theme::warning().add_modifier(Modifier::ITALIC),
                    )));
                }
                if !msg.sources.is_empty() {
                    lines.push(Line::from(Span::styled(
                        "Sources cited",
                        Theme::dim().add_modifier(Modifier::UNDERLINED),
                    )));
                    // Numbers match the inline [n] markers in the answer above.
                    for src in &msg.sources {
                        lines.push(Line::from(vec![
                            Span::styled(format!("[{}] ", src.n), Theme::warning()),
                            Span::styled(src.label.as_str(), Theme::source()),
                        ]));
                    }
                }
            }
            lines.push(Line::from("")); // spacer between messages
        }

        // In-flight streaming bubble.
        if let Some(buf) = &self.current_stream {
            lines.push(Line::from(Span::styled(
                expert_name,
                Theme::accent2().add_modifier(Modifier::BOLD),
            )));
            if buf.is_empty() {
                // No tokens yet — show the current pipeline status with a spinner.
                let label = self.current_status.as_deref().unwrap_or("Thinking…");
                lines.push(Line::from(vec![
                    Span::styled(spinner::dots(tick), Theme::accent()),
                    Span::styled(format!(" {}", label), Theme::dim()),
                ]));
            } else {
                // Tokens arriving — render markdown and attach the pulse cursor.
                let mut md_lines = markdown::render(buf);
                if let Some(last) = md_lines.last_mut() {
                    last.spans.push(Span::styled(spinner::pulse(tick), Theme::accent()));
                } else {
                    md_lines.push(Line::from(Span::styled(spinner::pulse(tick), Theme::accent())));
                }
                lines.extend(md_lines);
            }
        }

        // Build Paragraph — this is the single source of truth for wrapping.
        let para = Paragraph::new(Text::from(lines)).wrap(Wrap { trim: false });

        // Use line_count to know the total rendered height and cap scroll_offset.
        let total_rendered = para.line_count(para_width);
        let max_scroll = total_rendered.saturating_sub(view_height);

        // While streaming and not manually scrolled, stay pinned to the bottom.
        if self.current_stream.is_some() && self.scroll_offset == 0 {
            // scroll_from_top = max_scroll (bottom) — no change needed.
        }
        if self.scroll_offset > max_scroll { self.scroll_offset = max_scroll; }

        // scroll_offset=0 → show the end; scroll_offset=max → show the beginning.
        let scroll_from_top = max_scroll.saturating_sub(self.scroll_offset);

        let para_area = Rect::new(chunks[0].x, chunks[0].y, para_width, chunks[0].height);
        f.render_widget(para.scroll((scroll_from_top as u16, 0)), para_area);

        // Scrollbar — rendered over chunks[0]; it uses only the rightmost column.
        let mut sb_state = ScrollbarState::new(max_scroll).position(scroll_from_top);
        f.render_stateful_widget(
            Scrollbar::new(ScrollbarOrientation::VerticalRight)
                .begin_symbol(Some("▲"))
                .end_symbol(Some("▼"))
                .thumb_style(Theme::accent())
                .track_style(Theme::dim()),
            chunks[0],
            &mut sb_state,
        );

        // Input box — a real block cursor while idle, a busy spinner while streaming.
        let mut input_line = vec![Span::styled("> ", Theme::accent())];
        let input_w = chunks[1].width.saturating_sub(4) as usize;
        input_line.extend(self.input.spans(input_w, Theme::normal(), self.rx.is_none()));
        if self.rx.is_some() {
            input_line.push(Span::styled(format!(" {}", spinner::dots(tick)), Theme::accent()));
        }
        f.render_widget(
            Paragraph::new(Line::from(input_line))
                .block(Block::default().borders(Borders::TOP).border_style(Theme::normal_border())),
            chunks[1],
        );

        // Footer hints
        f.render_widget(
            Paragraph::new("[Enter] Send  [Esc] Back  [↑↓/PgUp/PgDn] Scroll  [←→ Home/Ctrl+A/E] Cursor  [Ctrl+U/K/W] Kill")
                .style(Theme::dim()),
            chunks[2],
        );
    }
}
