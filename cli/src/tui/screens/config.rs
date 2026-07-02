use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph},
};
use crate::config::store::Config;
use crate::events::AppAction;
use crate::tui::theme::Theme;
use crate::tui::widgets::input_box::TextInput;

pub struct ConfigScreen {
    pub config: Config,
    pub saved: bool,
    field: usize, // 0 = server_url, 1 = api_key
    pub editing: bool,
    edit: TextInput,
    // Snapshot at open, so the screen can show an "unsaved changes" indicator.
    persisted: Config,
}

impl ConfigScreen {
    pub fn new(config: Config) -> Self {
        Self {
            persisted: config.clone(),
            config,
            saved: false,
            field: 0,
            editing: false,
            edit: TextInput::new(),
        }
    }

    fn dirty(&self) -> bool {
        self.config.server_url != self.persisted.server_url
            || self.config.api_key != self.persisted.api_key
    }

    fn commit_edit(&mut self) {
        let value = self.edit.take_trimmed();
        match self.field {
            0 => self.config.server_url = value,
            1 => self.config.api_key = value,
            _ => {}
        }
        self.editing = false;
    }

    pub fn handle(&mut self, action: AppAction) {
        match action {
            AppAction::Up if !self.editing => { self.field = 0; }
            AppAction::Down if !self.editing => { self.field = 1; }
            AppAction::Tab => {
                if self.editing { self.commit_edit(); }
                self.field = (self.field + 1) % 2;
            }
            // Enter toggles edit on a field and commits it — but does NOT save, so the
            // user can edit both fields before saving with Ctrl+S.
            AppAction::Submit => {
                if self.editing {
                    self.commit_edit();
                } else {
                    self.editing = true;
                    self.edit = TextInput::from(match self.field {
                        0 => &self.config.server_url,
                        1 => &self.config.api_key,
                        _ => "",
                    });
                }
            }
            // Ctrl+S persists everything and exits setup.
            AppAction::Save => {
                if self.editing { self.commit_edit(); }
                self.config.configured = true;
                self.saved = true;
            }
            AppAction::Back => { self.editing = false; }
            // Editing keys flow to the focused field.
            other if self.editing => match other {
                AppAction::Char(c)     => self.edit.insert(c),
                AppAction::Backspace   => self.edit.backspace(),
                AppAction::Delete      => self.edit.delete(),
                AppAction::CursorLeft  => self.edit.left(),
                AppAction::CursorRight => self.edit.right(),
                AppAction::WordLeft    => self.edit.word_left(),
                AppAction::WordRight   => self.edit.word_right(),
                AppAction::Home        => self.edit.home(),
                AppAction::End         => self.edit.end(),
                AppAction::CtrlW       => self.edit.delete_word_back(),
                AppAction::CtrlU       => self.edit.kill_to_start(),
                AppAction::KillToEnd   => self.edit.kill_to_end(),
                _ => {}
            },
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

        let field_w = inner.width.saturating_sub(14) as usize;

        let url_line = self.field_line(FieldSpec {
            label: "Server URL: ",
            field: 0,
            value: &self.config.server_url,
            placeholder: "(e.g. http://localhost:8000)",
            mask: false,
        }, field_w);
        let key_line = self.field_line(FieldSpec {
            label: "API Key:    ",
            field: 1,
            value: &self.config.api_key,
            placeholder: "(optional — leave blank for a local server)",
            mask: true,
        }, field_w);

        f.render_widget(
            Paragraph::new(url_line)
                .block(Block::default().borders(Borders::BOTTOM).border_style(Theme::dim())),
            chunks[0],
        );
        f.render_widget(
            Paragraph::new(key_line)
                .block(Block::default().borders(Borders::BOTTOM).border_style(Theme::dim())),
            chunks[1],
        );

        // Unsaved-changes indicator so Enter (confirm field) isn't mistaken for save.
        if self.dirty() && !self.editing {
            f.render_widget(
                Paragraph::new("● unsaved changes — press Ctrl+S to save").style(Theme::warning()),
                chunks[2],
            );
        }

        let hint = if self.editing {
            "[Enter] Confirm field  [←→/Home/End] Move  [Ctrl+U/K/W] Kill  [Esc] Cancel"
        } else {
            "[↑↓/Tab] Navigate  [Enter] Edit field  [Ctrl+S] Save & continue  [Esc] Back"
        };
        f.render_widget(Paragraph::new(hint).style(Theme::dim()), chunks[3]);
    }

    fn field_line(&self, spec: FieldSpec<'_>, width: usize) -> Line<'static> {
        let style = if self.field == spec.field { Theme::accent() } else { Theme::dim() };
        let mut spans = vec![Span::styled(spec.label, style)];
        if self.editing && self.field == spec.field {
            spans.extend(self.edit.spans(width, style, true));
        } else if spec.value.is_empty() {
            spans.push(Span::styled(spec.placeholder, style));
        } else if spec.mask {
            spans.push(Span::styled("████████████████", style));
        } else {
            spans.push(Span::styled(spec.value.to_string(), style));
        }
        Line::from(spans)
    }
}

struct FieldSpec<'a> {
    label: &'static str,
    field: usize,
    value: &'a str,
    placeholder: &'static str,
    mask: bool,
}
