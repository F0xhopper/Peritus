use ratatui::style::{Color, Modifier, Style};

pub struct Theme;

impl Theme {
    pub const BG: Color = Color::Black;
    pub const FG: Color = Color::White;
    pub const ACCENT: Color = Color::Cyan;
    pub const SUCCESS: Color = Color::Green;
    pub const WARNING: Color = Color::Yellow;
    pub const ERROR: Color = Color::Red;
    pub const DIM: Color = Color::DarkGray;
    pub const SELECTED_BG: Color = Color::DarkGray;

    pub fn normal() -> Style { Style::default().fg(Self::FG).bg(Self::BG) }
    pub fn accent() -> Style { Style::default().fg(Self::ACCENT) }
    pub fn success() -> Style { Style::default().fg(Self::SUCCESS) }
    pub fn warning() -> Style { Style::default().fg(Self::WARNING) }
    pub fn error() -> Style { Style::default().fg(Self::ERROR) }
    pub fn dim() -> Style { Style::default().fg(Self::DIM) }
    pub fn title() -> Style { Style::default().fg(Self::ACCENT).add_modifier(Modifier::BOLD) }
    pub fn selected_border() -> Style { Style::default().fg(Self::ACCENT) }
    pub fn normal_border() -> Style { Style::default().fg(Self::DIM) }
}
