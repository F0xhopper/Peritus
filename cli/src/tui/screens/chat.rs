use std::sync::Arc;
use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Modifier, Style},
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
use crate::tui::widgets::avatar;
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
    /// `[n]` markers in the answer that resolve to no real passage — the model
    /// invented them, and they must not render as legitimate citations.
    pub dangling: Vec<u32>,
}

pub struct ChatScreen {
    expert: ExpertSummary,
    api: Arc<ApiClient>,
    pub messages: Vec<Message>,
    current_stream: Option<String>,
    current_status: Option<String>,
    pending_sources: Vec<SourceCitation>,
    pending_dangling: Vec<u32>,
    input: TextInput,
    rx: Option<mpsc::Receiver<ChatEvent>>,
    // The spawned request task, kept so Esc can abort it rather than letting the
    // server stream into a dropped channel until the answer finishes.
    task: Option<tokio::task::JoinHandle<()>>,
    scroll_offset: usize, // lines scrolled up from the bottom (0 = pinned to bottom)
    // Rendered line count of the previous frame — used to keep the viewport
    // anchored on what the user is reading while new tokens grow the transcript.
    last_total: usize,
    // Questions already sent, cycled back into the input with Alt+↑/Ctrl+P.
    sent: Vec<String>,
    recall: Option<usize>, // index into `sent` while cycling; None = live draft
    draft: String,         // the in-progress input stashed when recall starts
    started: Option<std::time::Instant>, // when the in-flight question was sent
    confirm_clear: bool,   // first Ctrl+L arms, second clears the conversation
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
            pending_dangling: vec![],
            input: TextInput::new(),
            rx: None,
            task: None,
            scroll_offset: 0,
            last_total: 0,
            sent: vec![],
            recall: None,
            draft: String::new(),
            started: None,
            confirm_clear: false,
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
        // Any key other than a second Ctrl+L disarms the pending clear.
        if self.confirm_clear && (key.code, key.modifiers) != (KeyCode::Char('l'), CTRL) {
            self.confirm_clear = false;
        }
        match (key.code, key.modifiers) {
            // Esc stops an in-flight answer first; leaving the screen takes a
            // second press once nothing is streaming.
            (KeyCode::Esc, _) => {
                if self.rx.is_some() {
                    self.stop_stream();
                } else {
                    return ChatExit::Back;
                }
            }
            (KeyCode::Char('c'), CTRL) => return ChatExit::Quit,

            (KeyCode::Enter, _) => self.submit().await,

            // Ctrl+L twice starts a fresh conversation with the same expert.
            (KeyCode::Char('l'), CTRL) => {
                if self.rx.is_some() {
                    // Ignore while streaming — Esc is the stop key.
                } else if self.confirm_clear {
                    self.confirm_clear = false;
                    self.messages.clear();
                    self.scroll_offset = 0;
                } else if !self.messages.is_empty() {
                    self.confirm_clear = true;
                }
            }

            // Recall previously sent questions into the input.
            (KeyCode::Char('p'), CTRL) | (KeyCode::Up, ALT) => self.recall_prev(),
            (KeyCode::Char('n'), CTRL) | (KeyCode::Down, ALT) => self.recall_next(),

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

    /// Abort the in-flight answer. Whatever already streamed is kept as an
    /// interrupted message (matching the web client); zero tokens leaves only
    /// the question, which re-sends cleanly via history recall.
    fn stop_stream(&mut self) {
        if let Some(task) = self.task.take() { task.abort(); }
        self.rx = None;
        self.current_status = None;
        self.started = None;
        let partial = self.current_stream.take().unwrap_or_default();
        if partial.trim().is_empty() {
            self.pending_sources.clear();
            self.pending_dangling.clear();
            return;
        }
        self.messages.push(Message {
            role: "assistant".into(),
            content: format!("{partial}\n\n_[stopped]_"),
            sources: std::mem::take(&mut self.pending_sources),
            dangling: std::mem::take(&mut self.pending_dangling),
        });
    }

    fn recall_prev(&mut self) {
        if self.sent.is_empty() { return; }
        let idx = match self.recall {
            None => { self.draft = self.input.text(); self.sent.len() - 1 }
            Some(i) => i.saturating_sub(1),
        };
        self.recall = Some(idx);
        self.input = TextInput::from(&self.sent[idx]);
    }

    fn recall_next(&mut self) {
        match self.recall {
            None => {}
            Some(i) if i + 1 < self.sent.len() => {
                self.recall = Some(i + 1);
                self.input = TextInput::from(&self.sent[i + 1]);
            }
            Some(_) => {
                // Past the newest question: restore whatever was being typed.
                self.recall = None;
                self.input = TextInput::from(&std::mem::take(&mut self.draft));
            }
        }
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
            dangling: vec![],
        });
        self.input.clear();
        // Dedup an immediate re-ask (e.g. retry after an error) in the recall list.
        if self.sent.last() != Some(&question) {
            self.sent.push(question.clone());
        }
        self.recall = None;
        self.draft.clear();
        self.pending_sources.clear();
        self.pending_dangling.clear();
        self.current_stream = Some(String::new());
        self.current_status = None;
        self.started = Some(std::time::Instant::now());
        self.scroll_offset = 0; // snap to bottom on send

        let (tx, rx) = mpsc::channel::<ChatEvent>(256);
        self.rx = Some(rx);
        let api = self.api.clone();
        let slug = self.expert.name.clone();
        let req = ChatRequest { question, history };
        self.task = Some(tokio::spawn(async move {
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
        }));
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
                ChatEvent::Sources { citations, dangling_citations } => {
                    self.pending_sources = citations;
                    self.pending_dangling = dangling_citations;
                }
                ChatEvent::Done => {
                    if let Some(text) = self.current_stream.take() {
                        self.messages.push(Message {
                            role: "assistant".into(),
                            content: text,
                            sources: std::mem::take(&mut self.pending_sources),
                            dangling: std::mem::take(&mut self.pending_dangling),
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
                        dangling: std::mem::take(&mut self.pending_dangling),
                    });
                    close_rx = true;
                }
                ChatEvent::Unknown => {}
            }
        }
        if close_rx {
            self.rx = None;
            self.task = None;
            self.started = None;
        }
    }

    pub fn render(&mut self, f: &mut Frame, area: Rect, tick: u64) {
        let expert_name = self.expert.persona_name.as_deref().unwrap_or(&self.expert.name);
        // Same per-expert tone as the home-screen avatar, so the identity
        // established by the card follows the expert into the conversation.
        let expert_style = Style::default()
            .fg(avatar::tone_for(expert_name))
            .add_modifier(Modifier::BOLD);

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
                lines.push(Line::from(Span::styled(expert_name, expert_style)));
                lines.extend(markdown::render(&msg.content));
                // The stream still reports `has_contradiction` per answer, but —
                // matching the web UI — it no longer renders as a footnote. A flag
                // raised on every answer touching two sources that disagree reads
                // as a defect report on the answer rather than as a property of
                // the literature, and the answers already say so in prose where
                // it matters.
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
                if !msg.dangling.is_empty() {
                    let nums = msg.dangling.iter()
                        .map(|n| format!("[{}]", n))
                        .collect::<Vec<_>>()
                        .join(" ");
                    lines.push(Line::from(Span::styled(
                        format!("⚠ {} resolve to no source — treat those claims with care", nums),
                        Theme::warning().add_modifier(Modifier::ITALIC),
                    )));
                }
            }
            lines.push(Line::from("")); // spacer between messages
        }

        // In-flight streaming bubble.
        if let Some(buf) = &self.current_stream {
            lines.push(Line::from(Span::styled(expert_name, expert_style)));
            if buf.is_empty() {
                // No tokens yet — show the current pipeline status with a spinner
                // and how long the question has been waiting.
                let label = self.current_status.as_deref().unwrap_or("Thinking…");
                let elapsed = self.started
                    .map(|t| format!("  ({}s)", t.elapsed().as_secs()))
                    .unwrap_or_default();
                lines.push(Line::from(vec![
                    Span::styled(spinner::dots(tick), Theme::accent()),
                    Span::styled(format!(" {}", label), Theme::dim()),
                    Span::styled(elapsed, Theme::dim()),
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

        // scroll_offset counts from the bottom, so while scrolled up, streamed
        // tokens would slide the viewport off what's being read. Growing the
        // offset by the same amount keeps the view anchored; at offset 0 the
        // view stays pinned to the bottom as before.
        if self.scroll_offset > 0 && total_rendered > self.last_total {
            self.scroll_offset += total_rendered - self.last_total;
        }
        self.last_total = total_rendered;
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

        // Footer hints — context-sensitive: streaming and armed-clear states
        // change what Esc/Ctrl+L will actually do.
        let footer = if self.confirm_clear {
            "Press Ctrl+L again to start a new conversation — any other key cancels"
        } else if self.rx.is_some() {
            "[Esc] Stop answer  [↑↓/PgUp/PgDn] Scroll  [End] Bottom"
        } else {
            "[Enter] Send  [Esc] Back  [Alt+↑↓] History  [Ctrl+L] New chat  [↑↓/PgUp/PgDn] Scroll"
        };
        let footer_style = if self.confirm_clear { Theme::warning() } else { Theme::dim() };
        f.render_widget(Paragraph::new(footer).style(footer_style), chunks[2]);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::{backend::TestBackend, Terminal};

    fn expert() -> ExpertSummary {
        serde_json::from_str(
            r#"{"id":1,"name":"thomistic-metaphysics","topic":"thomistic metaphysics",
                "status":"ready","readiness":"graph_ready",
                "persona_name":"Br. Anselm","persona_bio":null,"persona_style":null,
                "avg_quality":null,"source_count":1,"chunk_count":1,"node_count":0,
                "edge_count":0,"created_at":"now"}"#,
        ).unwrap()
    }

    fn buffer_text(screen: &mut ChatScreen, w: u16, h: u16) -> String {
        let mut terminal = Terminal::new(TestBackend::new(w, h)).unwrap();
        terminal.draw(|f| { let area = f.area(); screen.render(f, area, 0); }).unwrap();
        let buf = terminal.backend().buffer().clone();
        let mut out = String::new();
        for y in 0..h {
            for x in 0..w {
                out.push_str(buf[(x, y)].symbol());
            }
            out.push('\n');
        }
        out
    }

    /// A completed exchange must actually paint both the question and the
    /// streamed answer text into the terminal buffer.
    #[test]
    fn chat_messages_render_into_buffer() {
        let api = Arc::new(ApiClient::new("http://localhost:0".into(), String::new()));
        let mut screen = ChatScreen::new(expert(), api);
        screen.messages.push(Message {
            role: "user".into(),
            content: "What is the act/potency distinction?".into(),
            sources: vec![],
            dangling: vec![],
        });
        screen.messages.push(Message {
            role: "assistant".into(),
            content: "Act is whatever is realized in a thing, while potency is what \
                      remains unrealized [1][3].\n\nOnly God is pure act."
                .into(),
            sources: vec![SourceCitation { n: 1, label: "De ente et essentia".into() }],
            dangling: vec![],
        });
        let text = buffer_text(&mut screen, 100, 30);
        assert!(text.contains("act/potency"), "user question missing:\n{text}");
        assert!(text.contains("Act is whatever is realized"), "answer text missing:\n{text}");
        assert!(text.contains("De ente et essentia"), "citation missing:\n{text}");
    }

    /// Mid-stream: the partial buffer must render, not just the spinner.
    #[test]
    fn streaming_tokens_render_into_buffer() {
        let api = Arc::new(ApiClient::new("http://localhost:0".into(), String::new()));
        let mut screen = ChatScreen::new(expert(), api);
        screen.current_stream = Some("Act is whatever is realized".into());
        let text = buffer_text(&mut screen, 100, 20);
        assert!(text.contains("Act is whatever is realized"), "partial answer missing:\n{text}");
    }

    fn screen() -> ChatScreen {
        let api = Arc::new(ApiClient::new("http://localhost:0".into(), String::new()));
        ChatScreen::new(expert(), api)
    }

    fn key(code: KeyCode, mods: KeyModifiers) -> KeyEvent {
        KeyEvent::new(code, mods)
    }

    /// Esc mid-stream stops the answer (keeping the partial text as an
    /// interrupted message) and stays on the screen; only the next Esc leaves.
    #[tokio::test]
    async fn esc_stops_stream_before_leaving() {
        let mut s = screen();
        let (_tx, rx) = mpsc::channel::<ChatEvent>(4);
        s.rx = Some(rx);
        s.current_stream = Some("A partial answer".into());

        let exit = s.handle_raw(key(KeyCode::Esc, KeyModifiers::NONE)).await;
        assert_eq!(exit, ChatExit::Stay);
        assert!(s.rx.is_none() && s.current_stream.is_none());
        let last = s.messages.last().expect("partial kept as a message");
        assert!(last.content.contains("A partial answer"));
        assert!(last.content.contains("[stopped]"));

        let exit = s.handle_raw(key(KeyCode::Esc, KeyModifiers::NONE)).await;
        assert_eq!(exit, ChatExit::Back);
    }

    /// Stopping before any token arrived leaves no empty assistant bubble.
    #[tokio::test]
    async fn esc_with_no_tokens_drops_the_bubble() {
        let mut s = screen();
        let (_tx, rx) = mpsc::channel::<ChatEvent>(4);
        s.rx = Some(rx);
        s.current_stream = Some(String::new());
        s.handle_raw(key(KeyCode::Esc, KeyModifiers::NONE)).await;
        assert!(s.messages.is_empty());
    }

    /// Alt+↑/↓ cycles sent questions and restores the stashed draft at the end.
    #[test]
    fn history_recall_cycles_and_restores_draft() {
        let mut s = screen();
        s.sent = vec!["first question".into(), "second question".into()];
        s.input = TextInput::from("dra");

        s.recall_prev();
        assert_eq!(s.input.text(), "second question");
        s.recall_prev();
        assert_eq!(s.input.text(), "first question");
        s.recall_prev(); // already oldest — stays put
        assert_eq!(s.input.text(), "first question");
        s.recall_next();
        assert_eq!(s.input.text(), "second question");
        s.recall_next(); // past newest — the draft comes back
        assert_eq!(s.input.text(), "dra");
        assert!(s.recall.is_none());
    }

    /// Ctrl+L arms, a second press clears, and any other key disarms.
    #[tokio::test]
    async fn ctrl_l_clears_only_on_confirmation() {
        const CTRL: KeyModifiers = KeyModifiers::CONTROL;
        let mut s = screen();
        s.messages.push(Message {
            role: "user".into(), content: "q".into(), sources: vec![], dangling: vec![],
        });

        s.handle_raw(key(KeyCode::Char('l'), CTRL)).await;
        assert!(s.confirm_clear && !s.messages.is_empty());

        // Any other key disarms without clearing.
        s.handle_raw(key(KeyCode::Char('x'), KeyModifiers::NONE)).await;
        assert!(!s.confirm_clear && !s.messages.is_empty());

        s.handle_raw(key(KeyCode::Char('l'), CTRL)).await;
        s.handle_raw(key(KeyCode::Char('l'), CTRL)).await;
        assert!(s.messages.is_empty());
    }
}
