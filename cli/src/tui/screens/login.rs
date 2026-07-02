use ratatui::{
    Frame,
    layout::{Constraint, Direction, Layout, Rect},
    text::{Line, Span},
    widgets::{Block, BorderType, Borders, Paragraph},
};

use crate::tui::theme::Theme;

#[derive(Debug, Clone, PartialEq)]
pub enum LoginPhase {
    Email,
    Code,
}

/// Email-OTP login: enter email, receive a one-time code by email, enter the code.
/// The async request/verify calls are driven from `app.rs` (it owns the ApiClient).
pub struct LoginScreen {
    pub phase: LoginPhase,
    pub email: String,
    pub code: String,
    pub status: Option<String>,
    pub error: Option<String>,
    pub busy: bool,
}

impl LoginScreen {
    pub fn new(prefill_email: String) -> Self {
        Self {
            phase: LoginPhase::Email,
            email: prefill_email,
            code: String::new(),
            status: None,
            error: None,
            busy: false,
        }
    }

    pub fn input_push(&mut self, c: char) {
        match self.phase {
            LoginPhase::Email => self.email.push(c),
            // Codes are numeric; ignore stray non-digits so pasting is forgiving.
            LoginPhase::Code => {
                if c.is_ascii_digit() && self.code.len() < 10 {
                    self.code.push(c);
                }
            }
        }
    }

    pub fn input_pop(&mut self) {
        match self.phase {
            LoginPhase::Email => {
                self.email.pop();
            }
            LoginPhase::Code => {
                self.code.pop();
            }
        }
    }

    /// Go back to the email step (from the code step) to retry a different address.
    pub fn back_to_email(&mut self) {
        self.phase = LoginPhase::Email;
        self.code.clear();
        self.error = None;
        self.status = None;
    }

    pub fn render(&mut self, f: &mut Frame, area: Rect) {
        let block = Block::default()
            .title(" Sign in to Peritus ")
            .title_style(Theme::title())
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Theme::accent());
        let inner = block.inner(area);
        f.render_widget(block, area);

        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .margin(1)
            .constraints([
                Constraint::Length(2), // intro
                Constraint::Length(3), // email field
                Constraint::Length(3), // code field
                Constraint::Min(1),    // status / error
                Constraint::Length(1), // hint
            ])
            .split(inner);

        let intro = match self.phase {
            LoginPhase::Email => "Enter your email and we'll send you a one-time code.",
            LoginPhase::Code => "Enter the 6-digit code we emailed you.",
        };
        f.render_widget(Paragraph::new(intro).style(Theme::dim()), chunks[0]);

        let email_active = self.phase == LoginPhase::Email;
        let email_val = if self.email.is_empty() {
            "(you@example.com)".to_string()
        } else if email_active {
            format!("{}█", self.email)
        } else {
            self.email.clone()
        };
        f.render_widget(
            Paragraph::new(format!("Email:  {}", email_val))
                .style(if email_active { Theme::accent() } else { Theme::dim() })
                .block(Block::default().borders(Borders::BOTTOM).border_style(Theme::dim())),
            chunks[1],
        );

        let code_active = self.phase == LoginPhase::Code;
        let code_val = if code_active {
            format!("{}█", self.code)
        } else {
            self.code.clone()
        };
        f.render_widget(
            Paragraph::new(format!("Code:   {}", code_val))
                .style(if code_active { Theme::accent() } else { Theme::dim() })
                .block(Block::default().borders(Borders::BOTTOM).border_style(Theme::dim())),
            chunks[2],
        );

        let mut msg_lines: Vec<Line> = Vec::new();
        if self.busy {
            msg_lines.push(Line::from(Span::styled("  Working…", Theme::dim())));
        }
        if let Some(status) = &self.status {
            msg_lines.push(Line::from(Span::styled(format!("  {}", status), Theme::success())));
        }
        if let Some(err) = &self.error {
            msg_lines.push(Line::from(Span::styled(format!("  {}", err), Theme::warning())));
        }
        f.render_widget(Paragraph::new(msg_lines), chunks[3]);

        let hint = match self.phase {
            LoginPhase::Email => "[Enter] Send code   [Esc] Quit",
            LoginPhase::Code => "[Enter] Verify   [Esc] Change email",
        };
        f.render_widget(Paragraph::new(hint).style(Theme::dim()), chunks[4]);
    }
}
