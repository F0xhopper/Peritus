use ratatui::style::{Color, Modifier, Style};

pub struct Theme;

impl Theme {
    // Peritus brand palette — true-color (RGB), works on all modern terminals.
    // Night-blue base keeps brand blues vibrant without eye strain.
    pub const BG: Color          = Color::Rgb(8,  9,  18);   // deep night blue
    pub const FG: Color          = Color::Rgb(215, 218, 232); // cool white
    pub const ACCENT: Color      = Color::Rgb(90,  170, 255); // Peritus blue
    pub const ACCENT2: Color     = Color::Rgb(160, 110, 255); // Peritus violet
    pub const SUCCESS: Color     = Color::Rgb(75,  210, 115); // emerald
    pub const WARNING: Color     = Color::Rgb(255, 185, 55);  // amber
    pub const ERROR: Color       = Color::Rgb(255, 75,  75);  // coral
    pub const DIM: Color         = Color::Rgb(140, 145, 170); // muted blue-grey
    pub const HIGHLIGHT: Color   = Color::Rgb(25,  35,  65);  // subtle card bg
    pub const SELECTED_BG: Color = Color::Rgb(20,  30,  60);  // selected card bg
    pub const BORDER_SEL: Color  = Color::Rgb(185, 185, 185); // selected border (near-white)
    pub const BORDER_DIM: Color  = Color::Rgb(55,  55,  55);  // unselected border (dark grey)
    pub const SOURCE: Color      = Color::Rgb(130, 100, 220); // citation violet
    pub const CODE: Color        = Color::Rgb(230, 190,  80); // warm amber for inline code
    pub const CODE_BLOCK: Color  = Color::Rgb(130, 210, 160); // muted mint for code blocks

    pub fn normal()          -> Style { Style::default().fg(Self::FG) }
    pub fn accent()          -> Style { Style::default().fg(Self::ACCENT) }
    pub fn accent2()         -> Style { Style::default().fg(Self::ACCENT2) }
    pub fn success()         -> Style { Style::default().fg(Self::SUCCESS) }
    pub fn warning()         -> Style { Style::default().fg(Self::WARNING) }
    pub fn error()           -> Style { Style::default().fg(Self::ERROR) }
    pub fn dim()             -> Style { Style::default().fg(Self::DIM) }
    pub fn source()          -> Style { Style::default().fg(Self::SOURCE) }
    pub fn selected_bg()     -> Style { Style::default() }
    pub fn title()           -> Style { Style::default().fg(Self::ACCENT).add_modifier(Modifier::BOLD) }
    pub fn selected_border() -> Style { Style::default().fg(Self::BORDER_SEL) }
    pub fn normal_border()   -> Style { Style::default().fg(Self::BORDER_DIM) }

    // Markdown rendering styles
    pub fn heading1()    -> Style { Style::default().fg(Self::FG).add_modifier(Modifier::BOLD | Modifier::UNDERLINED) }
    pub fn heading2()    -> Style { Style::default().fg(Self::ACCENT).add_modifier(Modifier::BOLD) }
    pub fn heading3()    -> Style { Style::default().fg(Self::ACCENT2).add_modifier(Modifier::BOLD) }
    pub fn code_inline() -> Style { Style::default().fg(Self::CODE) }
    pub fn code_block()  -> Style { Style::default().fg(Self::CODE_BLOCK) }
}
