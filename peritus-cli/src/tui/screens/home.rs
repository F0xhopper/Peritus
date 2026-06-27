use ratatui::{
    Frame,
    layout::Rect,
    style::{Modifier, Style},
    text::{Line, Span},
    widgets::{Block, BorderType, Borders, Paragraph},
};
use crate::api::types::ExpertSummary;
use crate::tui::theme::Theme;

pub struct HomeScreen {
    pub experts: Vec<ExpertSummary>,
    pub selected: usize,
    pub input_active: bool,
    input_buf: String,
    submitted_topic: Option<String>,
}

impl HomeScreen {
    pub fn new() -> Self {
        Self { experts: vec![], selected: 0, input_active: false, input_buf: String::new(), submitted_topic: None }
    }

    pub fn update_experts(&mut self, experts: Vec<ExpertSummary>) {
        self.experts = experts;
        if self.selected >= self.experts.len() && !self.experts.is_empty() {
            self.selected = self.experts.len() - 1;
        }
    }

    pub fn selected_expert(&self) -> Option<&ExpertSummary> {
        self.experts.get(self.selected)
    }

    pub fn next(&mut self) {
        if !self.experts.is_empty() {
            self.selected = (self.selected + 1) % self.experts.len();
        }
    }

    pub fn prev(&mut self) {
        if !self.experts.is_empty() {
            self.selected = self.selected.saturating_sub(1);
        }
    }

    pub fn start_new_expert_input(&mut self) {
        self.input_active = true;
        self.input_buf.clear();
    }

    pub fn input_push(&mut self, c: char) { self.input_buf.push(c); }
    pub fn input_pop(&mut self) { self.input_buf.pop(); }
    pub fn cancel_input(&mut self) { self.input_active = false; self.input_buf.clear(); }

    pub fn submit_input(&mut self) {
        if !self.input_buf.trim().is_empty() {
            self.submitted_topic = Some(self.input_buf.trim().to_string());
        }
        self.input_active = false;
        self.input_buf.clear();
    }

    pub fn take_submitted_topic(&mut self) -> Option<String> {
        self.submitted_topic.take()
    }

    pub fn handle_enter(&mut self) {
        if self.input_active {
            self.submit_input();
        }
    }

    pub fn render(&mut self, f: &mut Frame, area: Rect) {
        let outer = Block::default()
            .title(" Peritus ")
            .borders(Borders::ALL)
            .border_style(Theme::accent());
        let inner = outer.inner(area);
        f.render_widget(outer, area);

        // Cards layout
        let cols = 2usize;
        let card_width = inner.width / cols as u16;
        let card_height = 8u16;

        for (i, expert) in self.experts.iter().enumerate() {
            let col = (i % cols) as u16;
            let row = (i / cols) as u16;
            let x = inner.x + col * card_width;
            let y = inner.y + row * card_height;
            if y + card_height > inner.y + inner.height.saturating_sub(4) { break; }
            let card_area = Rect::new(x, y, card_width.saturating_sub(1), card_height);

            let is_selected = i == self.selected;
            let border_style = if is_selected { Theme::selected_border() } else { Theme::normal_border() };
            let status_style = match expert.status.as_str() {
                "ready" => Theme::success(),
                "building" => Theme::warning(),
                _ => Theme::error(),
            };
            let status_icon = match expert.status.as_str() {
                "ready" => "✓",
                "building" => "●",
                _ => "✗",
            };
            let name = expert.persona_name.as_deref().unwrap_or(&expert.name);
            let lines = vec![
                Line::from(Span::styled(name, Style::default().add_modifier(Modifier::BOLD))),
                Line::from(Span::styled(expert.topic.as_str(), Theme::dim())),
                Line::from(vec![
                    Span::styled(status_icon, status_style),
                    Span::raw(format!(" {} sources", expert.source_count)),
                ]),
                Line::from(Span::raw(format!("  {} chunks", expert.chunk_count))),
                Line::from(Span::raw(format!("  {} nodes", expert.node_count))),
            ];
            let block = Block::default()
                .borders(Borders::ALL)
                .border_style(border_style)
                .border_type(if is_selected { BorderType::Double } else { BorderType::Plain });
            let para = Paragraph::new(lines).block(block);
            f.render_widget(para, card_area);
        }

        // Footer
        let footer_y = inner.y + inner.height.saturating_sub(2);
        let footer_area = Rect::new(inner.x, footer_y, inner.width, 2);
        let footer_text = if self.input_active {
            format!("New expert topic: {}█", self.input_buf)
        } else {
            "[n] New  [Enter] Chat  [d] Delete  [q] Quit  [↑↓] Navigate".to_string()
        };
        f.render_widget(Paragraph::new(footer_text).style(Theme::dim()), footer_area);
    }
}
