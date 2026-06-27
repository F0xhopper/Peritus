use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, BorderType, Borders, Clear, Paragraph, Wrap},
};
use crate::api::types::ExpertSummary;
use crate::tui::theme::Theme;

const CARD_WIDTH: u16 = 46;

pub struct HomeScreen {
    pub experts: Vec<ExpertSummary>,
    pub selected: usize,
    pub input_active: bool,
    pub confirm_delete: bool,
    input_buf: String,
    submitted_topic: Option<String>,
    scroll_offset: usize,
}

impl HomeScreen {
    pub fn new() -> Self {
        Self {
            experts: vec![],
            selected: 0,
            input_active: false,
            confirm_delete: false,
            input_buf: String::new(),
            submitted_topic: None,
            scroll_offset: 0,
        }
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
        if !self.experts.is_empty() { self.selected = (self.selected + 1) % self.experts.len(); }
        self.confirm_delete = false;
    }

    pub fn prev(&mut self) {
        if !self.experts.is_empty() { self.selected = self.selected.saturating_sub(1); }
        self.confirm_delete = false;
    }

    pub fn start_new_expert_input(&mut self) {
        self.input_active = true;
        self.input_buf.clear();
        self.confirm_delete = false;
    }

    pub fn input_push(&mut self, c: char) { self.input_buf.push(c); }
    pub fn input_pop(&mut self)           { self.input_buf.pop(); }
    pub fn cancel_input(&mut self)        { self.input_active = false; self.input_buf.clear(); }

    pub fn submit_input(&mut self) {
        if !self.input_buf.trim().is_empty() {
            self.submitted_topic = Some(self.input_buf.trim().to_string());
        }
        self.input_active = false;
        self.input_buf.clear();
    }

    pub fn take_submitted_topic(&mut self) -> Option<String> { self.submitted_topic.take() }
    pub fn handle_enter(&mut self) { if self.input_active { self.submit_input(); } }

    pub fn render(&mut self, f: &mut Frame, area: Rect, tick: u64) {
        let _ = tick;

        let outer = Block::default()
            .title(" ◈ PERITUS  ·  talk with your experts ")
            .title_style(Theme::normal().add_modifier(Modifier::BOLD))
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::selected_border())
            .style(Theme::normal());
        let inner = outer.inner(area);
        f.render_widget(outer, area);

        // cards · 2-line footer
        let layout = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(4), Constraint::Length(2)])
            .split(inner);

        let cards_area  = layout[0];
        let footer_area = layout[1];

        let visible_count = (cards_area.width / CARD_WIDTH).max(1) as usize;

        if self.selected < self.scroll_offset {
            self.scroll_offset = self.selected;
        } else if self.selected >= self.scroll_offset + visible_count {
            self.scroll_offset = self.selected + 1 - visible_count;
        }

        for slot in 0..visible_count {
            let idx = self.scroll_offset + slot;
            if idx >= self.experts.len() { break; }
            let expert = &self.experts[idx];

            let x = cards_area.x + slot as u16 * CARD_WIDTH;
            if x + CARD_WIDTH > cards_area.x + cards_area.width { break; }
            let card_area = Rect::new(x, cards_area.y, CARD_WIDTH - 1, cards_area.height);

            render_expert_card(f, card_area, expert, idx == self.selected);
        }

        // Scroll indicator dots
        if self.experts.len() > visible_count {
            let dots: String = self.experts.iter().enumerate()
                .map(|(i, _)| if i == self.selected { "●" } else { "○" })
                .collect::<Vec<_>>().join(" ");
            let dot_x = inner.x + inner.width.saturating_sub(dots.chars().count() as u16) / 2;
            f.render_widget(
                Paragraph::new(dots).style(Theme::dim()),
                Rect::new(dot_x, footer_area.y, footer_area.width, 1),
            );
        }

        // Footer hints / new-expert input
        let hint_area = Rect::new(footer_area.x, footer_area.y + 1, footer_area.width, 1);
        let (footer_text, hint_style) = if self.input_active {
            (String::new(), Theme::dim())
        } else if self.confirm_delete {
            let name = self.selected_expert()
                .and_then(|e| e.persona_name.as_deref().or(Some(e.name.as_str())))
                .unwrap_or("this expert");
            (format!("Delete \"{}\"?  [D] Confirm  [Esc] Cancel", name), Theme::error())
        } else {
            ("[n] New  [Enter] Chat  [d] Delete  [←→] Scroll  [q] Quit".to_string(), Theme::dim())
        };
        f.render_widget(Paragraph::new(footer_text).style(hint_style), hint_area);

        if self.confirm_delete {
            if let Some(expert) = self.selected_expert() {
                let name = expert.persona_name.as_deref().unwrap_or(expert.name.as_str());
                render_confirm_popup(f, area, name);
            }
        }
        if self.input_active {
            render_input_popup(f, area, &self.input_buf);
        }
    }
}

fn render_expert_card(f: &mut Frame, card_area: Rect, expert: &ExpertSummary, is_selected: bool) {
    let display_name = expert.persona_name.as_deref().unwrap_or(expert.name.as_str());

    let (status_label, status_style) = match expert.status.as_str() {
        "ready"    => ("✓ ready",    Theme::success()),
        "building" => ("● building", Theme::warning()),
        _          => ("✗ failed",   Theme::error()),
    };

    let border_style = if is_selected { Theme::selected_border() } else { Theme::normal_border() };
    let border_type  = if is_selected { BorderType::Double } else { BorderType::Rounded };
    let block_style  = if is_selected { Theme::selected_bg() } else { Theme::normal() };

    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .border_type(border_type)
        .style(block_style);
    let inner = block.inner(card_area);
    f.render_widget(block, card_area);

    // 1-char horizontal padding inside the border
    let content = Rect::new(
        inner.x + 1,
        inner.y,
        inner.width.saturating_sub(2),
        inner.height,
    );

    let sep: String = "─".repeat(content.width as usize);

    // ── Top section: pixel-art avatar (left 8) + name/topic (right) ──────
    // Avatar is 8 chars wide; add 1-char gap before text column.
    const AVATAR_W: u16 = 9;
    let top_h = 3u16.min(content.height);

    let avatar_lines = pixel_avatar_lines(is_selected);
    for (i, line) in avatar_lines.into_iter().enumerate() {
        if (i as u16) < top_h {
            f.render_widget(
                Paragraph::new(line),
                Rect::new(content.x, content.y + i as u16, 8, 1),
            );
        }
    }

    let text_x = content.x + AVATAR_W;
    let text_w  = content.width.saturating_sub(AVATAR_W);
    if text_w > 0 {
        let name_style  = Theme::normal().add_modifier(Modifier::BOLD);
        let content_w   = text_w as usize;
        let name_chars   = display_name.chars().count();
        let status_chars = status_label.chars().count();
        let gap          = content_w.saturating_sub(name_chars + status_chars);

        // Row 0: name + status
        f.render_widget(
            Paragraph::new(Line::from(vec![
                Span::styled(display_name, name_style),
                Span::raw(" ".repeat(gap)),
                Span::styled(status_label, status_style),
            ])),
            Rect::new(text_x, content.y, text_w, 1),
        );

        // Row 1: topic
        if top_h >= 2 {
            f.render_widget(
                Paragraph::new(Span::styled(expert.topic.as_str(), Theme::dim())),
                Rect::new(text_x, content.y + 1, text_w, 1),
            );
        }
    }

    // ── Rows below avatar ─────────────────────────────────────────────────
    let bottom_y = content.y + top_h;
    let bottom_h = content.height.saturating_sub(top_h);
    if bottom_h == 0 { return; }

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1), // separator
            Constraint::Length(1), // concepts · sources
            Constraint::Length(1), // separator
            Constraint::Min(1),    // bio
        ])
        .split(Rect::new(content.x, bottom_y, content.width, bottom_h));

    f.render_widget(
        Paragraph::new(Span::styled(sep.as_str(), Theme::dim())),
        chunks[0],
    );

    f.render_widget(
        Paragraph::new(Line::from(vec![
            Span::styled(fmt_count(expert.node_count), Theme::normal()),
            Span::styled(" concepts", Theme::dim()),
            Span::styled("  ·  ", Theme::dim()),
            Span::styled(fmt_count(expert.source_count), Theme::normal()),
            Span::styled(" sources", Theme::dim()),
        ])),
        chunks[1],
    );

    f.render_widget(
        Paragraph::new(Span::styled(sep.as_str(), Theme::dim())),
        chunks[2],
    );

    let mut body_lines: Vec<Line> = Vec::new();

    if let Some(bio) = expert.persona_bio.as_deref().filter(|s| !s.is_empty()) {
        for para in bio.split('\n') {
            body_lines.push(Line::from(Span::styled(para.to_string(), Theme::dim())));
        }
        if !expert.key_concepts.is_empty() {
            body_lines.push(Line::from(""));
        }
    }

    for concept in &expert.key_concepts {
        body_lines.push(Line::from(vec![
            Span::styled("· ", Theme::accent()),
            Span::styled(concept.clone(), Theme::dim()),
        ]));
    }

    f.render_widget(
        Paragraph::new(body_lines).wrap(Wrap { trim: true }),
        chunks[3],
    );
}

// ── Pixel-art avatar ─────────────────────────────────────────────────────────

/// 8×3 block-character gem icon, coloured brighter when the card is selected.
fn pixel_avatar_lines(is_selected: bool) -> Vec<Line<'static>> {
    let rows  = ["░▒▓██▓▒░", "▒▓████▓▒", "░▒▓██▓▒░"];
    let colors: [Color; 3] = if is_selected {
        [Theme::ACCENT, Theme::ACCENT2, Theme::ACCENT]
    } else {
        [Theme::DIM, Theme::BORDER_DIM, Theme::DIM]
    };
    rows.iter().zip(colors.iter()).map(|(&s, &c)| {
        Line::from(Span::styled(s, Style::default().fg(c)))
    }).collect()
}

/// Format large numbers with K/M suffix so they fit neatly in the card.
fn fmt_count(n: u64) -> String {
    if n >= 1_000_000 { format!("{:.1}M", n as f64 / 1_000_000.0) }
    else if n >= 1_000 { format!("{:.1}K", n as f64 / 1_000.0) }
    else               { n.to_string() }
}


fn render_confirm_popup(f: &mut Frame, area: Rect, name: &str) {
    let popup_w = 50u16.min(area.width.saturating_sub(4));
    let popup = centered_rect(popup_w, 5, area);
    f.render_widget(Clear, popup);
    f.render_widget(
        Block::default()
            .title(" Confirm Delete ")
            .title_style(Theme::error().add_modifier(Modifier::BOLD))
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::error())
            .style(Theme::normal()),
        popup,
    );
    let inner = Rect::new(popup.x + 1, popup.y + 1, popup.width.saturating_sub(2), popup.height.saturating_sub(2));
    f.render_widget(
        Paragraph::new(vec![
            Line::from(vec![
                Span::raw("Delete "),
                Span::styled(format!("\"{}\"", name), Theme::error().add_modifier(Modifier::BOLD)),
                Span::raw("?"),
            ]),
            Line::from(""),
            Line::from(vec![
                Span::styled("[D] ", Theme::error().add_modifier(Modifier::BOLD)),
                Span::raw("Confirm  "),
                Span::styled("[Esc] ", Theme::accent()),
                Span::styled("Cancel", Theme::dim()),
            ]),
        ]),
        inner,
    );
}

fn render_input_popup(f: &mut Frame, area: Rect, input: &str) {
    let popup_w = 60u16.min(area.width.saturating_sub(4));
    let popup = centered_rect(popup_w, 4, area);
    f.render_widget(Clear, popup);
    f.render_widget(
        Block::default()
            .title(" New Expert ")
            .title_style(Theme::title())
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::selected_border())
            .style(Theme::normal()),
        popup,
    );
    let inner = Rect::new(popup.x + 1, popup.y + 1, popup.width.saturating_sub(2), popup.height.saturating_sub(2));
    f.render_widget(
        Paragraph::new(vec![
            Line::from(Span::styled("Topic:", Theme::dim())),
            Line::from(vec![
                Span::styled("> ", Theme::accent()),
                Span::styled(input, Theme::normal()),
                Span::styled("▌", Theme::accent()),
            ]),
        ]),
        inner,
    );
}

fn centered_rect(width: u16, height: u16, area: Rect) -> Rect {
    let x = area.x + area.width.saturating_sub(width) / 2;
    let y = area.y + area.height.saturating_sub(height) / 2;
    Rect::new(x, y, width.min(area.width), height.min(area.height))
}
