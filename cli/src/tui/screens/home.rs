use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    style::Modifier,
    text::{Line, Span},
    widgets::{Block, BorderType, Borders, Clear, Paragraph, Wrap},
};
use crate::api::types::{ExpertSummary, SourceOut};
use crate::events::AppAction;
use crate::tui::theme::Theme;
use crate::tui::screens::build::BuildCardInfo;
use crate::tui::widgets::avatar;
use crate::tui::widgets::input_box::TextInput;
use crate::tui::widgets::spinner;

const CARD_WIDTH: u16 = 46;

// "auto" is not sent to the server at all — the API resolves the deepest tier
// the account's plan and credit balance afford. It is the default because a
// topic alone should always be a buildable request.
const TIERS: &[(&str, &str, &str)] = &[
    ("auto",     "AUTO",     "best your plan affords"),
    ("lite",     "LITE",     "~15 sources · fast"),
    ("standard", "STANDARD", "~30 sources · balanced"),
    ("pro",      "PRO",      "~60 sources · deep"),
];
const DEFAULT_TIER_IDX: usize = 0; // AUTO

pub struct HomeScreen {
    pub experts: Vec<ExpertSummary>,
    pub selected: usize,
    pub input_active: bool,
    pub confirm_delete: bool,
    pub tier_select_active: bool,
    tier_selected: usize,   // index into TIERS
    pending_topic: Option<String>,
    input: TextInput,
    submitted_build: Option<(String, String)>, // (topic, tier)
    scroll_offset: usize,
    // ── sources overlay ──────────────────────────────────────────────────
    // Fetched on demand rather than carried on ExpertSummary: a corpus is up to
    // ~60 rows per expert, and the home list would pay for all of them on every
    // refresh to show something only ever looked at one expert at a time.
    pub sources_active: bool,
    pub sources_slug: Option<String>,
    sources: Vec<SourceOut>,
    sources_loading: bool,
    sources_error: Option<String>,
    sources_scroll: usize,
}

impl HomeScreen {
    pub fn new() -> Self {
        Self {
            experts: vec![],
            selected: 0,
            input_active: false,
            confirm_delete: false,
            tier_select_active: false,
            tier_selected: DEFAULT_TIER_IDX,
            pending_topic: None,
            input: TextInput::new(),
            submitted_build: None,
            scroll_offset: 0,
            sources_active: false,
            sources_slug: None,
            sources: vec![],
            sources_loading: false,
            sources_error: None,
            sources_scroll: 0,
        }
    }

    /// Open the overlay in its loading state; the fetch result arrives later via
    /// `set_sources`/`set_sources_error`.
    pub fn open_sources(&mut self, slug: String) {
        self.sources_active = true;
        self.sources_slug = Some(slug);
        self.sources.clear();
        self.sources_error = None;
        self.sources_loading = true;
        self.sources_scroll = 0;
    }

    pub fn close_sources(&mut self) {
        self.sources_active = false;
        self.sources_slug = None;
        self.sources.clear();
        self.sources_error = None;
        self.sources_loading = false;
        self.sources_scroll = 0;
    }

    /// Late results for an expert the user has since navigated away from are
    /// dropped: the slug they were requested for must still be the open one.
    pub fn set_sources(&mut self, slug: &str, sources: Vec<SourceOut>) {
        if self.sources_slug.as_deref() != Some(slug) { return; }
        self.sources = sources;
        self.sources_loading = false;
        self.sources_error = None;
    }

    pub fn set_sources_error(&mut self, slug: &str, error: String) {
        if self.sources_slug.as_deref() != Some(slug) { return; }
        self.sources_loading = false;
        self.sources_error = Some(error);
    }

    pub fn sources_scroll_down(&mut self) {
        if self.sources_scroll + 1 < self.sources.len() { self.sources_scroll += 1; }
    }

    pub fn sources_scroll_up(&mut self) {
        self.sources_scroll = self.sources_scroll.saturating_sub(1);
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
        if !self.experts.is_empty() {
            // Wrap around, mirroring next().
            self.selected = (self.selected + self.experts.len() - 1) % self.experts.len();
        }
        self.confirm_delete = false;
    }

    pub fn start_new_expert_input(&mut self) {
        self.input_active = true;
        self.input.clear();
        self.confirm_delete = false;
    }

    pub fn cancel_input(&mut self) { self.input_active = false; self.input.clear(); }

    /// Route an editing action to the topic input while it is focused.
    pub fn input_edit(&mut self, action: &AppAction) {
        match action {
            AppAction::Char(c)     => self.input.insert(*c),
            AppAction::Backspace   => self.input.backspace(),
            AppAction::Delete      => self.input.delete(),
            AppAction::CursorLeft  => self.input.left(),
            AppAction::CursorRight => self.input.right(),
            AppAction::WordLeft    => self.input.word_left(),
            AppAction::WordRight   => self.input.word_right(),
            AppAction::Home        => self.input.home(),
            AppAction::End         => self.input.end(),
            AppAction::CtrlW       => self.input.delete_word_back(),
            AppAction::CtrlU       => self.input.kill_to_start(),
            AppAction::KillToEnd   => self.input.kill_to_end(),
            _ => {}
        }
    }

    pub fn submit_input(&mut self) {
        let topic = self.input.take_trimmed();
        if !topic.is_empty() {
            self.pending_topic = Some(topic);
            self.tier_selected = DEFAULT_TIER_IDX; // reset each time
            self.tier_select_active = true;
        }
        self.input_active = false;
    }

    pub fn tier_prev(&mut self) {
        if self.tier_selected > 0 { self.tier_selected -= 1; }
    }
    pub fn tier_next(&mut self) {
        if self.tier_selected < TIERS.len() - 1 { self.tier_selected += 1; }
    }
    pub fn tier_confirm(&mut self) {
        if let Some(topic) = self.pending_topic.take() {
            let tier = TIERS[self.tier_selected].0.to_string();
            self.submitted_build = Some((topic, tier));
        }
        self.tier_select_active = false;
    }
    pub fn tier_cancel(&mut self) {
        self.pending_topic = None;
        self.tier_select_active = false;
    }

    pub fn take_submitted_build(&mut self) -> Option<(String, String)> { self.submitted_build.take() }
    pub fn handle_enter(&mut self) { if self.input_active { self.submit_input(); } }

    pub fn select_by_topic(&mut self, topic: &str) {
        if let Some(idx) = self.experts.iter().rposition(|e| e.topic == topic) {
            self.selected = idx;
            self.scroll_offset = 0;
        }
    }

    pub fn render(&mut self, f: &mut Frame, area: Rect, tick: u64, build_info: Option<&BuildCardInfo>) {

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

        if self.experts.is_empty() && !self.input_active {
            let msg = "No experts yet — press [n] to build your first one";
            let msg_len = msg.chars().count() as u16;
            let cx = cards_area.x + cards_area.width.saturating_sub(msg_len) / 2;
            let cy = cards_area.y + cards_area.height / 2;
            f.render_widget(
                Paragraph::new(Line::from(Span::styled(msg, Theme::dim()))),
                Rect::new(cx, cy, msg_len.min(cards_area.width), 1),
            );
        }

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
            // Later cards must fit whole; the first card clamps to whatever
            // width there is, so a narrow terminal still shows *something*.
            if slot > 0 && x + CARD_WIDTH > cards_area.x + cards_area.width { break; }
            let w = (CARD_WIDTH - 1).min((cards_area.x + cards_area.width).saturating_sub(x));
            if w < 10 { break; }
            let card_area = Rect::new(x, cards_area.y, w, cards_area.height);

            let card_build = build_info.filter(|b| b.topic == expert.topic);
            render_expert_card(f, card_area, expert, idx == self.selected, card_build, tick);
        }

        // Scroll indicator — dots while they fit, "n/total" once the list grows.
        if self.experts.len() > visible_count {
            let indicator = if self.experts.len() <= 12 {
                self.experts.iter().enumerate()
                    .map(|(i, _)| if i == self.selected { "●" } else { "○" })
                    .collect::<Vec<_>>().join(" ")
            } else {
                format!("{} / {}", self.selected + 1, self.experts.len())
            };
            let dot_x = inner.x + inner.width.saturating_sub(indicator.chars().count() as u16) / 2;
            f.render_widget(
                Paragraph::new(indicator).style(Theme::dim()),
                Rect::new(dot_x, footer_area.y, footer_area.width, 1),
            );
        }

        // Footer hints / new-expert input
        let hint_area = Rect::new(footer_area.x, footer_area.y + 1, footer_area.width, 1);
        let selected_status = self.selected_expert().map(|e| e.status.as_str()).unwrap_or("");
        let selected_chattable = self.selected_expert().map(|e| e.can_chat()).unwrap_or(false);

        let (footer_text, hint_style) = if self.input_active {
            (String::new(), Theme::dim())
        } else if self.confirm_delete {
            let name = self.selected_expert()
                .and_then(|e| e.persona_name.as_deref().or(Some(e.name.as_str())))
                .unwrap_or("this expert");
            (format!("Delete \"{}\"?  [D] Confirm  [Esc] Cancel", name), Theme::error())
        } else if (selected_status == "building" || selected_status == "queued") && selected_chattable {
            ("[Enter] Chat now  [b] Build  [s] Sources  [n] New  [d] Delete  [q] Quit".to_string(), Theme::accent())
        } else if selected_status == "building" || selected_status == "queued" {
            ("[Enter/b] Watch Build  [s] Sources  [n] New  [d] Delete  [q] Quit".to_string(), Theme::accent())
        } else if selected_status == "failed" && !selected_chattable {
            ("[Enter] Rebuild  [s] Sources  [n] New  [d] Delete  [q] Quit".to_string(), Theme::dim())
        } else {
            ("[n] New  [Enter] Chat  [s] Sources  [d] Delete  [q] Quit".to_string(), Theme::dim())
        };
        f.render_widget(Paragraph::new(footer_text).style(hint_style), hint_area);

        if self.confirm_delete {
            if let Some(expert) = self.selected_expert() {
                let name = expert.persona_name.as_deref().unwrap_or(expert.name.as_str());
                render_confirm_popup(f, area, name);
            }
        }
        if self.input_active {
            render_input_popup(f, area, &self.input);
        }
        if self.tier_select_active {
            let topic = self.pending_topic.as_deref().unwrap_or("");
            render_tier_popup(f, area, topic, self.tier_selected);
        }
        if self.sources_active {
            self.render_sources_popup(f, area);
        }
    }

    fn render_sources_popup(&self, f: &mut Frame, area: Rect) {
        let popup_w = 78u16.min(area.width.saturating_sub(4));
        let popup_h = 24u16.min(area.height.saturating_sub(2));
        let popup = centered_rect(popup_w, popup_h, area);
        f.render_widget(Clear, popup);

        let title = match (self.sources_loading, self.sources.len()) {
            (true, _) => " Sources · loading… ".to_string(),
            (false, n) => format!(" Sources · {} ", n),
        };
        f.render_widget(
            Block::default()
                .title(title)
                .title_style(Theme::accent().add_modifier(Modifier::BOLD))
                .borders(Borders::ALL)
                .border_type(BorderType::Rounded)
                .border_style(Theme::accent())
                .style(Theme::normal()),
            popup,
        );
        let inner = Rect::new(
            popup.x + 1, popup.y + 1,
            popup.width.saturating_sub(2), popup.height.saturating_sub(2),
        );
        let split = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(1), Constraint::Length(1)])
            .split(inner);

        let mut lines: Vec<Line> = Vec::new();
        if let Some(err) = &self.sources_error {
            lines.push(Line::from(Span::styled(err.clone(), Theme::error())));
        } else if self.sources_loading {
            lines.push(Line::from(Span::styled("Fetching the corpus…", Theme::dim())));
        } else if self.sources.is_empty() {
            lines.push(Line::from(Span::styled(
                "No sources yet — this expert has no corpus.", Theme::dim())));
        } else {
            // One row per source, windowed by sources_scroll. The list is the
            // point of the overlay, so it gets every line except the footer.
            let rows = split[0].height as usize;
            let width = split[0].width as usize;
            for src in self.sources.iter().skip(self.sources_scroll).take(rows) {
                let mut spans = vec![
                    // 15 columns: the width of "thought_leaders", the longest
                    // fetcher name, so no source type is ever shown truncated.
                    Span::styled(
                        format!("{:<15} ", truncate(&src.source_type, 15)),
                        if src.is_user_supplied() { Theme::success() } else { Theme::dim() },
                    ),
                ];
                // Quality is what the validator scored it; absent for uploads,
                // which bypass validation.
                match src.quality_score {
                    Some(q) => spans.push(Span::styled(format!("{:>4.1} ", q), Theme::normal())),
                    None => spans.push(Span::styled("   · ", Theme::dim())),
                }
                spans.push(Span::styled(format!("{:>4}c ", src.chunk_count), Theme::dim()));
                // Tier as a single letter: P/S/T for primary/secondary/tertiary.
                // This is what corpus_tier_warning fires on — a corpus that is
                // mostly T is summaries about the field rather than the field.
                let (mark, style) = match src.source_tier.as_deref() {
                    Some("primary") => ("P ", Theme::success()),
                    Some("secondary") => ("S ", Theme::normal()),
                    Some("tertiary") => ("T ", Theme::error()),
                    _ => ("· ", Theme::dim()),
                };
                spans.push(Span::styled(mark, style));
                let used: usize = 15 + 1 + 5 + 5 + 2;
                spans.push(Span::styled(
                    truncate(&src.title, width.saturating_sub(used)),
                    Theme::normal(),
                ));
                lines.push(Line::from(spans));
            }
        }
        f.render_widget(Paragraph::new(lines), split[0]);

        let shown = self.sources.len().min(self.sources_scroll + split[0].height as usize);
        let footer = if self.sources.is_empty() {
            "[Esc] Close".to_string()
        } else {
            format!(
                "{}–{} of {}   [↑↓] Scroll  [Esc] Close",
                self.sources_scroll + 1, shown, self.sources.len(),
            )
        };
        f.render_widget(Paragraph::new(Span::styled(footer, Theme::dim())), split[1]);
    }
}

/// Clip to `max` columns, marking the cut with an ellipsis. Counts chars, not
/// bytes — source titles routinely carry non-ASCII.
fn truncate(s: &str, max: usize) -> String {
    if max == 0 { return String::new(); }
    if s.chars().count() <= max { return s.to_string(); }
    let keep = max.saturating_sub(1);
    s.chars().take(keep).collect::<String>() + "…"
}

fn render_expert_card(f: &mut Frame, card_area: Rect, expert: &ExpertSummary, is_selected: bool, build_info: Option<&BuildCardInfo>, tick: u64) {
    let display_name = expert.persona_name.as_deref().unwrap_or(expert.name.as_str());

    let (status_label, status_style) = match expert.status.as_str() {
        "ready" => ("✓ ready", Theme::success()),
        // Chat-ready mid-build: the corpus is embedded and answers questions
        // while the graph/persona stages are still running.
        "building" | "queued" if expert.can_chat() => ("★ chat-ready", Theme::success()),
        "building" => ("● building", Theme::warning()),
        "queued"   => ("◌ queued",   Theme::warning()),
        // e.g. a build that failed after the corpus was embedded: still usable.
        _ if expert.can_chat() => ("△ usable", Theme::warning()),
        _ => ("✗ failed", Theme::error()),
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

    // ── Top section: monogram avatar (left 8) + name/topic (right) ──────
    // Avatar is 8 chars wide; add 1-char gap before text column.
    const AVATAR_W: u16 = avatar::WIDTH + 1;
    let top_h = 3u16.min(content.height);

    for (i, line) in avatar::lines(display_name, is_selected).into_iter().enumerate() {
        if (i as u16) < top_h {
            f.render_widget(
                Paragraph::new(line),
                Rect::new(content.x, content.y + i as u16, avatar::WIDTH, 1),
            );
        }
    }

    let text_x = content.x + AVATAR_W;
    let text_w  = content.width.saturating_sub(AVATAR_W);
    if text_w > 0 {
        let name_style  = Theme::normal().add_modifier(Modifier::BOLD);
        let content_w   = text_w as usize;
        let tier_label  = expert.tier.to_uppercase();
        let right_block = format!("{}  {}", tier_label, status_label);
        let name_chars   = display_name.chars().count();
        let right_chars  = right_block.chars().count();
        let gap          = content_w.saturating_sub(name_chars + right_chars);

        // Row 0: name + tier + status
        f.render_widget(
            Paragraph::new(Line::from(vec![
                Span::styled(display_name, name_style),
                Span::raw(" ".repeat(gap)),
                Span::styled(tier_label, Theme::accent()),
                Span::raw("  "),
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

    let bottom_area = Rect::new(content.x, bottom_y, content.width, bottom_h);

    if let Some(info) = build_info {
        render_building_card_body(f, bottom_area, info, content.width, tick);
    } else {
        render_ready_card_body(f, bottom_area, expert, &sep);
    }
}

fn render_ready_card_body(f: &mut Frame, area: Rect, expert: &ExpertSummary, sep: &str) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1), // separator
            Constraint::Length(1), // concepts · sources
            Constraint::Length(1), // separator
            Constraint::Min(1),    // bio
        ])
        .split(area);

    f.render_widget(Paragraph::new(Span::styled(sep, Theme::dim())), chunks[0]);
    let mut stats = vec![
        Span::styled(fmt_count(expert.node_count), Theme::normal()),
        Span::styled(" concepts", Theme::dim()),
        Span::styled("  ·  ", Theme::dim()),
        Span::styled(fmt_count(expert.source_count), Theme::normal()),
        Span::styled(" sources", Theme::dim()),
    ];
    if let Some(q) = expert.avg_quality {
        stats.push(Span::styled("  ·  ", Theme::dim()));
        stats.push(Span::styled(format!("Q {:.1}", q), Theme::normal()));
        stats.push(Span::styled(" avg", Theme::dim()));
    }
    f.render_widget(Paragraph::new(Line::from(stats)), chunks[1]);
    f.render_widget(Paragraph::new(Span::styled(sep, Theme::dim())), chunks[2]);

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
    f.render_widget(Paragraph::new(body_lines).wrap(Wrap { trim: true }), chunks[3]);
}

fn render_building_card_body(f: &mut Frame, area: Rect, info: &BuildCardInfo, content_w: u16, tick: u64) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1), // separator
            Constraint::Length(1), // stage name + [N/5]
            Constraint::Length(1), // detail stats
            Constraint::Length(1), // separator
            Constraint::Min(0),    // mini pipeline
        ])
        .split(area);

    let sep: String = "─".repeat(content_w as usize);

    f.render_widget(Paragraph::new(Span::styled(sep.as_str(), Theme::dim())), chunks[0]);

    // Stage name line with [N/6] right-aligned (stage is 0-based, 6 stages total)
    let indicator = format!("[{}/6]", info.stage.min(5) + 1);
    let spin = spinner::braille(tick);
    let label_max = (content_w as usize).saturating_sub(3 + indicator.len() + 1);
    let label_trunc: String = info.stage_label.chars().take(label_max).collect();
    let pad = (content_w as usize)
        .saturating_sub(2 + label_trunc.chars().count() + 1 + indicator.len());
    f.render_widget(
        Paragraph::new(Line::from(vec![
            Span::styled(format!("{}  ", spin), Theme::accent()),
            Span::styled(label_trunc, Theme::accent().add_modifier(Modifier::BOLD)),
            Span::styled(" ".repeat(pad), Theme::normal()),
            Span::styled(indicator, Theme::dim()),
        ])),
        chunks[1],
    );

    // Detail stats
    f.render_widget(
        Paragraph::new(Span::styled(info.detail.as_str(), Theme::dim())),
        chunks[2],
    );

    f.render_widget(Paragraph::new(Span::styled(sep.as_str(), Theme::dim())), chunks[3]);

    // Mini pipeline: ✓ Plan  ✓ Find  ● Score  ○ Read  ○ Graph  ○ Voice
    // Indexed by the backend's 0-based stage number (5 = persona/"Voice").
    const MINI: &[&str] = &["Plan", "Find", "Score", "Read", "Graph", "Voice"];
    let mut spans: Vec<Span> = Vec::new();
    for (i, label) in MINI.iter().enumerate() {
        let stage_num = i as u8;
        if i > 0 { spans.push(Span::styled(" ", Theme::dim())); }
        let (icon, style) = if stage_num < info.stage {
            ("✓", Theme::success())
        } else if stage_num == info.stage {
            ("●", Theme::accent().add_modifier(Modifier::BOLD))
        } else {
            ("○", Theme::dim())
        };
        spans.push(Span::styled(format!("{} {}", icon, label), style));
    }
    f.render_widget(Paragraph::new(Line::from(spans)), chunks[4]);
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

fn render_input_popup(f: &mut Frame, area: Rect, input: &TextInput) {
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
    let mut line = vec![Span::styled("> ", Theme::accent())];
    line.extend(input.spans(inner.width.saturating_sub(3) as usize, Theme::normal(), true));
    f.render_widget(
        Paragraph::new(vec![
            Line::from(Span::styled("Topic:", Theme::dim())),
            Line::from(line),
        ]),
        inner,
    );
}

fn render_tier_popup(f: &mut Frame, area: Rect, topic: &str, selected: usize) {
    let popup_w = 76u16.min(area.width.saturating_sub(4));
    let popup = centered_rect(popup_w, 8, area);
    f.render_widget(Clear, popup);
    f.render_widget(
        Block::default()
            .title(format!(" Select tier for \"{}\" ", topic))
            .title_style(Theme::title())
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::selected_border())
            .style(Theme::normal()),
        popup,
    );
    let inner = Rect::new(popup.x + 2, popup.y + 1, popup.width.saturating_sub(4), popup.height.saturating_sub(2));

    // One column per tier
    let col_w = (inner.width / TIERS.len() as u16).max(1);
    for (i, (_, label, desc)) in TIERS.iter().enumerate() {
        let is_sel = i == selected;
        let x = inner.x + i as u16 * col_w;
        let col = Rect::new(x, inner.y, col_w, inner.height.saturating_sub(1));

        let (icon, name_style, desc_style) = if is_sel {
            ("●", Theme::accent().add_modifier(Modifier::BOLD), Theme::normal())
        } else {
            ("○", Theme::dim(), Theme::dim())
        };

        f.render_widget(
            Paragraph::new(vec![
                Line::from(Span::styled(format!("{} {}", icon, label), name_style)),
                Line::from(Span::styled(*desc, desc_style)),
            ]),
            col,
        );
    }

    // Footer hint
    f.render_widget(
        Paragraph::new(Line::from(vec![
            Span::styled("[←→] ", Theme::accent()),
            Span::styled("Choose  ", Theme::dim()),
            Span::styled("[Enter] ", Theme::accent()),
            Span::styled("Confirm  ", Theme::dim()),
            Span::styled("[Esc] ", Theme::accent()),
            Span::styled("Cancel", Theme::dim()),
        ])),
        Rect::new(inner.x, inner.y + inner.height.saturating_sub(1), inner.width, 1),
    );
}

fn centered_rect(width: u16, height: u16, area: Rect) -> Rect {
    let x = area.x + area.width.saturating_sub(width) / 2;
    let y = area.y + area.height.saturating_sub(height) / 2;
    Rect::new(x, y, width.min(area.width), height.min(area.height))
}
