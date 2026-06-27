use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    widgets::{Block, Borders, Paragraph},
};
use crate::config::store::Config;
use crate::events::AppAction;
use crate::tui::theme::Theme;

pub struct ConfigScreen {
    pub config: Config,
    pub saved: bool,
    field: usize, // 0 = server_url, 1 = api_key
    pub editing: bool,
    edit_buf: String,
}

impl ConfigScreen {
    pub fn new(config: Config) -> Self {
        Self { config, saved: false, field: 0, editing: false, edit_buf: String::new() }
    }

    pub fn handle(&mut self, action: AppAction) {
        match action {
            AppAction::Up => { self.field = 0; self.editing = false; }
            AppAction::Down => { self.field = 1; self.editing = false; }
            AppAction::Tab => { self.field = (self.field + 1) % 2; self.editing = false; }
            AppAction::Submit => {
                if self.editing {
                    match self.field {
                        0 => self.config.server_url = self.edit_buf.trim().to_string(),
                        1 => self.config.api_key = self.edit_buf.trim().to_string(),
                        _ => {}
                    }
                    self.editing = false;
                    self.saved = true;
                } else {
                    self.editing = true;
                    self.edit_buf = match self.field {
                        0 => self.config.server_url.clone(),
                        1 => self.config.api_key.clone(),
                        _ => String::new(),
                    };
                }
            }
            AppAction::Char(c) if self.editing => { self.edit_buf.push(c); }
            AppAction::Backspace if self.editing => { self.edit_buf.pop(); }
            AppAction::Back => { self.editing = false; }
            _ => {}
        }
    }

    pub fn render(&mut self, f: &mut Frame, area: Rect) {
        let block = Block::default().title(" Configuration ").borders(Borders::ALL).border_style(Theme::accent());
        let inner = block.inner(area);
        f.render_widget(block, area);

        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(3), Constraint::Length(3), Constraint::Min(1), Constraint::Length(1)])
            .split(inner);

        let url_val = if self.editing && self.field == 0 { format!("{}█", self.edit_buf) } else { self.config.server_url.clone() };
        let key_val = if self.editing && self.field == 1 { format!("{}█", self.edit_buf) } else if self.config.api_key.is_empty() { "(not set)".into() } else { "████████████████".into() };

        let url_style = if self.field == 0 { Theme::accent() } else { Theme::dim() };
        let key_style = if self.field == 1 { Theme::accent() } else { Theme::dim() };

        f.render_widget(
            Paragraph::new(format!("Server URL: {}", url_val)).style(url_style)
                .block(Block::default().borders(Borders::BOTTOM).border_style(Theme::dim())),
            chunks[0],
        );
        f.render_widget(
            Paragraph::new(format!("API Key:    {}", key_val)).style(key_style)
                .block(Block::default().borders(Borders::BOTTOM).border_style(Theme::dim())),
            chunks[1],
        );

        let hint = if self.editing { "[Enter] Confirm  [Esc] Cancel" } else { "[↑↓/Tab] Navigate  [Enter] Edit & Save  [Esc] Cancel" };
        f.render_widget(Paragraph::new(hint).style(Theme::dim()), chunks[3]);
    }
}
